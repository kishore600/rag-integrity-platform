"""IntegrityService: the one object the API, CLI and scheduler talk to."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import alerts, report
from .config import Settings, get_settings
from .connectors.base import ConnectorError, UpstreamError
from .connectors.factory import Connectors, build_connectors
from .demo.world import DemoWorld
from .engine.audit import AuditOptions, inspect_document, run_reconciliation
from .engine.blast import blast_radius
from .engine.planning import estimate_workload, plan_items
from .engine.reconcile import parse_ts
from .ledger import Ledger, RunDiff, RunInProgress
from .models import ConnectionStatus, DocSummary, Finding, Scope
from .repair import RepairManager
from .security import scrub

log = logging.getLogger("ragintegrity")

# errors raised by the libraries that talk to the customer's infrastructure
_IO_MODULES = ("botocore", "boto3", "sqlalchemy", "psycopg", "httpx", "httpcore", "qdrant_client", "urllib3")


def friendly_error(exc: BaseException) -> str:
    """A specific, actionable message for a failure talking to the user's infrastructure, with passwords scrubbed."""
    mod = type(exc).__module__
    try:
        if mod.startswith(("botocore", "boto3")):
            from .connectors.s3 import _explain_s3

            return _explain_s3(exc)  # type: ignore[arg-type]
        if mod.startswith(("sqlalchemy", "psycopg")):
            from .connectors.postgres import _explain_pg

            return _explain_pg(exc)  # type: ignore[arg-type]
        if mod.startswith(("qdrant_client", "httpx", "httpcore", "urllib3")):
            from .connectors.qdrant import _explain_qdrant

            return _explain_qdrant(exc)  # type: ignore[arg-type]
    except Exception:  # an explainer must never hide the original problem
        pass
    return f"{type(exc).__name__}: {scrub(str(exc), 300)}"


def as_upstream(exc: BaseException) -> UpstreamError | None:
    if isinstance(exc, ConnectorError) or not type(exc).__module__.startswith(_IO_MODULES):
        return None
    return UpstreamError(friendly_error(exc))


class AuditBusy(RuntimeError):
    pass


@dataclass
class AuditResult:
    run_id: str
    kind: str
    stats: dict[str, Any]
    diff: RunDiff
    findings: list[Finding] = field(default_factory=list)
    summaries: list[DocSummary] = field(default_factory=list)
    alerts: dict[str, Any] = field(default_factory=dict)


class IntegrityService:
    def __init__(self, settings: Settings | None = None, ledger: Ledger | None = None,
                 connectors: Connectors | None = None, *,
                 connector_factory: Callable[[Settings], Connectors] | None = None, init_schema: bool = True) -> None:
        self.settings = settings or get_settings()
        self.ledger = ledger or Ledger(self.settings.database_url)
        if init_schema:
            self.ledger.init()
        self._connectors = connectors
        self._connector_factory = connector_factory or build_connectors  # app mode injects an SSRF-guarded factory
        self._guard: Callable[[Settings, str], None] | None = None  # set by the workspace manager in app mode
        self.callback_base: str | None = None  # origin the worker should call back to (set per request in app mode)
        self._build_lock = threading.Lock()
        self._ready = False
        self._ready_lock = threading.Lock()
        self._lock = threading.Lock()  # one audit at a time per process (the database enforces it across processes)
        self.repairs = RepairManager(self)

    # ------------------------------------------------------------------ connectors
    @property
    def connectors(self) -> Connectors:
        if self._connectors is None:
            with self._build_lock:
                if self._connectors is None:
                    self._connectors = self._connector_factory(self.settings)
        return self._connectors

    def options(self, probe: bool | None = None) -> AuditOptions:
        s = self.settings
        limit = s.audit_seconds_limit
        return AuditOptions(
            target=s.target_fingerprint(), default_tenant=s.default_tenant, required_fields=s.required_fields,
            known_tenants=self.ledger.known_tenants(), grace_minutes=s.grace_minutes,
            check_vectors=s.qdrant_check_vectors or s.is_demo, source_only=s.source_documents_only,
            probe=s.probe_retrieval if probe is None else probe, probe_max=s.probe_max, probe_top_k=s.probe_top_k,
            deadline=(time.monotonic() + limit) if limit else None,
        )

    # ------------------------------------------------------------------ audits
    def _execute(self, run_id: str, kind: str, trigger: str, scope: Scope | None, probe: bool | None) -> AuditResult:
        t0 = time.perf_counter()
        try:
            c = self.connectors
            result = run_reconciliation(c.source, c.manifest, c.index, self.options(probe), scope)
            diff = self.ledger.apply_run(run_id, result.findings, result.summaries, scope)
            stats = {**result.stats, "diff": diff.to_json(), "scope": scope.to_json() if scope else {},
                     "duration_seconds": round(time.perf_counter() - t0, 3)}
            alert = alerts.notify(self.settings, run_id, diff, stats)
            stats["alerts"] = alert
            self.ledger.finish_run(run_id, "completed", stats)
            return AuditResult(run_id, kind, stats, diff, result.findings, result.summaries, alert)
        except Exception as exc:
            up = as_upstream(exc)
            self.ledger.finish_run(run_id, "failed", {"duration_seconds": round(time.perf_counter() - t0, 3)},
                                   error=str(up) if up else f"{type(exc).__name__}: {scrub(str(exc), 500)}")
            if up is not None:
                raise up from exc
            raise

    @staticmethod
    def _kind(scope: Scope | None, kind: str | None) -> str:
        return kind or ("full" if scope is None or scope.is_full else "scoped")

    def run_audit(self, scope: Scope | None = None, trigger: str = "manual", kind: str | None = None,
                  probe: bool | None = None) -> AuditResult:
        if not self._lock.acquire(blocking=False):
            raise AuditBusy("An audit is already running.")
        try:
            kind = self._kind(scope, kind)
            _ = self.connectors  # a misconfigured or incomplete setup fails here, before a run row is created
            try:
                run_id = self.ledger.start_run(kind, trigger, scope)
            except RunInProgress as exc:
                raise AuditBusy(str(exc)) from exc
            return self._execute(run_id, kind, trigger, scope, probe)
        finally:
            self._lock.release()

    def start_audit_async(self, scope: Scope | None = None, trigger: str = "manual", probe: bool | None = None) -> str:
        if self.settings.run_audits_inline:  # serverless: a background thread would be frozen with the instance
            return self.run_audit(scope=scope, trigger=trigger, probe=probe).run_id
        if not self._lock.acquire(blocking=False):
            raise AuditBusy("An audit is already running.")
        try:
            kind = self._kind(scope, None)
            _ = self.connectors  # fail early (and without a run row) when setup is incomplete
            run_id = self.ledger.start_run(kind, trigger, scope)
        except RunInProgress as exc:
            self._lock.release()
            raise AuditBusy(str(exc)) from exc
        except Exception:
            self._lock.release()
            raise

        def work() -> None:
            try:
                self._execute(run_id, kind, trigger, scope, probe)
            except Exception:
                log.exception("audit %s failed", run_id)
            finally:
                self._lock.release()

        threading.Thread(target=work, name=f"audit-{run_id[:8]}", daemon=True).start()
        return run_id

    @property
    def audit_running(self) -> bool:
        if self._lock.locked():
            return True
        return bool(self.ledger.list_runs(limit=1, status="running"))  # another process may be running one

    # ------------------------------------------------------------------ bootstrap / demo
    def ensure_ready(self) -> None:
        """Run the one-time bootstrap lazily, once per process. Serverless hosts may not run ASGI lifespan hooks,
        and the first request after a cold start is the earliest moment we can rely on."""
        if self._ready:
            return
        with self._ready_lock:
            if not self._ready:
                self.bootstrap()
                self._ready = True

    def bootstrap(self) -> None:
        """In demo mode, make the first page load interesting: seed the query log and run a first audit."""
        if not self.settings.is_demo or self.ledger.list_runs(limit=1):
            return
        world = self.connectors.world
        if world is not None:
            self.ingest_queries(world.query_log)
        self.run_audit(trigger="bootstrap")

    def demo_reset(self, seed: int | None = None, audit: bool = True) -> None:
        if not self.settings.is_demo:
            raise ConnectorError("Demo reset is only available in demo mode.")
        if not self._lock.acquire(blocking=False):
            raise AuditBusy("An audit is already running.")
        try:
            self._connectors = build_connectors(self.settings, DemoWorld(seed=seed if seed is not None else int(time.time()) % 10_000))
            self.ledger.reset()
        finally:
            self._lock.release()
        if audit:
            self.bootstrap()

    # ------------------------------------------------------------------ read models
    def overview(self) -> dict[str, Any]:
        full = self.ledger.list_runs(limit=30, kind="full", status="completed")
        latest = self.ledger.list_runs(limit=1)
        docs = self.ledger.document_counts()
        trend = [{"at": r["finished_at"], "health_score": (r["stats"] or {}).get("health_score"),
                  "findings": (r["stats"] or {}).get("findings_total"), "documents": (r["stats"] or {}).get("documents_total")}
                 for r in reversed(full)]
        return {
            "mode": self.settings.mode, "demo": self.settings.is_demo, "documents": docs,
            "issues": self.ledger.issue_counts(), "latest_run": latest[0] if latest else None,
            "latest_full_run": full[0] if full else None, "trend": trend, "audit_running": self.audit_running,
            "query_log_size": self.ledger.query_count(),
            "target_fingerprint": (self.settings.target_fingerprint().to_dict() if self.settings.target_fingerprint() else None),
            "scheduler_interval_minutes": self.settings.audit_interval_minutes,
            "cleanup_policy": self.settings.cleanup_policy,
            "repair_webhook_configured": bool(self.settings.repair_webhook_url or self.settings.is_demo),
        }

    def connections(self) -> list[dict[str, Any]]:
        out: list[ConnectionStatus] = []
        ok, detail = self.ledger.ping()
        dialect = "supabase/postgres" if self.ledger.is_pg else "sqlite"
        out.append(ConnectionStatus("Issue ledger", "ledger", ok, detail, info={"engine": dialect}))
        try:
            c = self.connectors
            out += [c.source.health(), c.manifest.health(), c.index.health()]
        except Exception:
            # building all three failed (misconfiguration): construct them one by one to say *which* is wrong
            from .connectors.postgres import PostgresManifest
            from .connectors.qdrant import QdrantIndex
            from .connectors.s3 import S3Source

            for name, kind, key, factory in (("S3 source", "s3", "s3", S3Source), ("Manifest (Postgres)", "postgres", "manifest", PostgresManifest),
                                             ("Vector index (Qdrant)", "qdrant", "qdrant", QdrantIndex)):
                try:
                    if self._guard is not None:
                        self._guard(self.settings, key)  # app mode: refuse private/loopback targets before connecting
                    out.append(factory(self.settings).health())
                except Exception as exc:
                    out.append(ConnectionStatus(name, kind, False, f"{type(exc).__name__}: {str(exc)[:200]}"))
        return [asdict(s) for s in out]

    def inspect(self, tenant: str, document_id: str) -> dict[str, Any]:
        c = self.connectors
        try:
            return inspect_document(c.source, c.manifest, c.index, self.options(probe=False), tenant, document_id)
        except Exception as exc:
            up = as_upstream(exc)
            if up is not None:
                raise up from exc
            raise

    def recommendations(self, min_severity: str | None = None) -> dict[str, Any]:
        issues = self.ledger.open_issues(min_severity=min_severity)
        keys = sorted({(i["tenant_id"], i["document_id"]) for i in issues if i["document_id"] != "*"})
        docs = self.ledger.documents_for(keys)
        items = plan_items(issues, docs)
        est = estimate_workload(items, docs, list(self.ledger.all_documents()),
                                chunk_tokens=self.settings.chunk_size_tokens, price_per_mtok=self.settings.embedding_price_per_mtok)
        return {"summary": est, "items": items[:200], "items_truncated": len(items) > 200}

    def blast_radius(self, scenario: dict[str, Any]) -> dict[str, Any]:
        return blast_radius(self.ledger, scenario, chunk_tokens=self.settings.chunk_size_tokens,
                            price_per_mtok=self.settings.embedding_price_per_mtok)

    def report(self, fmt: str = "json", include_healthy: bool = False, tenant: str | None = None) -> Any:
        data = report.build_report(self.ledger, include_healthy=include_healthy, tenant=tenant)
        if fmt == "md":
            return report.to_markdown(data)
        if fmt == "csv":
            return report.to_csv(data)
        return data

    def ingest_queries(self, rows: list[dict[str, Any]]) -> int:
        """Store retrieval logs for query-impact analysis. Only document ids are kept; query text is hashed."""
        clean = []
        for r in rows[:5000]:
            tenant = str(r.get("tenant_id") or self.settings.default_tenant)
            ids = [str(d) for d in (r.get("retrieved_doc_ids") or [])][:100]
            if not ids:
                continue
            qh = r.get("query_hash") or (hashlib.sha256(str(r["query_text"]).encode()).hexdigest()[:16] if r.get("query_text") else None)
            ts = parse_ts(r.get("ts")) or datetime.now(timezone.utc)
            clean.append({"ts": ts, "tenant_id": tenant, "query_hash": qh, "retrieved_doc_ids": ids})
        return self.ledger.add_queries(clean)
