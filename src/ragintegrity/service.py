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

from . import alerts, notifications, plan_mail, report
from .config import Settings, get_settings
from .connectors.base import ConnectorError, UpstreamError
from .connectors.factory import Connectors, build_connectors
from .demo.world import DemoWorld
from .engine.audit import AuditOptions, PartialAudit, SliceResult, inspect_document, run_reconciliation
from .engine.blast import blast_radius
from .engine.isolation import OVERALL_TEXT
from .engine.planning import estimate_workload, plan_items
from .engine.reconcile import parse_ts
from .ledger import STALE_RUN_SECONDS, Ledger, RunDiff, RunInProgress, _parse_iso, utcnow
from .models import ConnectionStatus, DocSummary, Finding, IssueType, Scope
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
    status: str = "completed"  # completed | partial (the scan stopped part-way: see stats.scan)


_UNSET: Any = object()
WORKER_QUIET_SECONDS = 90  # a queued audit nobody has picked up for this long is reported as waiting for a worker


class _Heartbeat:
    """Tells the ledger every few seconds that the worker is alive, so a worker that dies is noticed and its audit taken back."""

    def __init__(self, ledger: Ledger, run_id: str, worker_id: str, every: float = 20.0) -> None:
        self.ledger, self.run_id, self.worker_id, self.every = ledger, run_id, worker_id, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{run_id[:8]}", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                self.ledger.touch_run(self.run_id, self.worker_id)
            except Exception:  # a missed beat is not worth stopping the audit for
                log.warning("heartbeat for audit %s failed", self.run_id, exc_info=True)

    def __enter__(self) -> _Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


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
        self._lock_test_mail = threading.Lock()
        self._test_mail_times: list[float] = []
        self.repairs = RepairManager(self)

    # ------------------------------------------------------------------ connectors
    @property
    def connectors(self) -> Connectors:
        if self._connectors is None:
            with self._build_lock:
                if self._connectors is None:
                    self._connectors = self._connector_factory(self.settings)
        return self._connectors

    def options(self, probe: bool | None = None, run_id: str | None = None, budget: Any = _UNSET) -> AuditOptions:
        """The audit's options. ``budget`` is the seconds the audit may take: left out it is the host's limit (270 s on
        serverless, none elsewhere), None means no limit."""
        s = self.settings
        limit = s.audit_seconds_limit if budget is _UNSET else (budget or 0)
        return AuditOptions(
            target=s.target_fingerprint(), default_tenant=s.default_tenant, required_fields=s.required_fields,
            known_tenants=self.ledger.known_tenants(), grace_minutes=s.grace_minutes,
            check_vectors=s.qdrant_check_vectors or s.pgvector_check_vectors or s.is_demo, source_only=s.source_documents_only,
            lookup_from_manifest=s.s3_lookup_from_manifest, names=self.id_names(), slice_size=max(1, s.audit_slice_documents),
            probe=s.probe_retrieval if probe is None else probe, probe_max=s.probe_max, probe_top_k=s.probe_top_k,
            deadline=(time.monotonic() + limit) if limit else None,
            progress=(lambda phase, **info: self.ledger.set_progress(run_id, phase, **info)) if run_id else None,
        )

    def id_names(self) -> dict[str, str]:
        """The setting names a message about identifiers can quote (the payload field, the manifest column, the key pattern)."""
        from .connectors.payload import build_payload_map
        from .connectors.pgvector import build_column_map

        s = self.settings
        names = {"payload_document_id": "document_id", "manifest_document_id": "document_id", "key_pattern": s.s3_key_pattern}
        try:  # a setting that cannot be read is reported by the connector that needs it, not by a message about names
            index_map = build_column_map(s.pgvector_columns) if s.uses_pgvector else build_payload_map(s.payload_map)
            names["payload_document_id"] = index_map["document_id"]
            names["manifest_document_id"] = s.manifest_columns.get("document_id", "document_id")
        except (ValueError, ConnectorError):
            pass
        return names

    def _stale_after(self) -> int:
        """How old a 'running' audit may get before it is presumed dead: the time budget plus a margin, else 15 minutes."""
        limit = self.settings.audit_seconds_limit
        return limit + 90 if limit else STALE_RUN_SECONDS

    # ------------------------------------------------------------------ audits
    def _resume_info(self, exclude: str | None = None) -> dict[str, Any] | None:
        """What a resumed audit continues: the interrupted full audit's last checkpoint and the counts it had reported."""
        run = self.ledger.latest_resumable_run(exclude=exclude)
        if run is None:
            return None
        stats = run.get("stats") or {}
        return {"run_id": run["id"], "after": tuple(stats["scan"]["checkpoint"]),
                "carry": {k: stats.get(k) or {} for k in ("documents_by_status", "findings_by_type", "findings_by_severity")}}

    def _execute(self, run_id: str, kind: str, trigger: str, scope: Scope | None, probe: bool | None,
                 resume: dict[str, Any] | None = None, budget: Any = _UNSET) -> AuditResult:
        t0 = time.perf_counter()
        diff = RunDiff()
        seen: set[tuple[str, str]] = set()
        sticky: dict[str, Any] = {}  # the last checkpoint: kept in every progress note, so a run that is killed can still be resumed
        try:
            c = self.connectors
            opts = self.options(probe, run_id, budget)
            sliced = opts.source_only and (scope is None or scope.keys is None)
            if sliced and (scope is None or scope.is_full):
                opts.prior_source_keys = self.ledger.source_present_keys()  # a document that vanished from the source is checked
            if resume is not None:
                opts.resume_after, opts.carry, opts.resumed_from = resume["after"], resume["carry"], resume["run_id"]
            if opts.progress is not None:
                opts.progress = lambda phase, **info: self.ledger.set_progress(run_id, phase, **{**sticky, **info})

            def on_slice(sl: SliceResult) -> None:
                """A slice of the scan is complete: record it now, so a later stop cannot lose it."""
                part = self.ledger.apply_run(run_id, sl.findings, sl.summaries, sl.scope)
                diff.opened += part.opened
                diff.reopened += part.reopened
                diff.escalated += part.escalated
                diff.resolved += part.resolved
                diff.unchanged += part.unchanged
                if not sl.final and sl.scope.keys:
                    seen.update(sl.scope.keys)
                pct = round(100.0 * sl.documents_done / sl.documents_total, 1) if sl.documents_total else 100.0
                sticky.update(checkpoint=list(sl.last_key) if sl.last_key else None, carry=sl.carry, documents_done=sl.documents_done,
                              documents_total=sl.documents_total, slices_done=sl.index if not sl.final else sl.total, slices_total=sl.total,
                              percent=pct, points_scanned=sl.points_scanned, resumed_from=resume["run_id"] if resume else None)
                self.ledger.set_progress(run_id, "recorded a slice of the audit", **sticky)

            opts.on_slice = on_slice if sliced else None
            result = run_reconciliation(c.source, c.manifest, c.index, opts, scope)
            if (result.stats.get("scan") or {}).get("mode") == "sliced":
                diff.resolved += self.ledger.sweep_missing(run_id, seen, after=opts.resume_after).resolved
            else:
                diff = self.ledger.apply_run(run_id, result.findings, result.summaries, scope)
            stats = {**result.stats, "diff": diff.to_json(), "scope": scope.to_json() if scope else {},
                     "duration_seconds": round(time.perf_counter() - t0, 3)}
            if resume is not None:
                stats["resume"] = {"requested": True, "resumed_from": resume["run_id"]}
            alert = alerts.notify(self.settings, run_id, diff, stats)
            stats["alerts"] = alert
            stats["notifications"] = self._announce(run_id, kind, trigger, "completed", stats, diff)
            self.ledger.finish_run(run_id, "completed", stats)
            return AuditResult(run_id, kind, stats, diff, result.findings, result.summaries, alert)
        except PartialAudit as pa:
            # the scan stopped part-way: the slices before it are recorded and final, nothing is claimed about the rest
            stats = {**pa.result.stats, "diff": diff.to_json(), "scope": {}, "duration_seconds": round(time.perf_counter() - t0, 3)}
            if resume is not None:
                stats["resume"] = {"requested": True, "resumed_from": resume["run_id"]}
            stats["alerts"] = alerts.notify(self.settings, run_id, diff, stats)
            stats["notifications"] = self._announce(run_id, kind, trigger, "partial", stats, diff)
            self.ledger.finish_run(run_id, "partial", stats,
                                   error=f"{scrub(pa.reason, 300)}. The audit checked {pa.scan.get('documents_done')} of "
                                         f"{pa.scan.get('documents_total')} documents; what it checked is reported, the rest is not. "
                                         "Resume the audit to continue.")
            return AuditResult(run_id, kind, stats, diff, pa.result.findings, pa.result.summaries, stats["alerts"], status="partial")
        except Exception as exc:
            up = as_upstream(exc)
            failed_stats: dict[str, Any] = {"duration_seconds": round(time.perf_counter() - t0, 3)}
            snap = getattr(exc, "scan_snapshot", None)
            if isinstance(snap, dict):
                failed_stats["scan"] = snap
            reason = str(up) if up else f"{type(exc).__name__}: {scrub(str(exc), 500)}"
            failed_stats["notifications"] = self._announce(run_id, kind, trigger, "failed", failed_stats, diff, error=reason)
            self.ledger.finish_run(run_id, "failed", failed_stats, error=reason)
            if up is not None:
                raise up from exc
            raise

    def send_test_email(self) -> dict[str, Any]:
        """The Send test email button: one message to the people an alert would go to. Limited per process; the API adds a per-workspace limit."""
        now = time.monotonic()
        with self._lock_test_mail:
            self._test_mail_times = [t for t in self._test_mail_times if now - t < notifications.TEST_WINDOW_SECONDS]
            if len(self._test_mail_times) >= notifications.TEST_EMAILS:
                return {"ok": False, "sent": 0, "to": [], "rate_limited": True,
                        "reason": f"Too many test emails: at most {notifications.TEST_EMAILS} every 10 minutes. Try again in a few minutes."}
            self._test_mail_times.append(now)
        return notifications.send_test_email(self.settings, self.ledger)

    def _announce(self, run_id: str, kind: str, trigger: str, status: str, stats: dict[str, Any], diff: RunDiff,
                  error: str | None = None) -> dict[str, Any]:
        """The notification in the app and the email for a finished audit. It reports what it did and can never fail the audit."""
        try:
            return notifications.announce(self.settings, self.ledger, run_id=run_id, kind=kind, trigger=trigger, status=status,
                                          stats=stats, diff=diff, error=error)
        except Exception as exc:  # announce already catches everything; this is the last line of defence
            log.warning("notifications failed for %s: %s", run_id, type(exc).__name__)
            return {"error": f"{type(exc).__name__}: notifications failed"}

    @staticmethod
    def _kind(scope: Scope | None, kind: str | None) -> str:
        return kind or ("full" if scope is None or scope.is_full else "scoped")

    def run_audit(self, scope: Scope | None = None, trigger: str = "manual", kind: str | None = None,
                  probe: bool | None = None, resume: bool = False) -> AuditResult:
        if not self._lock.acquire(blocking=False):
            raise AuditBusy("An audit is already running.")
        try:
            kind = self._kind(scope, kind)
            _ = self.connectors  # a misconfigured or incomplete setup fails here, before a run row is created
            self._refuse_while_queued(scope)
            info = self._resume_info() if (resume and scope is None) else None  # (before the run row: it must not hide the checkpoint)
            try:
                run_id = self.ledger.start_run(kind, trigger, scope, stale_after=self._stale_after())
            except RunInProgress as exc:
                raise AuditBusy(str(exc)) from exc
            return self._execute(run_id, kind, trigger, scope, probe, info)
        finally:
            self._lock.release()

    def start_audit_async(self, scope: Scope | None = None, trigger: str = "manual", probe: bool | None = None,
                          resume: bool = False) -> str:
        if self.settings.run_audits_inline:  # serverless: a background thread would be frozen with the instance
            return self.run_audit(scope=scope, trigger=trigger, probe=probe, resume=resume).run_id
        if not self._lock.acquire(blocking=False):
            raise AuditBusy("An audit is already running.")
        try:
            kind = self._kind(scope, None)
            _ = self.connectors  # fail early (and without a run row) when setup is incomplete
            self._refuse_while_queued(scope)
            info = self._resume_info() if (resume and scope is None) else None
            run_id = self.ledger.start_run(kind, trigger, scope, stale_after=self._stale_after())
        except RunInProgress as exc:
            self._lock.release()
            raise AuditBusy(str(exc)) from exc
        except Exception:
            self._lock.release()
            raise

        def work() -> None:
            try:
                self._execute(run_id, kind, trigger, scope, probe, info)
            except Exception:
                log.exception("audit %s failed", run_id)
            finally:
                self._lock.release()

        threading.Thread(target=work, name=f"audit-{run_id[:8]}", daemon=True).start()
        return run_id

    @property
    def audit_running(self) -> bool:
        """An audit is running, or queued (waiting for a worker to start it or to carry it on)."""
        if self._lock.locked():
            return True
        active = self.ledger.active_runs()  # another process may be running one
        if active and self.ledger.retire_stale_runs(self._stale_after()):
            # a run whose process was killed never records a result; without this the button would stay disabled forever
            active = self.ledger.active_runs()
        return bool(active)

    # ------------------------------------------------------------------ the queue and the worker
    def _refuse_while_queued(self, scope: Scope | None) -> None:
        """A second whole-corpus audit cannot start while one waits in the queue (it would do the same work twice).
        An audit of named documents, such as the check that follows a repair, is small and goes ahead."""
        if (scope is None or scope.keys is None) and any(r["status"] == "queued" for r in self.ledger.active_runs()):
            raise AuditBusy("An audit is already waiting for a worker to carry it out.")

    def enqueue_audit(self, trigger: str = "api", probe: bool | None = None, resume: bool = False) -> str:
        """Queue a whole-corpus audit for a worker instead of running it here (``RAGI_AUDIT_QUEUE``). A worker (``ragi worker``) or
        a call to ``POST /api/worker/step`` carries it out, and carries on after every pause until it is done."""
        _ = self.connectors  # a misconfigured or incomplete setup fails now, not an hour later in a worker
        self.ledger.retire_stale_runs(self._stale_after())
        if self.ledger.active_runs():
            raise AuditBusy("An audit is already running, or waiting for a worker.")
        return self.ledger.queue_run("full", trigger, None, {"probe": probe, "resume": resume, "auto": True})

    def work(self, worker_id: str, budget: float | None = None, run: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Take the oldest queued audit of this workspace and work on it for up to ``budget`` seconds (None: until it is done).

        What it does is the ordinary audit (sliced, with checkpoints, ``partial`` when it stops part-way). If it stops part-way
        the next stretch is queued, and resumes from the last checkpoint. Returns what happened (``completed``, ``partial`` or
        ``failed``), or None when nothing was waiting. ``run`` is an audit the caller has already claimed."""
        self.ledger.retire_stale_runs(self._stale_after())  # a dead worker's audit goes back in the queue
        claimed = run or self.ledger.claim_run(worker_id)
        if claimed is None:
            return None
        run_id = claimed["id"]
        meta = self.ledger.get_run(run_id) or {}
        asked = self.ledger.get_run_options(run_id)
        kind, trigger, probe = meta.get("kind", "full"), meta.get("trigger", "worker"), asked.get("probe")
        status = "failed"
        try:
            info = self._resume_info(exclude=run_id) if asked.get("resume") else None
            with _Heartbeat(self.ledger, run_id, worker_id):
                status = self._execute(run_id, kind, trigger, None, probe, info, budget=budget).status
        except Exception as exc:  # _execute has recorded the failure on the run; the worker reports it and goes on
            log.warning("audit %s failed in worker %s: %s", run_id, worker_id, exc)
        finished = self.ledger.get_run(run_id) or {}
        scan = (finished.get("stats") or {}).get("scan") or {}
        out: dict[str, Any] = {"run_id": run_id, "status": status, "documents_done": scan.get("documents_done"),
                               "documents_total": scan.get("documents_total"), "percent": scan.get("percent")}
        if status == "partial" and asked.get("auto"):
            # Stopped part-way (time ran out, or the index could not be reached): queue the next stretch. One that moved the
            # checkpoint on is fine; MAX_STALLS in a row that did not are left partial for a person.
            earlier = ((self.ledger.get_run(asked["continues"]) or {}).get("stats") or {}) if asked.get("continues") else {}
            before = (earlier.get("scan") or {}).get("checkpoint")
            progressed = bool(scan.get("checkpoint")) and scan.get("checkpoint") != before
            out["next"] = self.ledger.queue_continuation(run_id, asked, progressed=progressed)
        if status == "failed":
            out["error"] = finished.get("error")
        return out

    def audit_progress(self) -> dict[str, Any] | None:
        """Where the audit in progress (running, or waiting in the queue) stands, in words people can act on."""
        active = self.ledger.active_runs()
        if not active:
            return None
        run = self.ledger.get_run(active[0]["id"]) or {}
        stats = run.get("stats") or {}
        worker = stats.get("worker") or {}
        now = utcnow()

        def ago(value: Any) -> int | None:
            t = _parse_iso(value)
            return int((now - t).total_seconds()) if t else None

        # a running audit reports its own progress; a queued continuation shows where the audit it continues had got to
        source = stats.get("progress") or {}
        if run.get("status") == "queued":
            earlier = self.ledger.get_run_options(run["id"]).get("continues")  # (the public run hides the request's details)
            scan = ((self.ledger.get_run(earlier) or {}).get("stats") or {}).get("scan") if earlier else None
            source = scan or {}
        done, total, pct = source.get("documents_done"), source.get("documents_total"), source.get("percent")
        counts = f"{done:,} of {total:,} documents ({pct}%)" if isinstance(done, int) and isinstance(total, int) and total else ""
        if run.get("status") == "running":
            quiet = ago(worker.get("heartbeat_at"))
            if quiet is not None and quiet > WORKER_QUIET_SECONDS:
                state = "silent"
                msg = (f"The worker has not reported for {quiet} seconds. If it does not come back, the audit is taken over "
                       "and carries on from its last checkpoint.")
            else:
                state, msg = "working", ("Checking " + counts) if counts else (source.get("phase") or "The audit is running.")
        else:
            waited = ago(stats.get("queued_at")) or 0
            if waited > WORKER_QUIET_SECONDS:
                state = "waiting_for_worker"
                msg = (f"Waiting for a worker for {waited // 60} min. Nothing is running this audit: start one with `ragi worker`, or "
                       "call POST /api/worker/step (for example from a scheduled job). "
                       + (f"{counts} are already checked and it carries on from there." if counts else ""))
            else:
                state = "queued"
                msg = ("Paused at a checkpoint: " + counts + ". Waiting for the next step.") if counts else "Waiting for a worker to pick it up."
        return {"run_id": run.get("id"), "status": run.get("status"), "state": state, "message": msg.strip(),
                "done_documents": done, "total_documents": total, "percent": pct,
                "last_worker": worker.get("id") or None}

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
            "audit_progress": self.audit_progress(), "audit_queue": self.settings.audit_queue,
            "query_log_size": self.ledger.query_count(),
            "target_fingerprint": (self.settings.target_fingerprint().to_dict() if self.settings.target_fingerprint() else None),
            "scheduler_interval_minutes": self.settings.audit_interval_minutes,
            "cleanup_policy": self.settings.cleanup_policy,
            "repair_webhook_configured": bool(self.settings.repair_webhook_url or self.settings.is_demo),
            "resumable_audit": self._resumable_summary(),
            # the manifest is optional: the screens say "not connected" instead of calling its absence a fault
            "manifest_connected": bool(self.settings.manifest_database_url) or self.settings.is_demo,
            "index_type": "pgvector" if self.settings.uses_pgvector else "qdrant",
            "email_configured": plan_mail.is_configured(self.settings, deployment_account=self._guard is None),
        }

    def _resumable_summary(self) -> dict[str, Any] | None:
        run = self.ledger.latest_resumable_run()
        if run is None:
            return None
        scan = (run.get("stats") or {}).get("scan") or {}
        return {"run_id": run["id"], "finished_at": run.get("finished_at"), "documents_done": scan.get("documents_done"),
                "documents_total": scan.get("documents_total"), "percent": scan.get("percent"),
                "stopped_because": scan.get("stopped_because")}

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
            from .connectors.nomanifest import NoManifest
            from .connectors.pgvector import PgVectorIndex
            from .connectors.postgres import PostgresManifest
            from .connectors.qdrant import QdrantIndex
            from .connectors.s3 import S3Source

            index = (("Vector index (pgvector)", "pgvector", "pgvector", PgVectorIndex) if self.settings.uses_pgvector
                     else ("Vector index (Qdrant)", "qdrant", "qdrant", QdrantIndex))
            manifest = (("Manifest (Postgres)", "postgres", "manifest", PostgresManifest) if self.settings.manifest_database_url
                        else ("Processing manifest", "manifest", "manifest", lambda _s: NoManifest()))
            for name, kind, key, factory in (("S3 source", "s3", "s3", S3Source), manifest, index):
                try:
                    if self._guard is not None:
                        self._guard(self.settings, key)  # app mode: refuse private/loopback targets before connecting
                    out.append(factory(self.settings).health())
                except Exception as exc:
                    out.append(ConnectionStatus(name, kind, False, friendly_error(exc) if as_upstream(exc) else f"{type(exc).__name__}: {str(exc)[:200]}"))
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

    def setup_check(self) -> dict[str, Any]:
        """Do S3, the manifest and Qdrant line up on document IDs? A quick, read-only look (no audit is stored or started).

        Runs within a short time budget of its own, reads a bounded part of each system, and reports what it could not
        look at as part of the result instead of failing."""
        from .engine.coverage import build_setup_report, collect_setup_facts

        t0 = time.monotonic()
        limit = self.settings.audit_seconds_limit
        budget = min(limit, 120) if limit else 120
        try:
            c = self.connectors
        except (ConnectorError, ValueError) as exc:  # a connection that is not set up (or refused) is a result of this check, not a server fault
            return {"status": "not_ready", "checks": [{"id": "connections", "name": "Connections", "status": "fail", "detail": scrub(str(exc), 300),
                                                       "fix": "Finish connecting S3, the manifest and Qdrant on the Data Sources page, then run this check again."}],
                    "headline": "Not ready yet: a connection is missing. Finish connecting S3, the manifest and Qdrant on the Data Sources page.",
                    "coverage": {}, "counts": {}, "limits": [], "next_steps": ["Finish connecting S3, the manifest and Qdrant on the Data Sources page."],
                    "ids_at_a_glance": {}, "id_types_in_index": {}, "duration_seconds": 0.0}
        s = self.settings
        facts = collect_setup_facts(c.source, c.manifest, c.index, time.monotonic() + budget, default_tenant=s.default_tenant,
                                    names=self.id_names(), source_only=s.source_documents_only, lookup_mode=s.s3_lookup_from_manifest,
                                    explain=friendly_error)
        return build_setup_report(facts, time.monotonic() - t0)

    def verify_deletions(self, documents: list[tuple[str, str]] | None = None, record: bool = True,
                         max_documents: int = 200) -> dict[str, Any]:
        """Deletion and retrieval verification: for documents deleted from the source, are their vectors really gone, and can
        a search still return them? Read-only towards S3, the manifest and the index. With ``record`` the findings are written
        to the issue list (our own store) as a scoped run, which also closes issues whose vectors have since been cleaned up."""
        from .engine.deletions import verify_deletions
        from .engine.reconcile import DELETED_STATUSES, _norm

        c = self.connectors
        candidates: dict[tuple[str, str], str] = {}
        prior = self.ledger.source_present_keys()
        if prior:  # in the source at an earlier audit: which of them are gone now? (names only: no hashing, no downloads)
            if hasattr(c.source, "iter_keys"):
                present = {parsed for _key, parsed in c.source.iter_keys() if parsed}
            else:
                present = {d.key for d in c.source.inventory(None)}
            for k in sorted(prior - present):
                candidates[k] = "it was in the source at the last audit and is gone now"
        for r in c.manifest.documents(None):
            if _norm(r.processing_status) in DELETED_STATUSES:
                candidates.setdefault(r.key, "the manifest marks it deleted")
        for typ in (IssueType.ORPHAN_VECTOR.value, IssueType.TENANT_MISMATCH.value):
            rows, _ = self.ledger.list_issues(status="open", type=typ, limit=500)
            for i in rows:
                if i["document_id"] != "*":
                    candidates.setdefault((i["tenant_id"], i["document_id"]), "an open issue says vectors remain for it")
        for k in documents or []:
            candidates[(k[0], k[1])] = "you asked for it"
        truncated = max(0, len(candidates) - max_documents)
        if truncated:
            candidates = dict(sorted(candidates.items())[:max_documents])
        if not candidates:
            return {"generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "summary": {"documents_checked": 0, "verified_deleted": 0, "deletion_mismatch": 0, "manifest_not_updated": 0,
                                "not_deleted": 0, "vectors_remaining": 0, "retrievable": 0},
                    "documents": [], "truncated": 0, "recorded": None,
                    "limits": [], "note": "Nothing to verify: no document has been deleted from the source since the last audit, "
                                          "the manifest marks none as deleted, and no open issue says vectors remain for a deleted one."}
        try:
            report, result, scope = verify_deletions(c.source, c.manifest, c.index, self.options(probe=False), candidates)
        except Exception as exc:
            up = as_upstream(exc)
            if up is not None:
                raise up from exc
            raise
        report["truncated"] = truncated
        report["recorded"] = None
        if record:
            if not self._lock.acquire(blocking=False):
                raise AuditBusy("An audit is already running; try again when it has finished, or run the check without recording.")
            try:
                try:
                    run_id = self.ledger.start_run("scoped", "deletion-check", scope, stale_after=self._stale_after())
                except RunInProgress as exc:
                    raise AuditBusy(str(exc)) from exc
                try:
                    diff = self.ledger.apply_run(run_id, result.findings, result.summaries, scope)
                    self.ledger.finish_run(run_id, "completed", {**result.stats, "deletion_check": report["summary"],
                                                                 "diff": diff.to_json(), "scope": scope.to_json()})
                except Exception as exc:
                    self.ledger.finish_run(run_id, "failed", {}, error=f"{type(exc).__name__}: {scrub(str(exc), 300)}")
                    raise
                report["recorded"] = {"run_id": run_id, **diff.to_json()}
            finally:
                self._lock.release()
        return report

    def isolation(self) -> dict[str, Any]:
        """Tenant isolation as of the latest full audit, with the open findings behind it."""
        full = self.ledger.list_runs(limit=1, kind="full", status="completed")
        summary = ((full[0].get("stats") or {}).get("isolation") if full else None)
        if not summary:
            return {"available": False, "note": "Run a full audit first: the isolation picture is built from it."}
        leaks, leak_total = self.ledger.list_issues(status="open", type="tenant_mismatch", limit=100)
        meta, _ = self.ledger.list_issues(status="open", type="metadata_inconsistent", limit=500)
        acl = [i for i in meta if any(p.get("code") == "acl_mismatch" for p in ((i.get("evidence") or {}).get("problems") or []))]
        findings = [{"issue_id": i["id"], "type": i["type"], "severity": i["severity"], "tenant_id": i["tenant_id"],
                     "document_id": i["document_id"], "title": i["title"], "status": i["status"]} for i in [*leaks, *acl[:100]]]
        # the sentence is wording, not data: always the current wording (an audit stored earlier may hold older text)
        overall = {**summary["overall"], "summary": OVERALL_TEXT.get(summary["overall"]["status"], summary["overall"].get("summary", ""))}
        summary = {**summary, "overall": overall}
        # the banner and cards describe the last full audit; the findings are the issue list as it is now (a scoped re-audit,
        # an ignore or a repair can change it), so say when the two no longer agree
        changed = leak_total != overall["leaking_documents"] or len(acl) != overall["permission_mismatch_documents"]
        return {"available": True,
                "audit": {"run_id": full[0]["id"], "finished_at": full[0].get("finished_at"), "kind": "full"},
                **summary, "findings": findings, "findings_total": leak_total + len(acl),
                "findings_live": True, "findings_changed_since_audit": changed}

    def isolation_report(self, fmt: str = "json") -> Any:
        from .engine import isolation as iso

        data = self.isolation()
        return iso.to_markdown(data) if fmt == "md" else data

    def isolation_drill(self, tenant: str | None = None, document_id: str | None = None) -> dict[str, Any]:
        """Show the audit catching a pretend leak on one real document. Read-only: nothing is stored, written or sent."""
        from .engine.drills import drill_tenant_mismatch

        if (tenant is None) != (document_id is None):
            raise ValueError("Give both tenant and document_id, or neither to let RAGGuard pick a document.")
        if document_id is None:
            rows, _ = self.ledger.list_documents(status="healthy", limit=50)
            pick = next((r for r in rows if r.get("index_present") and (r.get("indexed_chunks") or 0) > 0), None)
            if pick is None:
                raise ValueError("There is no healthy, indexed document to use yet. Run a full audit first.")
            tenant, document_id = pick["tenant_id"], pick["document_id"]
        elif self.ledger.get_document(tenant, document_id) is None:
            raise ValueError("That document has not been audited yet. Run a full audit first, or leave both fields empty.")
        c = self.connectors
        full = self.ledger.list_runs(limit=1, kind="full", status="completed")
        health = ((full[0].get("stats") or {}).get("health_score") if full else None)

        def preview(finding: Finding) -> dict[str, Any]:
            """The alert exactly as a real audit would build it (the same function), never sent."""
            msg = alerts.build_message(self.settings, "drill", RunDiff(opened=[finding]), {"health_score": 100.0 if health is None else health})
            return {"severity": finding.severity.value, "sent": False,
                    "text": msg["text"] if msg else f"{finding.title} ({finding.tenant_id}/{finding.document_id})",
                    "note": "This is the message an audit posts to your alert webhook for a new issue. The drill never sends it."}

        try:
            return drill_tenant_mismatch(c.source, c.manifest, c.index, self.options(probe=False), (tenant, document_id), preview)
        except Exception as exc:
            up = as_upstream(exc)
            if up is not None:
                raise up from exc
            raise

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
