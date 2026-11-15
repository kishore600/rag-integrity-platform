"""The operator's view across every workspace of a hosted RAGGuard: who signed up, who signs in, who ran audits.

Read-only, and deliberately narrow. It never returns password hashes, session tokens, IP addresses, browser strings, API keys
or any settings value: for connections it only says which systems a workspace has saved. Audit errors are scrubbed of
passwords and web addresses before they leave, because some older run errors were stored as the raw exception text.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from .ledger import Ledger, aware, iso, utcnow
from .security import redact_urls, scrub

DAYS = 30  # the length of the daily series
INDEX_KINDS = ("qdrant", "pgvector")
FINISHED = ("completed", "partial")  # an audit that produced results


def _clean_error(error: str | None) -> str | None:
    return redact_urls(scrub(error, 300)) if error else None


def _duration(started: datetime | None, finished: datetime | None, stats: dict[str, Any]) -> float | None:
    if isinstance(stats.get("duration_seconds"), (int, float)):
        return round(float(stats["duration_seconds"]), 1)
    if started and finished:
        return round((aware(finished) - aware(started)).total_seconds(), 1)
    return None


class AdminView:
    def __init__(self, ledger: Ledger) -> None:
        self.engine = ledger.engine
        self.t = ledger.t

    # ------------------------------------------------------------------ building blocks
    def _systems(self) -> dict[str, list[str]]:
        """{workspace_id: [saved settings kinds]}: which systems each workspace has saved, never their values."""
        w = self.t["workspace_settings"]
        out: dict[str, list[str]] = defaultdict(list)
        with self.engine.connect() as c:
            for ws, kind in c.execute(select(w.c.workspace_id, w.c.kind)):
                out[ws].append(kind)
        return {ws: sorted(kinds) for ws, kinds in out.items()}

    @staticmethod
    def _connected(kinds: list[str]) -> bool:
        """Saved a source and an index: enough to run an audit (the manifest is optional)."""
        return "s3" in kinds and any(k in kinds for k in INDEX_KINDS)

    def _last_seen(self) -> dict[str, datetime]:
        """{user_id: the latest use of any of their sessions}. Sessions record use at most once an hour."""
        s = self.t["sessions"]
        with self.engine.connect() as c:
            rows = c.execute(select(s.c.user_id, func.max(s.c.last_used_at)).group_by(s.c.user_id)).all()
        return {uid: aware(at) for uid, at in rows if at}

    def _run_summary(self) -> dict[str, dict[str, Any]]:
        """{workspace_id: {total, failed, last}} over every audit of every workspace."""
        r = self.t["audit_runs"]
        out: dict[str, dict[str, Any]] = {}
        with self.engine.connect() as c:
            for ws, status, n in c.execute(select(r.c.workspace_id, r.c.status, func.count()).group_by(r.c.workspace_id, r.c.status)):
                e = out.setdefault(ws, {"total": 0, "failed": 0, "finished": 0, "last": None})
                e["total"] += n
                if status == "failed":
                    e["failed"] += n
                if status in FINISHED:
                    e["finished"] += n
            latest = (select(r.c.workspace_id, func.max(r.c.started_at).label("at")).group_by(r.c.workspace_id)).subquery()
            rows = c.execute(select(r.c.workspace_id, r.c.status, r.c.started_at, r.c.stats)
                             .join(latest, (latest.c.workspace_id == r.c.workspace_id) & (latest.c.at == r.c.started_at))).all()
        for ws, status, started, stats in rows:
            stats = stats or {}
            out.setdefault(ws, {"total": 0, "failed": 0, "finished": 0, "last": None})["last"] = {
                "status": status, "started_at": iso(started), "health_score": stats.get("health_score"),
                "documents": stats.get("documents_total"), "findings": stats.get("findings_total"),
            }
        return out

    # ------------------------------------------------------------------ the three views
    def users(self) -> list[dict[str, Any]]:
        """Every account, newest first, with its workspace, saved systems and audit activity."""
        u, w = self.t["users"], self.t["workspaces"]
        with self.engine.connect() as c:
            rows = c.execute(select(u.c.id, u.c.email, u.c.created_at, u.c.last_login_at, u.c.workspace_id, w.c.name)
                             .join(w, w.c.id == u.c.workspace_id, isouter=True).order_by(u.c.created_at.desc())).all()
        systems, seen, runs = self._systems(), self._last_seen(), self._run_summary()
        out = []
        for uid, email, created, last_login, ws, ws_name in rows:
            kinds = systems.get(ws, [])
            activity = [x for x in (aware(last_login), seen.get(uid)) if x]
            r = runs.get(ws, {"total": 0, "failed": 0, "finished": 0, "last": None})
            out.append({
                "email": email,
                "workspace": ws_name or "Workspace",
                "created_at": iso(created),
                "last_login_at": iso(last_login),
                "last_active_at": iso(max(activity)) if activity else None,
                "systems": kinds,
                "connected": self._connected(kinds),
                "audits": r["total"],
                "audits_failed": r["failed"],
                "last_audit": r["last"],
            })
        return out

    def audits(self, limit: int = 100) -> list[dict[str, Any]]:
        """The latest audits across all workspaces, newest first, with who ran them."""
        r, u, w = self.t["audit_runs"], self.t["users"], self.t["workspaces"]
        with self.engine.connect() as c:
            rows = c.execute(
                select(r.c.id, r.c.kind, r.c.trigger, r.c.status, r.c.started_at, r.c.finished_at, r.c.stats, r.c.error,
                       w.c.name, u.c.email)
                .join(w, w.c.id == r.c.workspace_id, isouter=True)
                .join(u, u.c.id == w.c.owner_id, isouter=True)
                .order_by(r.c.started_at.desc()).limit(limit)
            ).all()
        out = []
        for run_id, kind, trigger, status, started, finished, stats, error, ws_name, email in rows:
            stats = stats or {}
            out.append({
                "id": run_id, "kind": kind, "trigger": trigger, "status": status,
                "email": email, "workspace": ws_name or "Workspace",
                "started_at": iso(started), "finished_at": iso(finished),
                "duration_seconds": _duration(started, finished, stats),
                "documents": stats.get("documents_total"), "findings": stats.get("findings_total"),
                "health_score": stats.get("health_score"),
                "error": _clean_error(error),
            })
        return out

    def overview(self, now: datetime | None = None) -> dict[str, Any]:
        """Totals, the sign-up funnel and a daily series of sign-ups and audits for the last 30 days."""
        now = now or utcnow()
        week, month = now - timedelta(days=7), now - timedelta(days=DAYS)
        users = self.users()
        u_created = [aware(_at(x["created_at"])) for x in users]
        active = [x for x in users if x["last_active_at"] and _at(x["last_active_at"]) >= week]

        r = self.t["audit_runs"]
        with self.engine.connect() as c:
            total_runs = c.execute(select(func.count()).select_from(r)).scalar_one()
            recent = c.execute(select(r.c.status, r.c.started_at).where(r.c.started_at >= month)).all()
        runs_week = [s for s, at in recent if aware(at) >= week]

        days = [(now - timedelta(days=i)).date() for i in range(DAYS - 1, -1, -1)]
        signups_by_day = Counter(d.date() for d in u_created if d and d >= month)
        runs_by_day = Counter(aware(at).date() for _, at in recent)
        failed_by_day = Counter(aware(at).date() for s, at in recent if s == "failed")
        return {
            "generated_at": iso(now),
            "users": {"total": len(users), "new_7d": sum(1 for d in u_created if d and d >= week),
                      "new_30d": sum(1 for d in u_created if d and d >= month), "active_7d": len(active)},
            "funnel": {"signed_up": len(users), "connected": sum(1 for x in users if x["connected"]),
                       "audited": sum(1 for x in users if x["audits"] > 0)},
            "audits": {"total": total_runs, "last_7d": len(runs_week),
                       "failed_7d": sum(1 for s in runs_week if s == "failed"),
                       "running": sum(1 for s, _ in recent if s in ("running", "queued"))},
            "daily": [{"date": d.isoformat(), "signups": signups_by_day.get(d, 0), "audits": runs_by_day.get(d, 0),
                       "failed": failed_by_day.get(d, 0)} for d in days],
        }


def _at(value: str | None) -> datetime | None:
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00"))) if value else None
