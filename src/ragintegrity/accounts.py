"""Users, sessions, workspaces, API keys, rate limits and encrypted per-workspace settings."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from .ledger import Ledger, aware, iso, utcnow
from .security import (
    Vault,
    burn_password_time,
    hash_password,
    new_token,
    normalize_email,
    password_problem,
    token_hash,
    verify_password,
)

SESSION_REFRESH = timedelta(hours=1)
API_KEY_PREFIX = "ragi_"


class AccountError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Accounts:
    def __init__(self, ledger: Ledger, vault: Vault | None = None, session_days: int = 7) -> None:
        self.ledger = ledger
        self.engine = ledger.engine
        self.t = ledger.t
        self.vault = vault
        self.session_days = session_days

    # ------------------------------------------------------------------ rate limiting (database-backed, so it holds across
    # serverless instances, unlike an in-memory counter)
    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Count one attempt against ``key``; False once more than ``limit`` happened inside the window."""
        t = self.t["rate_limits"]
        for _ in range(2):
            now = utcnow()
            try:
                with self.engine.begin() as c:
                    row = c.execute(select(t.c.window_start, t.c.count).where(t.c.key == key)).first()
                    if row is None or aware(row[0]) + timedelta(seconds=window_seconds) < now:
                        if row is not None:
                            c.execute(delete(t).where(t.c.key == key))
                        c.execute(insert(t).values(key=key, window_start=now, count=1))
                        return True
                    if row[1] >= limit:
                        return False
                    c.execute(update(t).where(t.c.key == key).values(count=t.c.count + 1))
                    return True
            except IntegrityError:  # two requests created the row at once: retry, the second sees it
                continue
        return True

    def clear_hits(self, key: str) -> None:
        with self.engine.begin() as c:
            c.execute(delete(self.t["rate_limits"]).where(self.t["rate_limits"].c.key == key))

    def workspace_name(self, workspace_id: str) -> str | None:
        w = self.t["workspaces"]
        with self.engine.connect() as c:
            row = c.execute(select(w.c.name).where(w.c.id == workspace_id)).first()
        return row[0] if row else None

    # ------------------------------------------------------------------ users
    def register(self, email: str, password: str) -> dict[str, Any]:
        try:
            email = normalize_email(email)
        except ValueError as exc:
            raise AccountError(str(exc), 422) from exc
        problem = password_problem(password, email)
        if problem:
            raise AccountError(problem, 422)
        user_id, ws_id, now = str(uuid.uuid4()), str(uuid.uuid4()), utcnow()
        pw_hash = hash_password(password)
        try:
            with self.engine.begin() as c:
                c.execute(insert(self.t["workspaces"]).values(id=ws_id, name=f"{email.split('@')[0]}'s workspace",
                                                              owner_id=user_id, created_at=now))
                c.execute(insert(self.t["users"]).values(id=user_id, email=email, password_hash=pw_hash,
                                                         workspace_id=ws_id, created_at=now))
        except IntegrityError as exc:
            raise AccountError("An account with that email already exists.", 409) from exc
        return {"id": user_id, "email": email, "workspace_id": ws_id}

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        try:
            email = normalize_email(email)
        except ValueError:
            burn_password_time(password)
            return None
        u = self.t["users"]
        with self.engine.connect() as c:
            row = c.execute(select(u).where(u.c.email == email)).mappings().first()
        if row is None:
            burn_password_time(password)  # same cost as a real check: timing does not reveal registered emails
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        with self.engine.begin() as c:
            c.execute(update(u).where(u.c.id == row["id"]).values(last_login_at=utcnow()))
        return {"id": row["id"], "email": row["email"], "workspace_id": row["workspace_id"]}

    def change_password(self, user_id: str, current: str, new: str, keep_session: str | None = None) -> None:
        u = self.t["users"]
        with self.engine.connect() as c:
            row = c.execute(select(u.c.email, u.c.password_hash).where(u.c.id == user_id)).first()
        if row is None or not verify_password(current, row[1]):
            raise AccountError("Your current password is incorrect.", 403)
        problem = password_problem(new, row[0])
        if problem:
            raise AccountError(problem, 422)
        with self.engine.begin() as c:
            c.execute(update(u).where(u.c.id == user_id).values(password_hash=hash_password(new)))
        self.delete_user_sessions(user_id, except_hash=token_hash(keep_session) if keep_session else None)

    # ------------------------------------------------------------------ sessions
    def create_session(self, user_id: str, workspace_id: str, ip: str | None, user_agent: str | None) -> tuple[str, datetime]:
        token = new_token()
        now = utcnow()
        expires = now + timedelta(days=self.session_days)
        s = self.t["sessions"]
        with self.engine.begin() as c:
            c.execute(delete(s).where(s.c.expires_at < now))  # opportunistic cleanup
            c.execute(insert(s).values(token_hash=token_hash(token), user_id=user_id, workspace_id=workspace_id, created_at=now,
                                       expires_at=expires, last_used_at=now, ip=(ip or "")[:64], user_agent=(user_agent or "")[:200]))
        return token, expires

    def session_user(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        th, now = token_hash(token), utcnow()
        s, u = self.t["sessions"], self.t["users"]
        with self.engine.connect() as c:
            row = c.execute(select(s.c.user_id, s.c.workspace_id, s.c.expires_at, s.c.last_used_at, u.c.email)
                            .join(u, u.c.id == s.c.user_id).where(s.c.token_hash == th)).first()
        if row is None or aware(row[2]) <= now:
            return None
        if aware(row[3]) + SESSION_REFRESH < now:  # sliding expiry, written at most once an hour
            with self.engine.begin() as c:
                c.execute(update(s).where(s.c.token_hash == th).values(
                    last_used_at=now, expires_at=now + timedelta(days=self.session_days)))
        return {"id": row[0], "workspace_id": row[1], "email": row[4], "session_hash": th}

    def delete_session(self, token: str | None) -> None:
        if token:
            with self.engine.begin() as c:
                c.execute(delete(self.t["sessions"]).where(self.t["sessions"].c.token_hash == token_hash(token)))

    def delete_user_sessions(self, user_id: str, except_hash: str | None = None) -> None:
        s = self.t["sessions"]
        q = delete(s).where(s.c.user_id == user_id)
        if except_hash:
            q = q.where(s.c.token_hash != except_hash)
        with self.engine.begin() as c:
            c.execute(q)

    # ------------------------------------------------------------------ API keys (for CI / cron / query-log ingestion)
    def create_api_key(self, workspace_id: str, name: str) -> tuple[str, dict[str, Any]]:
        name = (name or "").strip()[:80]
        if not name:
            raise AccountError("Give the key a name.", 422)
        token = new_token(API_KEY_PREFIX)
        row = {"id": str(uuid.uuid4()), "workspace_id": workspace_id, "name": name, "token_hash": token_hash(token),
               "prefix": token[:12], "created_at": utcnow()}
        with self.engine.begin() as c:
            c.execute(insert(self.t["api_keys"]).values(**row))
        return token, {"id": row["id"], "name": name, "prefix": row["prefix"], "created_at": iso(row["created_at"])}

    def list_api_keys(self, workspace_id: str) -> list[dict[str, Any]]:
        k = self.t["api_keys"]
        with self.engine.connect() as c:
            rows = c.execute(select(k).where(k.c.workspace_id == workspace_id, k.c.revoked_at.is_(None))
                             .order_by(k.c.created_at.desc())).mappings().all()
        return [{"id": r["id"], "name": r["name"], "prefix": r["prefix"], "created_at": iso(r["created_at"]),
                 "last_used_at": iso(r["last_used_at"])} for r in rows]

    def revoke_api_key(self, workspace_id: str, key_id: str) -> bool:
        k = self.t["api_keys"]
        with self.engine.begin() as c:
            res = c.execute(update(k).where(k.c.workspace_id == workspace_id, k.c.id == key_id, k.c.revoked_at.is_(None))
                            .values(revoked_at=utcnow()))
        return res.rowcount > 0

    def api_key_workspace(self, token: str | None) -> str | None:
        if not token or not token.startswith(API_KEY_PREFIX):
            return None
        k, th, now = self.t["api_keys"], token_hash(token), utcnow()
        with self.engine.connect() as c:
            row = c.execute(select(k.c.workspace_id, k.c.last_used_at).where(k.c.token_hash == th, k.c.revoked_at.is_(None))).first()
        if row is None:
            return None
        if row[1] is None or aware(row[1]) + timedelta(minutes=10) < now:
            with self.engine.begin() as c:
                c.execute(update(k).where(k.c.token_hash == th).values(last_used_at=now))
        return row[0]

    # ------------------------------------------------------------------ per-workspace settings (secrets encrypted)
    def load_settings(self, workspace_id: str) -> dict[str, dict[str, Any]]:
        """{kind: {"config": {...}, "secrets": {...}, "updated_at": datetime, "last_test": {...}|None}}"""
        w = self.t["workspace_settings"]
        with self.engine.connect() as c:
            rows = c.execute(select(w).where(w.c.workspace_id == workspace_id)).mappings().all()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            secrets: dict[str, Any] = {}
            if r["secrets"]:
                if self.vault is None:
                    raise AccountError("The server has no RAGI_SECRET_KEY, so stored secrets cannot be read.", 500)
                secrets = self.vault.decrypt(r["secrets"])
            out[r["kind"]] = {"config": dict(r["config"] or {}), "secrets": secrets, "updated_at": r["updated_at"],
                              "last_test": r["last_test"]}
        return out

    def save_settings(self, workspace_id: str, kind: str, config: dict[str, Any], secrets: dict[str, Any]) -> None:
        w = self.t["workspace_settings"]
        if secrets and self.vault is None:
            raise AccountError("The server has no RAGI_SECRET_KEY, so secrets cannot be stored.", 500)
        blob = self.vault.encrypt(secrets) if secrets and self.vault else None
        now = utcnow()
        with self.engine.begin() as c:
            exists = c.execute(select(w.c.kind).where(w.c.workspace_id == workspace_id, w.c.kind == kind)).first()
            if exists:
                c.execute(update(w).where(w.c.workspace_id == workspace_id, w.c.kind == kind)
                          .values(config=config, secrets=blob, updated_at=now, last_test=None))
            else:
                c.execute(insert(w).values(workspace_id=workspace_id, kind=kind, config=config, secrets=blob,
                                           updated_at=now, last_test=None))

    def set_last_test(self, workspace_id: str, kind: str, result: dict[str, Any]) -> None:
        w = self.t["workspace_settings"]
        with self.engine.begin() as c:
            c.execute(update(w).where(w.c.workspace_id == workspace_id, w.c.kind == kind).values(last_test=result))

    def settings_version(self, workspace_id: str) -> str:
        """Changes whenever any of the workspace's settings change (cache key for the per-workspace service)."""
        w = self.t["workspace_settings"]
        with self.engine.connect() as c:
            rows = c.execute(select(w.c.kind, w.c.updated_at).where(w.c.workspace_id == workspace_id)).all()
        return "|".join(f"{k}:{iso(u)}" for k, u in sorted(rows))

    # ------------------------------------------------------------------ admin helpers
    def delete_user(self, email: str) -> bool:
        """Remove a user and everything their workspace owns (used by the CLI and by tests)."""
        u, w = self.t["users"], self.t["workspaces"]
        with self.engine.connect() as c:
            row = c.execute(select(u.c.id, u.c.workspace_id).where(u.c.email == normalize_email(email))).first()
        if row is None:
            return False
        user_id, ws = row
        scoped = self.ledger.for_workspace(ws)
        scoped.reset()
        with self.engine.begin() as c:
            for name in ("sessions",):
                c.execute(delete(self.t[name]).where(self.t[name].c.user_id == user_id))
            c.execute(delete(self.t["api_keys"]).where(self.t["api_keys"].c.workspace_id == ws))
            c.execute(delete(self.t["workspace_settings"]).where(self.t["workspace_settings"].c.workspace_id == ws))
            c.execute(delete(u).where(u.c.id == user_id))
            c.execute(delete(w).where(w.c.id == ws))
        return True
