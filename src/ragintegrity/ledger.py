"""Issue ledger / control-plane store.

One schema, two homes: SQLite for local use and Postgres (Supabase) in production. In Postgres the
tables live in a dedicated ``ragi`` schema, which Supabase's REST API does not expose by default.
No document contents are ever stored - only ids, hashes, versions, counts and evidence about them.

Multi-tenancy: every ledger table carries a ``workspace_id`` and a ``Ledger`` instance is bound to exactly one
workspace. There is deliberately no way to run an unscoped query through it: each statement is built with the
workspace condition, so one workspace can never read or modify another's issues, documents, runs or plans.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    bindparam,
    case,
    delete,
    func,
    insert,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from .config import normalize_db_url
from .connectors.postgres import make_engine
from .models import SEVERITY_RANK, DocSummary, Finding, Scope, severity_at_least

PG_SCHEMA = "ragi"
CHUNK = 400
DEFAULT_WORKSPACE = "default"  # the single implicit workspace of the non-app modes
STALE_RUN_SECONDS = 15 * 60  # a run "running" longer than this was abandoned (e.g. a killed serverless function)


class RunInProgress(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime | None) -> str | None:
    dt = aware(dt)
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def build_tables(schema: str | None) -> tuple[MetaData, dict[str, Table]]:
    md = MetaData(schema=schema)
    J = JSON().with_variant(JSONB(), "postgresql")
    ts = lambda: DateTime(timezone=True)  # noqa: E731
    t: dict[str, Table] = {}

    # ---------------------------------------------------------------- accounts
    t["workspaces"] = Table(
        "workspaces", md,
        Column("id", String(36), primary_key=True),
        Column("name", Text, nullable=False),
        Column("owner_id", String(36), nullable=False),
        Column("created_at", ts(), nullable=False),
    )
    t["users"] = Table(
        "users", md,
        Column("id", String(36), primary_key=True),
        Column("email", Text, nullable=False, unique=True),
        Column("password_hash", Text, nullable=False),
        Column("workspace_id", String(36), nullable=False),
        Column("created_at", ts(), nullable=False),
        Column("last_login_at", ts()),
    )
    t["sessions"] = Table(
        "sessions", md,
        Column("token_hash", String(64), primary_key=True),
        Column("user_id", String(36), nullable=False),
        Column("workspace_id", String(36), nullable=False),
        Column("created_at", ts(), nullable=False),
        Column("expires_at", ts(), nullable=False),
        Column("last_used_at", ts(), nullable=False),
        Column("ip", Text),
        Column("user_agent", Text),
    )
    Index("ix_sessions_user", t["sessions"].c.user_id)
    Index("ix_sessions_expires", t["sessions"].c.expires_at)
    t["workspace_settings"] = Table(
        "workspace_settings", md,
        Column("workspace_id", String(36), primary_key=True),
        Column("kind", String(32), primary_key=True),
        Column("config", J, nullable=False),  # non-secret values
        Column("secrets", Text),  # Fernet token (encrypted JSON) of the secret values
        Column("updated_at", ts(), nullable=False),
        Column("last_test", J),
    )
    t["api_keys"] = Table(
        "api_keys", md,
        Column("id", String(36), primary_key=True),
        Column("workspace_id", String(36), nullable=False),
        Column("name", Text, nullable=False),
        Column("token_hash", String(64), nullable=False, unique=True),
        Column("prefix", String(16), nullable=False),
        Column("created_at", ts(), nullable=False),
        Column("last_used_at", ts()),
        Column("revoked_at", ts()),
    )
    Index("ix_api_keys_workspace", t["api_keys"].c.workspace_id)
    t["rate_limits"] = Table(
        "rate_limits", md,
        Column("key", Text, primary_key=True),
        Column("window_start", ts(), nullable=False),
        Column("count", Integer, nullable=False),
    )

    # ---------------------------------------------------------------- the ledger proper (all workspace-scoped)
    t["audit_runs"] = Table(
        "audit_runs", md,
        Column("id", String(36), primary_key=True),
        Column("workspace_id", String(36), nullable=False),
        Column("kind", String(16), nullable=False),  # full | scoped | verify
        Column("trigger", String(32), nullable=False),  # manual | api | cli | schedule | repair-verify | ...
        Column("scope", J, nullable=False),
        Column("status", String(16), nullable=False),  # running | completed | failed
        Column("started_at", ts(), nullable=False),
        Column("finished_at", ts()),
        Column("stats", J, nullable=False),
        Column("error", Text),
    )
    Index("ix_audit_runs_ws_started", t["audit_runs"].c.workspace_id, t["audit_runs"].c.started_at)
    # at most one running audit per workspace, enforced by the database (works across serverless instances)
    Index("ux_audit_runs_one_running", t["audit_runs"].c.workspace_id, unique=True,
          sqlite_where=text("status = 'running'"), postgresql_where=text("status = 'running'"))
    t["issues"] = Table(
        "issues", md,
        Column("workspace_id", String(36), primary_key=True),
        Column("id", String(32), primary_key=True),
        Column("type", String(32), nullable=False),
        Column("severity", String(16), nullable=False),
        Column("status", String(16), nullable=False),  # open | resolved | ignored
        Column("tenant_id", Text, nullable=False),
        Column("document_id", Text, nullable=False),
        Column("collection", Text),
        Column("title", Text, nullable=False),
        Column("detail", Text, nullable=False),
        Column("evidence", J, nullable=False),
        Column("action", String(32), nullable=False),
        Column("first_seen_at", ts(), nullable=False),
        Column("last_seen_at", ts(), nullable=False),
        Column("first_run_id", String(36), nullable=False),
        Column("last_run_id", String(36), nullable=False),
        Column("resolved_at", ts()),
        Column("resolved_run_id", String(36)),
        Column("occurrences", Integer, nullable=False),
        Column("reopened_count", Integer, nullable=False),
        Column("ignored_reason", Text),
    )
    Index("ix_issues_status_sev", t["issues"].c.workspace_id, t["issues"].c.status, t["issues"].c.severity)
    Index("ix_issues_doc", t["issues"].c.workspace_id, t["issues"].c.tenant_id, t["issues"].c.document_id)
    t["issue_events"] = Table(
        "issue_events", md,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("workspace_id", String(36), nullable=False),
        Column("issue_id", String(32), nullable=False),
        Column("run_id", String(36)),
        Column("ts", ts(), nullable=False),
        Column("event", String(32), nullable=False),  # opened | reopened | resolved | severity_changed | ignored | unignored
        Column("details", J, nullable=False),
    )
    Index("ix_issue_events_issue", t["issue_events"].c.workspace_id, t["issue_events"].c.issue_id)
    Index("ix_issue_events_ts", t["issue_events"].c.workspace_id, t["issue_events"].c.ts)
    t["documents"] = Table(
        "documents", md,
        Column("workspace_id", String(36), primary_key=True),
        Column("tenant_id", Text, primary_key=True),
        Column("document_id", Text, primary_key=True),
        Column("status", String(16), nullable=False),
        Column("issue_count", Integer, nullable=False),
        Column("worst_severity", String(16)),
        Column("issue_types", J, nullable=False),
        Column("fingerprint", J, nullable=False),
        Column("source_uri", Text),
        Column("source_hash", Text),
        Column("source_version", Text),
        Column("size_bytes", Integer, nullable=False),
        Column("expected_chunks", Integer),
        Column("indexed_chunks", Integer, nullable=False),
        Column("manifest_status", Text),
        Column("manifest_updated_at", Text),
        Column("collections", J, nullable=False),
        Column("source_present", Integer, nullable=False),
        Column("manifest_present", Integer, nullable=False),
        Column("index_present", Integer, nullable=False),
        Column("last_verified_at", ts(), nullable=False),
        Column("last_run_id", String(36), nullable=False),
        Column("indexed_version", Text),  # added by migration 20261109000000 (appended: ALTER TABLE ... ADD COLUMN)
    )
    Index("ix_documents_status", t["documents"].c.workspace_id, t["documents"].c.status)
    t["repair_plans"] = Table(
        "repair_plans", md,
        Column("id", String(36), primary_key=True),
        Column("workspace_id", String(36), nullable=False),
        Column("status", String(24), nullable=False),
        Column("created_at", ts(), nullable=False),
        Column("updated_at", ts(), nullable=False),
        Column("items", J, nullable=False),
        Column("summary", J, nullable=False),
    )
    Index("ix_repair_plans_ws", t["repair_plans"].c.workspace_id, t["repair_plans"].c.created_at)
    t["repair_events"] = Table(
        "repair_events", md,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("workspace_id", String(36), nullable=False),
        Column("plan_id", String(36), nullable=False),
        Column("ts", ts(), nullable=False),
        Column("event", String(32), nullable=False),
        Column("details", J, nullable=False),
    )
    Index("ix_repair_events_plan", t["repair_events"].c.workspace_id, t["repair_events"].c.plan_id)
    t["query_log"] = Table(
        "query_log", md,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("workspace_id", String(36), nullable=False),
        Column("ts", ts(), nullable=False),
        Column("tenant_id", Text, nullable=False),
        Column("query_hash", String(64)),
        Column("retrieved_doc_ids", J, nullable=False),
    )
    Index("ix_query_log_ts", t["query_log"].c.workspace_id, t["query_log"].c.ts)
    return md, t


@dataclass
class RunDiff:
    opened: list[Finding] = field(default_factory=list)
    reopened: list[Finding] = field(default_factory=list)
    escalated: list[Finding] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    unchanged: int = 0

    def to_json(self) -> dict[str, int]:
        return {"opened": len(self.opened), "reopened": len(self.reopened), "escalated": len(self.escalated),
                "resolved": len(self.resolved), "unchanged": self.unchanged}


def _chunks(seq: list, n: int = CHUNK) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _public(row: Any) -> dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = iso(v)
    return out


class Ledger:
    def __init__(self, url: str, engine: Engine | None = None, workspace_id: str = DEFAULT_WORKSPACE) -> None:
        self.url = normalize_db_url(url)
        self.engine = engine or make_engine(self.url)
        self.is_pg = self.engine.dialect.name == "postgresql"
        self.md, self.t = build_tables(PG_SCHEMA if self.is_pg else None)
        self.ws = workspace_id

    def for_workspace(self, workspace_id: str) -> Ledger:
        """A ledger bound to another workspace, sharing the engine (cheap: no new connections)."""
        other = Ledger.__new__(Ledger)
        other.url, other.engine, other.is_pg, other.md, other.t, other.ws = self.url, self.engine, self.is_pg, self.md, self.t, workspace_id
        return other

    # ------------------------------------------------------------------ lifecycle
    def init(self) -> None:
        if self.url.startswith("sqlite:///") and not self.url.startswith("sqlite:///:memory:"):
            import pathlib

            path = pathlib.Path(self.url.removeprefix("sqlite:///"))
            if path.parent and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
        if self.is_pg:
            with self.engine.begin() as c:
                c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}"))
        self.md.create_all(self.engine)

    def schema_ready(self) -> tuple[bool, str]:
        """True when the tables carry the multi-workspace columns (i.e. the latest migration has been applied)."""
        try:
            with self.engine.connect() as c:
                c.execute(select(self.t["issues"].c.workspace_id).limit(1))
                c.execute(select(self.t["users"].c.id).limit(1))
                c.execute(select(self.t["documents"].c.indexed_version).limit(1))  # migration 20261109000000
            return True, "ok"
        except Exception as exc:
            return False, f"{type(exc).__name__}: apply the latest supabase/migrations"

    def ping(self) -> tuple[bool, str]:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return True, f"{self.engine.dialect.name} ledger reachable"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:200]}"

    def _w(self, table: str):
        return self.t[table].c.workspace_id == self.ws

    def reset(self) -> None:
        with self.engine.begin() as c:
            for name in ("issue_events", "issues", "documents", "audit_runs", "repair_events", "repair_plans", "query_log"):
                c.execute(delete(self.t[name]).where(self._w(name)))

    # ------------------------------------------------------------------ runs
    def retire_stale_runs(self, max_age: int = STALE_RUN_SECONDS) -> int:
        """Mark runs whose process died (a killed serverless function never records a result) as failed, so they cannot
        block the workspace forever. The message says where the run had got to. Returns how many were retired."""
        runs = self.t["audit_runs"]
        now = utcnow()
        retired = 0
        with self.engine.begin() as c:
            stale = c.execute(select(runs.c.id, runs.c.stats).where(
                self._w("audit_runs"), runs.c.status == "running", runs.c.started_at < now - timedelta(seconds=max_age))).all()
            for run_id, stats in stale:
                progress = stats.get("progress") if isinstance(stats, dict) else None
                msg = "abandoned: the process running it stopped"
                if isinstance(progress, dict) and progress.get("phase"):
                    msg += f" (last step: {progress['phase']}, {progress.get('elapsed_seconds', '?')} s in)"
                c.execute(update(runs).where(runs.c.id == run_id, runs.c.status == "running")
                          .values(status="failed", finished_at=now, error=msg))
                retired += 1
        return retired

    def set_progress(self, run_id: str, phase: str, **info: Any) -> None:
        """Record where a running audit is, so a run that is killed still shows how far it got."""
        runs = self.t["audit_runs"]
        with self.engine.begin() as c:
            c.execute(update(runs).where(self._w("audit_runs"), runs.c.id == run_id, runs.c.status == "running")
                      .values(stats={"progress": {"phase": phase, **info}}))

    def start_run(self, kind: str, trigger: str, scope: Scope | None, stale_after: int = STALE_RUN_SECONDS) -> str:
        run_id = str(uuid.uuid4())
        runs = self.t["audit_runs"]
        now = utcnow()
        self.retire_stale_runs(stale_after)
        try:
            with self.engine.begin() as c:
                c.execute(insert(runs).values(
                    id=run_id, workspace_id=self.ws, kind=kind, trigger=trigger, scope=(scope.to_json() if scope else {}),
                    status="running", started_at=now, stats={}))
        except IntegrityError as exc:
            raise RunInProgress("An audit is already running for this workspace.") from exc
        return run_id

    def finish_run(self, run_id: str, status: str, stats: dict[str, Any], error: str | None = None) -> None:
        runs = self.t["audit_runs"]
        with self.engine.begin() as c:
            c.execute(update(runs).where(self._w("audit_runs"), runs.c.id == run_id).values(
                status=status, finished_at=utcnow(), stats=stats, error=error))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        t = self.t["audit_runs"]
        with self.engine.connect() as c:
            row = c.execute(select(t).where(self._w("audit_runs"), t.c.id == run_id)).mappings().first()
        return _public(row) if row else None

    def list_runs(self, limit: int = 50, kind: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        t = self.t["audit_runs"]
        q = select(t).where(self._w("audit_runs")).order_by(t.c.started_at.desc()).limit(limit)
        if kind:
            q = q.where(t.c.kind == kind)
        if status:
            q = q.where(t.c.status == status)
        with self.engine.connect() as c:
            return [_public(r) for r in c.execute(q).mappings()]

    # ------------------------------------------------------------------ scoping helpers
    def _scope_clause(self, table: str, scope: Scope | None):
        t = self.t[table]
        clauses = [self._w(table)]
        if scope is not None and not scope.is_full:
            if scope.tenant:
                clauses.append(t.c.tenant_id == scope.tenant)
            if scope.keys is not None:
                keys = sorted(scope.keys)
                clauses.append(tuple_(t.c.tenant_id, t.c.document_id).in_(keys) if keys else text("1=0"))
        return and_(*clauses)

    def known_tenants(self) -> set[str]:
        t = self.t["documents"]
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(select(t.c.tenant_id).where(self._w("documents")).distinct())}

    # ------------------------------------------------------------------ applying a run
    def apply_run(
        self, run_id: str, findings: list[Finding], summaries: list[DocSummary], scope: Scope | None,
    ) -> RunDiff:
        now = utcnow()
        diff = RunDiff()
        issues, events = self.t["issues"], self.t["issue_events"]
        with self.engine.begin() as c:
            existing = {r["id"]: r for r in c.execute(select(issues).where(self._scope_clause("issues", scope))).mappings()}
            # findings are always in scope, but be robust to an id living outside it
            missing_ids = [f.issue_id for f in findings if f.issue_id not in existing]
            for chunk in _chunks(missing_ids):
                for r in c.execute(select(issues).where(self._w("issues"), issues.c.id.in_(chunk))).mappings():
                    existing[r["id"]] = r

            inserts: list[dict[str, Any]] = []
            updates: list[dict[str, Any]] = []
            ev_rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            for f in findings:
                iid = f.issue_id
                seen.add(iid)
                row = existing.get(iid)
                base = dict(type=f.type.value, severity=f.severity.value, tenant_id=f.tenant_id, document_id=f.document_id,
                            collection=f.collection, title=f.title, detail=f.detail, evidence=f.evidence, action=f.action.value)
                if row is None:
                    inserts.append({"workspace_id": self.ws, "id": iid, **base, "status": "open", "first_seen_at": now,
                                    "last_seen_at": now, "first_run_id": run_id, "last_run_id": run_id, "occurrences": 1,
                                    "reopened_count": 0})
                    ev_rows.append(dict(workspace_id=self.ws, issue_id=iid, run_id=run_id, ts=now, event="opened",
                                        details={"severity": f.severity.value, "type": f.type.value}))
                    diff.opened.append(f)
                    continue
                upd = {"b_id": iid, **base, "last_seen_at": now, "last_run_id": run_id,
                       "occurrences": row["occurrences"] + 1, "status": row["status"],
                       "resolved_at": row["resolved_at"], "resolved_run_id": row["resolved_run_id"],
                       "reopened_count": row["reopened_count"]}
                if row["status"] == "resolved":
                    upd.update(status="open", resolved_at=None, resolved_run_id=None, reopened_count=row["reopened_count"] + 1)
                    ev_rows.append(dict(workspace_id=self.ws, issue_id=iid, run_id=run_id, ts=now, event="reopened",
                                        details={"severity": f.severity.value}))
                    diff.reopened.append(f)
                elif row["status"] == "open":
                    if SEVERITY_RANK[f.severity.value] != SEVERITY_RANK[row["severity"]]:
                        ev_rows.append(dict(workspace_id=self.ws, issue_id=iid, run_id=run_id, ts=now, event="severity_changed",
                                            details={"from": row["severity"], "to": f.severity.value}))
                        if SEVERITY_RANK[f.severity.value] > SEVERITY_RANK[row["severity"]]:
                            diff.escalated.append(f)
                    diff.unchanged += 1
                updates.append(upd)

            for iid, row in existing.items():
                if iid not in seen and row["status"] == "open" and self._in_scope(row, scope):
                    updates.append({
                        "b_id": iid, **{k: row[k] for k in ("type", "severity", "tenant_id", "document_id", "collection", "title",
                                                             "detail", "evidence", "action", "last_seen_at", "last_run_id",
                                                             "occurrences", "reopened_count")},
                        "status": "resolved", "resolved_at": now, "resolved_run_id": run_id})
                    ev_rows.append(dict(workspace_id=self.ws, issue_id=iid, run_id=run_id, ts=now, event="resolved", details={}))
                    diff.resolved.append(iid)

            if inserts:
                c.execute(insert(issues), inserts)
            if updates:
                cols = ["type", "severity", "tenant_id", "document_id", "collection", "title", "detail", "evidence", "action",
                        "last_seen_at", "last_run_id", "occurrences", "reopened_count", "status", "resolved_at", "resolved_run_id"]
                stmt = update(issues).where(and_(issues.c.workspace_id == bindparam("b_ws"), issues.c.id == bindparam("b_id"))).values(
                    {k: bindparam(f"p_{k}") for k in cols})
                c.execute(stmt, [{"b_ws": self.ws, "b_id": u["b_id"], **{f"p_{k}": u[k] for k in cols}} for u in updates])
            if ev_rows:
                c.execute(insert(events), ev_rows)

            self._upsert_documents(c, run_id, summaries, scope, now)
        return diff

    @staticmethod
    def _in_scope(row: Any, scope: Scope | None) -> bool:
        return scope is None or scope.is_full or scope.matches((row["tenant_id"], row["document_id"]))

    def _upsert_documents(self, c: Connection, run_id: str, summaries: list[DocSummary], scope: Scope | None, now: datetime) -> None:
        docs = self.t["documents"]
        have = {(r[0], r[1]) for r in c.execute(select(docs.c.tenant_id, docs.c.document_id).where(self._scope_clause("documents", scope)))}
        now_keys = {s.key for s in summaries}
        gone = sorted(have - now_keys)
        for chunk in _chunks(gone):
            c.execute(delete(docs).where(self._w("documents"), tuple_(docs.c.tenant_id, docs.c.document_id).in_(chunk)))

        def row(s: DocSummary) -> dict[str, Any]:
            return dict(
                status=s.status, issue_count=len(s.issue_types), worst_severity=s.worst_severity,
                issue_types=s.issue_types, fingerprint=s.fingerprint, source_uri=s.source_uri, source_hash=s.source_hash,
                source_version=s.source_version, size_bytes=s.size_bytes, expected_chunks=s.expected_chunks,
                indexed_chunks=s.indexed_chunks, manifest_status=s.manifest_status, manifest_updated_at=s.manifest_updated_at,
                collections=s.collections, source_present=int(s.source_present), manifest_present=int(s.manifest_present),
                index_present=int(s.index_present), last_verified_at=now, last_run_id=run_id,
                indexed_version=s.indexed_version)

        new_rows = [{"workspace_id": self.ws, "tenant_id": s.tenant_id, "document_id": s.document_id, **row(s)}
                    for s in summaries if s.key not in have]
        old_rows = [s for s in summaries if s.key in have]
        if new_rows:
            c.execute(insert(docs), new_rows)
        if old_rows:
            cols = list(row(old_rows[0]).keys())
            stmt = update(docs).where(and_(docs.c.workspace_id == bindparam("b_ws"), docs.c.tenant_id == bindparam("b_t"),
                                           docs.c.document_id == bindparam("b_d"))).values({k: bindparam(f"p_{k}") for k in cols})
            c.execute(stmt, [{"b_ws": self.ws, "b_t": s.tenant_id, "b_d": s.document_id, **{f"p_{k}": v for k, v in row(s).items()}}
                             for s in old_rows])

    # ------------------------------------------------------------------ issues
    def _issue_filters(self, status, severity, type_, tenant, q):
        t = self.t["issues"]
        conds = [self._w("issues")]
        if status and status != "all":
            conds.append(t.c.status == status)
        if severity:
            conds.append(t.c.severity == severity)
        if type_:
            conds.append(t.c.type == type_)
        if tenant:
            conds.append(t.c.tenant_id == tenant)
        if q:
            like = f"%{q.lower()}%"
            conds.append(func.lower(t.c.document_id).like(like) | func.lower(t.c.title).like(like))
        return conds

    def list_issues(self, *, status: str | None = "open", severity: str | None = None, type: str | None = None,
                    tenant: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        t = self.t["issues"]
        conds = self._issue_filters(status, severity, type, tenant, q)
        rank = case(*[(t.c.severity == k, v) for k, v in SEVERITY_RANK.items()], else_=0)
        with self.engine.connect() as c:
            total = c.execute(select(func.count()).select_from(t).where(*conds)).scalar_one()
            rows = c.execute(select(t).where(*conds).order_by(rank.desc(), t.c.last_seen_at.desc(), t.c.id)
                             .limit(limit).offset(offset)).mappings().all()
        return [_public(r) for r in rows], total

    def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        t = self.t["issues"]
        with self.engine.connect() as c:
            row = c.execute(select(t).where(self._w("issues"), t.c.id == issue_id)).mappings().first()
        return _public(row) if row else None

    def issues_for_document(self, tenant: str, document_id: str, status: str | None = None) -> list[dict[str, Any]]:
        t = self.t["issues"]
        conds = [self._w("issues"), t.c.tenant_id == tenant, t.c.document_id == document_id]
        if status:
            conds.append(t.c.status == status)
        with self.engine.connect() as c:
            return [_public(r) for r in c.execute(select(t).where(*conds)).mappings()]

    def open_issues(self, ids: list[str] | None = None, min_severity: str | None = None) -> list[dict[str, Any]]:
        t = self.t["issues"]
        conds = [self._w("issues"), t.c.status == "open"]
        if ids is not None:
            conds.append(t.c.id.in_(ids))
        with self.engine.connect() as c:
            rows = [_public(r) for r in c.execute(select(t).where(*conds)).mappings()]
        if min_severity:
            rows = [r for r in rows if severity_at_least(r["severity"], min_severity)]
        return rows

    def issue_events(self, issue_id: str, limit: int = 50) -> list[dict[str, Any]]:
        t = self.t["issue_events"]
        with self.engine.connect() as c:
            return [_public(r) for r in c.execute(
                select(t).where(self._w("issue_events"), t.c.issue_id == issue_id)
                .order_by(t.c.ts.desc(), t.c.id.desc()).limit(limit)).mappings()]

    def set_issue_status(self, issue_id: str, status: str, reason: str | None = None) -> bool:
        t, ev = self.t["issues"], self.t["issue_events"]
        if status not in ("open", "ignored"):
            raise ValueError("status must be 'open' or 'ignored'")
        now = utcnow()
        with self.engine.begin() as c:
            row = c.execute(select(t.c.status).where(self._w("issues"), t.c.id == issue_id)).first()
            if row is None:
                return False
            c.execute(update(t).where(self._w("issues"), t.c.id == issue_id).values(
                status=status, ignored_reason=reason if status == "ignored" else None))
            c.execute(insert(ev).values(workspace_id=self.ws, issue_id=issue_id, ts=now,
                                        event="ignored" if status == "ignored" else "unignored", details={"reason": reason}))
        return True

    def issue_counts(self) -> dict[str, Any]:
        t = self.t["issues"]
        w = self._w("issues")
        with self.engine.connect() as c:
            sev = dict(c.execute(select(t.c.severity, func.count()).where(w, t.c.status == "open").group_by(t.c.severity)).all())
            typ = dict(c.execute(select(t.c.type, func.count()).where(w, t.c.status == "open").group_by(t.c.type)).all())
            resolved = c.execute(select(func.count()).select_from(t).where(w, t.c.status == "resolved")).scalar_one()
            ignored = c.execute(select(func.count()).select_from(t).where(w, t.c.status == "ignored")).scalar_one()
        return {"open": sum(sev.values()), "by_severity": {k: sev.get(k, 0) for k in SEVERITY_RANK},
                "by_type": typ, "resolved": resolved, "ignored": ignored}

    # ------------------------------------------------------------------ documents
    def list_documents(self, *, status: str | None = None, tenant: str | None = None, q: str | None = None,
                       limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        t = self.t["documents"]
        conds = [self._w("documents")]
        if status and status != "all":
            conds.append(t.c.status == status)
        if tenant:
            conds.append(t.c.tenant_id == tenant)
        if q:
            conds.append(func.lower(t.c.document_id).like(f"%{q.lower()}%"))
        rank = case(*[(t.c.worst_severity == k, v) for k, v in SEVERITY_RANK.items()], else_=-1)
        with self.engine.connect() as c:
            total = c.execute(select(func.count()).select_from(t).where(*conds)).scalar_one()
            rows = c.execute(select(t).where(*conds).order_by(rank.desc(), t.c.tenant_id, t.c.document_id)
                             .limit(limit).offset(offset)).mappings().all()
        return [_public(r) for r in rows], total

    def get_document(self, tenant: str, document_id: str) -> dict[str, Any] | None:
        t = self.t["documents"]
        with self.engine.connect() as c:
            row = c.execute(select(t).where(self._w("documents"), t.c.tenant_id == tenant,
                                            t.c.document_id == document_id)).mappings().first()
        return _public(row) if row else None

    def documents_for(self, keys: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
        t = self.t["documents"]
        out: dict[tuple[str, str], dict[str, Any]] = {}
        with self.engine.connect() as c:
            for chunk in _chunks(keys):
                for r in c.execute(select(t).where(self._w("documents"),
                                                   tuple_(t.c.tenant_id, t.c.document_id).in_(chunk))).mappings():
                    out[(r["tenant_id"], r["document_id"])] = _public(r)
        return out

    def all_documents(self) -> Iterable[dict[str, Any]]:
        t = self.t["documents"]
        with self.engine.connect() as c:
            for r in c.execution_options(stream_results=True).execute(select(t).where(self._w("documents"))).mappings():
                yield _public(r)

    def document_counts(self) -> dict[str, Any]:
        t = self.t["documents"]
        w = self._w("documents")
        with self.engine.connect() as c:
            by_status = dict(c.execute(select(t.c.status, func.count()).where(w).group_by(t.c.status)).all())
            by_tenant = c.execute(select(
                t.c.tenant_id, func.count(),
                func.sum(case_when_healthy(t)),
            ).where(w).group_by(t.c.tenant_id).order_by(t.c.tenant_id)).all()
        total = sum(by_status.values())
        healthy = by_status.get("healthy", 0) + by_status.get("pending", 0)
        return {
            "total": total, "by_status": by_status,
            "health_score": round(100.0 * healthy / total, 1) if total else None,
            "tenants": [{"tenant_id": r[0], "documents": r[1], "healthy": int(r[2] or 0),
                         "health_score": round(100.0 * int(r[2] or 0) / r[1], 1) if r[1] else None} for r in by_tenant],
        }

    # ------------------------------------------------------------------ repair plans & history
    def save_plan(self, plan_id: str, status: str, items: list[dict], summary: dict, *, create: bool = False) -> None:
        t = self.t["repair_plans"]
        now = utcnow()
        with self.engine.begin() as c:
            if create:
                c.execute(insert(t).values(id=plan_id, workspace_id=self.ws, status=status, created_at=now, updated_at=now,
                                           items=items, summary=summary))
            else:
                c.execute(update(t).where(self._w("repair_plans"), t.c.id == plan_id).values(
                    status=status, updated_at=now, items=items, summary=summary))

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        t = self.t["repair_plans"]
        with self.engine.connect() as c:
            row = c.execute(select(t).where(self._w("repair_plans"), t.c.id == plan_id)).mappings().first()
        return _public(row) if row else None

    def list_plans(self, limit: int = 50) -> list[dict[str, Any]]:
        t = self.t["repair_plans"]
        with self.engine.connect() as c:
            return [_public(r) for r in c.execute(
                select(t).where(self._w("repair_plans")).order_by(t.c.created_at.desc()).limit(limit)).mappings()]

    def workspace_of_plan(self, plan_id: str) -> str | None:
        """The one deliberate cross-workspace lookup: a signed worker callback only carries a plan id."""
        t = self.t["repair_plans"]
        with self.engine.connect() as c:
            row = c.execute(select(t.c.workspace_id).where(t.c.id == plan_id)).first()
        return row[0] if row else None

    def add_repair_event(self, plan_id: str, event: str, details: dict[str, Any] | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(insert(self.t["repair_events"]).values(workspace_id=self.ws, plan_id=plan_id, ts=utcnow(),
                                                             event=event, details=details or {}))

    def repair_events(self, plan_id: str) -> list[dict[str, Any]]:
        t = self.t["repair_events"]
        with self.engine.connect() as c:
            return [_public(r) for r in c.execute(
                select(t).where(self._w("repair_events"), t.c.plan_id == plan_id).order_by(t.c.ts, t.c.id)).mappings()]

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Merged audit trail: issue lifecycle events, repair events and audit runs, newest first."""
        ie, it, re_, ar = self.t["issue_events"], self.t["issues"], self.t["repair_events"], self.t["audit_runs"]
        out: list[dict[str, Any]] = []
        with self.engine.connect() as c:
            for r in c.execute(select(ie, it.c.title, it.c.severity, it.c.tenant_id, it.c.document_id, it.c.type)
                               .join(it, and_(it.c.id == ie.c.issue_id, it.c.workspace_id == ie.c.workspace_id))
                               .where(self._w("issue_events")).order_by(ie.c.ts.desc()).limit(limit)).mappings():
                out.append({"kind": "issue", "ts": iso(r["ts"]), "event": r["event"], "issue_id": r["issue_id"], "run_id": r["run_id"],
                            "title": r["title"], "severity": r["severity"], "tenant_id": r["tenant_id"],
                            "document_id": r["document_id"], "type": r["type"], "details": r["details"]})
            for r in c.execute(select(re_).where(self._w("repair_events")).order_by(re_.c.ts.desc()).limit(limit)).mappings():
                out.append({"kind": "repair", "ts": iso(r["ts"]), "event": r["event"], "plan_id": r["plan_id"], "details": r["details"]})
            for r in c.execute(select(ar).where(self._w("audit_runs"), ar.c.status != "running")
                               .order_by(ar.c.started_at.desc()).limit(limit)).mappings():
                out.append({"kind": "audit", "ts": iso(r["finished_at"] or r["started_at"]), "event": f"audit_{r['status']}",
                            "run_id": r["id"], "details": {"kind": r["kind"], "trigger": r["trigger"], "scope": r["scope"],
                                                           "findings": (r["stats"] or {}).get("findings_total"),
                                                           "health_score": (r["stats"] or {}).get("health_score"),
                                                           "error": r["error"]}})
        out.sort(key=lambda e: e["ts"] or "", reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------ query log (for blast radius)
    def add_queries(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        t = self.t["query_log"]
        with self.engine.begin() as c:
            for chunk in _chunks(rows, 500):
                c.execute(insert(t), [{"workspace_id": self.ws, **r} for r in chunk])
        return len(rows)

    def queries_since(self, days: int) -> list[dict[str, Any]]:
        t = self.t["query_log"]
        since = utcnow() - timedelta(days=days)
        with self.engine.connect() as c:
            return [_public(r) for r in c.execute(select(t).where(self._w("query_log"), t.c.ts >= since)).mappings()]

    def query_count(self) -> int:
        t = self.t["query_log"]
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(t).where(self._w("query_log"))).scalar_one()


def case_when_healthy(t: Table):
    return case((t.c.status.in_(["healthy", "pending"]), 1), else_=0)
