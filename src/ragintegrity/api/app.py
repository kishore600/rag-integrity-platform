"""HTTP API + dashboard. Serves the single-user modes (demo / live) and the multi-user ``app`` mode."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..accounts import AccountError, Accounts
from ..config import Settings, get_settings
from ..connectors.base import ConnectorError, SetupIncomplete, UpstreamError
from ..engine.audit import AuditTimeout
from ..ledger import Ledger
from ..models import Scope
from ..repair import RepairError
from ..security import Vault, VaultError, scrub
from ..service import AuditBusy, IntegrityService
from ..workspaces import WorkspaceManager

log = logging.getLogger("ragintegrity.api")
STATIC = Path(__file__).parent / "static"
COOKIE = "ragi_session"
Sev = Literal["critical", "high", "medium", "low", "info"]
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_API_KEYS = 20


class DocRef(BaseModel):
    tenant_id: str = Field(max_length=256)
    document_id: str = Field(max_length=2048)


class AuditRequest(BaseModel):
    tenant: str | None = Field(default=None, max_length=256)
    documents: list[DocRef] | None = Field(default=None, max_length=5000)
    probe: bool | None = None
    wait: bool = False  # run synchronously and return the result (handy for CI)


class PlanRequest(BaseModel):
    issue_ids: list[str] | None = Field(default=None, max_length=5000)
    min_severity: Sev | None = None
    tenant: str | None = Field(default=None, max_length=256)
    types: list[str] | None = Field(default=None, max_length=20)


class IgnoreRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class BlastRequest(BaseModel):
    scenario: dict[str, Any] = Field(default_factory=lambda: {"type": "open_issues"})


class QueryLogRequest(BaseModel):
    queries: list[dict[str, Any]] = Field(max_length=5000)


class DemoResetRequest(BaseModel):
    seed: int | None = None


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class SettingsBody(BaseModel):
    values: dict[str, Any] | None = None


class KeyRequest(BaseModel):
    name: str = Field(max_length=80)


@dataclass
class Principal:
    user_id: str | None
    email: str | None
    workspace_id: str
    via: str  # session | api_key
    session_hash: str | None = None


class AppState:
    """Lazily builds (and retries building) the multi-user machinery, so a database that is briefly unreachable at
    cold start does not leave a serverless instance permanently broken."""

    def __init__(self, settings: Settings, ledger: Ledger | None) -> None:
        self.settings = settings
        self.ledger = ledger
        self.accounts: Accounts | None = None
        self.manager: WorkspaceManager | None = None
        self.problems: list[str] = []
        self._last = 0.0
        self._lock = threading.Lock()

    def ensure(self) -> bool:
        if self.manager is not None:
            return True
        with self._lock:
            if self.manager is not None:
                return True
            if self.problems and time.monotonic() - self._last < 5:
                return False
            self._last = time.monotonic()
            self.problems = []
            s = self.settings
            vault = None
            try:
                vault = Vault(s.secret_key)
            except VaultError as exc:
                self.problems.append(str(exc))
            if self.ledger is None:
                self.ledger = Ledger(s.database_url)
            if os.environ.get("VERCEL") and not self.ledger.is_pg:
                self.problems.append("RAGI_DATABASE_URL must point to a Postgres / Supabase database: serverless storage is "
                                     "ephemeral, so accounts would be lost.")
            if not self.problems:
                try:
                    self.ledger.init()
                    ok, why = self.ledger.schema_ready()
                    if not ok:
                        self.problems.append(f"The database schema is out of date ({why}).")
                except Exception as exc:
                    self.problems.append(f"The database is not reachable: {scrub(f'{type(exc).__name__}: {exc}', 200)}")
            if self.problems:
                return False
            self.accounts = Accounts(self.ledger, vault, s.session_days)
            self.manager = WorkspaceManager(s, self.ledger, self.accounts)
            return True


async def scheduler_loop(svc: IntegrityService, interval_seconds: float) -> None:
    """Built-in scheduled audits (RAGI_AUDIT_INTERVAL_MINUTES). Overlapping runs are skipped, failures are logged."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(svc.run_audit, None, "schedule")
        except AuditBusy:
            log.info("scheduled audit skipped: one is already running")
        except Exception:
            log.exception("scheduled audit failed")


def client_ip(request: Request) -> str:
    for header in ("x-real-ip",):
        v = request.headers.get(header)
        if v:
            return v.strip()[:64]
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def create_app(service: IntegrityService | None = None, settings: Settings | None = None, ledger: Ledger | None = None) -> FastAPI:
    settings = settings or (service.settings if service else get_settings())
    multi = settings.is_app and service is None
    state = AppState(settings, ledger) if multi else None
    svc = None if multi else (service or IntegrityService(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks: list[asyncio.Task] = []
        if svc is not None:
            try:
                await asyncio.to_thread(svc.ensure_ready)
            except Exception:
                log.exception("bootstrap audit failed")  # retried lazily on the first API request
            if settings.audit_interval_minutes > 0:
                tasks.append(asyncio.create_task(scheduler_loop(svc, settings.audit_interval_minutes * 60)))
        elif state is not None:
            await asyncio.to_thread(state.ensure)
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="RAG Integrity", version=__version__, lifespan=lifespan,
                  description="Know when your RAG index is wrong - before your users do.")
    app.state.service = svc
    app.state.app_state = state

    # ------------------------------------------------------------------ middleware (the last one added is the outermost)
    @app.middleware("http")
    async def csrf_origin(request: Request, call_next):
        """Cookie-authenticated writes must come from this very site. SameSite=Lax already blocks cross-site POSTs; this
        is the second lock. Bearer-token (API key) calls carry no cookie and are not affected."""
        path = request.url.path
        if (multi and request.method in UNSAFE_METHODS and path.startswith("/api/") and request.cookies.get(COOKIE)
                and not path.endswith("/callback")):
            origin = request.headers.get("origin") or request.headers.get("referer") or ""
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
            if not origin or urlparse(origin).netloc != host:
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def readiness(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            if state is not None and path not in ("/api/session", "/api/auth"):
                if not await asyncio.to_thread(state.ensure):
                    return JSONResponse({"detail": "This deployment is not set up yet.", "setup": state.problems}, status_code=503)
            elif svc is not None and path != "/api/auth":
                try:
                    await asyncio.to_thread(svc.ensure_ready)
                except Exception as exc:
                    log.exception("bootstrap failed")
                    return JSONResponse({"detail": f"Service is not ready ({type(exc).__name__}). Check the ledger connection."},
                                        status_code=503)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(("/docs", "/redoc")):  # Swagger UI loads its assets from a CDN
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ errors
    @app.exception_handler(AuditBusy)
    async def _busy(_: Request, exc: AuditBusy):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(RepairError)
    async def _repair(_: Request, exc: RepairError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(AccountError)
    async def _account(_: Request, exc: AccountError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(SetupIncomplete)
    async def _setup(_: Request, exc: SetupIncomplete):
        return JSONResponse({"detail": str(exc), "setup_incomplete": True}, status_code=409)

    @app.exception_handler(AuditTimeout)
    async def _timeout(_: Request, exc: AuditTimeout):
        return JSONResponse({"detail": str(exc)}, status_code=504)

    @app.exception_handler(ConnectorError)
    async def _connector(_: Request, exc: ConnectorError):
        return JSONResponse({"detail": scrub(str(exc))}, status_code=503)

    @app.exception_handler(UpstreamError)
    async def _upstream(_: Request, exc: UpstreamError):
        return JSONResponse({"detail": scrub(str(exc)), "upstream": True}, status_code=502)

    @app.exception_handler(ValueError)
    async def _value(_: Request, exc: ValueError):
        return JSONResponse({"detail": scrub(str(exc))}, status_code=400)

    # ------------------------------------------------------------------ authentication / service resolution
    def require_key(request: Request) -> None:
        expected = settings.api_key
        if not expected:
            return
        supplied = request.headers.get("x-api-key") or ""
        auth_header = request.headers.get("authorization") or ""
        if not supplied and auth_header.lower().startswith("bearer "):
            supplied = auth_header[7:]
        if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "Missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})

    def soft_principal(request: Request) -> Principal | None:
        assert state is not None and state.accounts is not None
        tok = request.cookies.get(COOKIE)
        if tok:
            u = state.accounts.session_user(tok)
            if u:
                return Principal(u["id"], u["email"], u["workspace_id"], "session", u["session_hash"])
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            ws = state.accounts.api_key_workspace(auth_header[7:].strip())
            if ws:
                return Principal(None, None, ws, "api_key")
        return None

    def get_principal(request: Request) -> Principal:
        if state is None or not state.ensure():
            raise HTTPException(503, "This deployment is not set up yet.")
        p = soft_principal(request)
        if p is None:
            raise HTTPException(401, "Sign in required.", headers={"WWW-Authenticate": "Bearer"})
        return p

    def session_only(request: Request) -> Principal:
        p = get_principal(request)
        if p.via != "session":
            raise HTTPException(403, "This action needs a signed-in session, not an API key.")
        return p

    def get_svc(request: Request) -> IntegrityService:
        if not multi:
            require_key(request)
            assert svc is not None
            return svc
        p = get_principal(request)
        assert state is not None and state.manager is not None
        s = state.manager.service(p.workspace_id)
        s.callback_base = str(request.base_url).rstrip("/")
        return s

    def set_session_cookie(request: Request, response: Response, token: str) -> None:
        response.set_cookie(COOKIE, token, max_age=settings.session_days * 86400, httponly=True, samesite="lax",
                            secure=is_https(request), path="/")

    # ------------------------------------------------------------------ public
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, Any]:
        led = svc.ledger if svc is not None else (state.ledger if state is not None else None)
        ok, detail = led.ping() if led is not None else (False, "no ledger")
        out: dict[str, Any] = {"ok": ok, "version": __version__, "mode": settings.mode, "ledger": detail}
        if state is not None:
            out["setup_required"] = state.manager is None
        return out

    @app.get("/api/auth", include_in_schema=False)
    def auth_info() -> dict[str, bool]:
        return {"required": bool(settings.api_key) and not multi}

    @app.get("/api/session", include_in_schema=False)
    def session_info(request: Request) -> dict[str, Any]:
        base: dict[str, Any] = {"app": multi, "mode": settings.mode, "version": __version__}
        if not multi:
            return {**base, "authenticated": True, "demo": settings.is_demo, "api_key_required": bool(settings.api_key)}
        assert state is not None
        if not state.ensure():
            return {**base, "authenticated": False, "registration_open": False,
                    "setup": {"required": True, "problems": state.problems}}
        p = soft_principal(request)
        out = {**base, "authenticated": p is not None, "registration_open": settings.allow_registration,
               "setup": {"required": False}, "user": None}
        if p is not None and p.via == "session":
            assert state.manager is not None
            out["user"] = {"email": p.email}
            out["ready"] = state.manager.is_ready(p.workspace_id)
        return out

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------------------ accounts (app mode)
    def need_multi() -> AppState:
        if state is None:
            raise HTTPException(404, "Accounts are not enabled in this mode.")
        return state

    @app.post("/api/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response) -> dict[str, Any]:
        st = need_multi()
        if not settings.allow_registration:
            raise HTTPException(403, "Registration is closed on this server.")
        assert st.accounts is not None
        ip = client_ip(request)
        if not st.accounts.hit(f"register:ip:{ip}", 5, 3600):
            raise HTTPException(429, "Too many sign-ups from your network. Try again later.")
        user = st.accounts.register(body.email, body.password)
        token, _ = st.accounts.create_session(user["id"], user["workspace_id"], ip, request.headers.get("user-agent"))
        set_session_cookie(request, response, token)
        return {"user": {"email": user["email"]}}

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response) -> dict[str, Any]:
        st = need_multi()
        assert st.accounts is not None
        ip = client_ip(request)
        email_key = "login:email:" + hashlib.sha256(body.email.strip().lower().encode()).hexdigest()[:32]
        if not st.accounts.hit(f"login:ip:{ip}", 30, 900) or not st.accounts.hit(email_key, 8, 900):
            raise HTTPException(429, "Too many sign-in attempts. Wait a few minutes and try again.")
        user = st.accounts.authenticate(body.email, body.password)
        if user is None:
            raise HTTPException(401, "Invalid email or password.")
        st.accounts.clear_hits(email_key)
        token, _ = st.accounts.create_session(user["id"], user["workspace_id"], ip, request.headers.get("user-agent"))
        set_session_cookie(request, response, token)
        return {"user": {"email": user["email"]}}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        st = need_multi()
        assert st.accounts is not None
        st.accounts.delete_session(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/auth/password")
    def change_password(body: PasswordChange, request: Request, p: Principal = Depends(session_only)) -> dict[str, bool]:
        st = need_multi()
        assert st.accounts is not None and p.user_id is not None
        if not st.accounts.hit(f"password:{p.user_id}", 10, 900):
            raise HTTPException(429, "Too many attempts. Try again later.")
        st.accounts.change_password(p.user_id, body.current_password, body.new_password, keep_session=request.cookies.get(COOKIE))
        return {"ok": True}

    # ------------------------------------------------------------------ settings & API keys (app mode, signed-in sessions only)
    @app.get("/api/settings")
    def get_settings_view(p: Principal = Depends(session_only)) -> dict[str, Any]:
        assert state is not None and state.manager is not None
        return state.manager.view(p.workspace_id)

    @app.put("/api/settings/{kind}")
    def put_settings(kind: str, body: SettingsBody, p: Principal = Depends(session_only)) -> dict[str, Any]:
        assert state is not None and state.manager is not None
        return state.manager.save(p.workspace_id, kind, body.values or {})

    @app.post("/api/settings/{kind}/test")
    def test_settings(kind: str, body: SettingsBody | None = None, p: Principal = Depends(session_only)) -> dict[str, Any]:
        assert state is not None and state.manager is not None and state.accounts is not None
        # a connection test makes this server open outbound connections: keep it from being used as a port scanner
        if not state.accounts.hit(f"test:{p.workspace_id}", 30, 600):
            raise HTTPException(429, "Too many connection tests. Try again in a few minutes.")
        return state.manager.test(p.workspace_id, kind, body.values if body is not None else None)

    @app.get("/api/keys")
    def list_keys(p: Principal = Depends(session_only)) -> list[dict[str, Any]]:
        assert state is not None and state.accounts is not None
        return state.accounts.list_api_keys(p.workspace_id)

    @app.post("/api/keys", status_code=201)
    def create_key(body: KeyRequest, p: Principal = Depends(session_only)) -> dict[str, Any]:
        assert state is not None and state.accounts is not None
        if len(state.accounts.list_api_keys(p.workspace_id)) >= MAX_API_KEYS:
            raise HTTPException(409, f"You can have at most {MAX_API_KEYS} API keys. Revoke one first.")
        token, row = state.accounts.create_api_key(p.workspace_id, body.name)
        return {"token": token, "key": row, "note": "Copy the token now: it is shown only once."}

    @app.delete("/api/keys/{key_id}")
    def revoke_key(key_id: str, p: Principal = Depends(session_only)) -> dict[str, bool]:
        assert state is not None and state.accounts is not None
        if not state.accounts.revoke_api_key(p.workspace_id, key_id):
            raise HTTPException(404, "API key not found")
        return {"ok": True}

    # ------------------------------------------------------------------ overview / connections
    @app.get("/api/overview")
    def overview(s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.overview()

    @app.get("/api/connections")
    def connections(s: IntegrityService = Depends(get_svc)) -> list[dict[str, Any]]:
        return s.connections()

    # ------------------------------------------------------------------ audits
    @app.post("/api/audits", status_code=202)
    def start_audit(req: AuditRequest | None = None, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        req = req or AuditRequest()
        scope = None
        if req.tenant or req.documents:
            keys = frozenset((d.tenant_id, d.document_id) for d in req.documents) if req.documents else None
            scope = Scope(tenant=req.tenant, keys=keys)
        if req.wait:
            r = s.run_audit(scope=scope, trigger="api", probe=req.probe)
            return {"run_id": r.run_id, "status": "completed", "stats": r.stats}
        run_id = s.start_audit_async(scope=scope, trigger="api", probe=req.probe)
        run = s.ledger.get_run(run_id)  # already "completed" on serverless hosts, where audits run inline
        return {"run_id": run_id, "status": run["status"] if run else "running"}

    @app.get("/api/audits")
    def list_audits(limit: int = Query(30, ge=1, le=200), s: IntegrityService = Depends(get_svc)) -> list[dict[str, Any]]:
        return s.ledger.list_runs(limit=limit)

    @app.get("/api/audits/{run_id}")
    def get_audit(run_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        run = s.ledger.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Audit run not found")
        return run

    # ------------------------------------------------------------------ issues
    @app.get("/api/issues")
    def list_issues(
        status: str | None = Query("open", pattern="^(open|resolved|ignored|all)$"),
        severity: Sev | None = None, type: str | None = Query(None, max_length=40), tenant: str | None = Query(None, max_length=256),
        q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
        s: IntegrityService = Depends(get_svc),
    ) -> dict[str, Any]:
        rows, total = s.ledger.list_issues(status=status, severity=severity, type=type, tenant=tenant, q=q,
                                           limit=limit, offset=offset)
        return {"total": total, "items": rows}

    @app.get("/api/issues/{issue_id}")
    def get_issue(issue_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        issue = s.ledger.get_issue(issue_id)
        if issue is None:
            raise HTTPException(404, "Issue not found")
        return {**issue, "events": s.ledger.issue_events(issue_id)}

    @app.post("/api/issues/{issue_id}/ignore")
    def ignore_issue(issue_id: str, req: IgnoreRequest | None = None, s: IntegrityService = Depends(get_svc)) -> dict[str, bool]:
        if not s.ledger.set_issue_status(issue_id, "ignored", (req.reason if req else None)):
            raise HTTPException(404, "Issue not found")
        return {"ok": True}

    @app.post("/api/issues/{issue_id}/reopen")
    def reopen_issue(issue_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, bool]:
        if not s.ledger.set_issue_status(issue_id, "open"):
            raise HTTPException(404, "Issue not found")
        return {"ok": True}

    # ------------------------------------------------------------------ documents
    @app.get("/api/documents")
    def list_documents(
        status: str | None = Query(None, pattern="^(healthy|degraded|broken|pending|orphaned|all)$"),
        tenant: str | None = Query(None, max_length=256), q: str | None = Query(None, max_length=200),
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), s: IntegrityService = Depends(get_svc),
    ) -> dict[str, Any]:
        rows, total = s.ledger.list_documents(status=status, tenant=tenant, q=q, limit=limit, offset=offset)
        return {"total": total, "items": rows}

    @app.get("/api/document")
    def get_document(tenant: str = Query(max_length=256), document_id: str = Query(max_length=2048), live: bool = False,
                     s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        doc = s.ledger.get_document(tenant, document_id)
        issues = s.ledger.issues_for_document(tenant, document_id)
        if doc is None and not issues:
            raise HTTPException(404, "Document not found")
        out: dict[str, Any] = {"document": doc, "issues": issues}
        if live:
            out["live"] = s.inspect(tenant, document_id)
        return out

    @app.get("/api/report")
    def get_report(format: Literal["json", "md", "csv"] = "json", include_healthy: bool = False,
                   tenant: str | None = Query(None, max_length=256), s: IntegrityService = Depends(get_svc)) -> Response:
        data = s.report(format, include_healthy=include_healthy, tenant=tenant)
        if format == "json":
            return JSONResponse(data)
        media = "text/markdown" if format == "md" else "text/csv"
        return PlainTextResponse(data, media_type=media,
                                 headers={"Content-Disposition": f'attachment; filename="rag-integrity-report.{format}"'})

    # ------------------------------------------------------------------ recommendations / blast radius / query log
    @app.get("/api/recommendations")
    def recommendations(min_severity: Sev | None = None, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.recommendations(min_severity)

    @app.post("/api/blast-radius")
    def blast(req: BlastRequest, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.blast_radius(req.scenario)

    @app.post("/api/query-log")
    def ingest_queries(req: QueryLogRequest, s: IntegrityService = Depends(get_svc)) -> dict[str, int]:
        return {"ingested": s.ingest_queries(req.queries)}

    @app.get("/api/history")
    def history(limit: int = Query(100, ge=1, le=500), s: IntegrityService = Depends(get_svc)) -> list[dict[str, Any]]:
        return s.ledger.history(limit)

    # ------------------------------------------------------------------ repairs
    @app.post("/api/repairs", status_code=201)
    def create_plan(req: PlanRequest | None = None, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        req = req or PlanRequest()
        return s.repairs.create_plan(issue_ids=req.issue_ids, min_severity=req.min_severity, tenant=req.tenant, types=req.types)

    @app.get("/api/repairs")
    def list_plans(s: IntegrityService = Depends(get_svc)) -> list[dict[str, Any]]:
        return s.ledger.list_plans()

    @app.get("/api/repairs/{plan_id}")
    def get_plan(plan_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.repairs.get(plan_id)

    @app.get("/api/repairs/{plan_id}/payload")
    def plan_payload(plan_id: str, phase: Literal["reindex"] = "reindex", s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.repairs.payload(s.repairs.get(plan_id), phase)

    @app.post("/api/repairs/{plan_id}/trigger")
    def trigger(plan_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.repairs.trigger(plan_id)

    @app.post("/api/repairs/{plan_id}/verify")
    def verify(plan_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.repairs.verify(plan_id)

    @app.post("/api/repairs/{plan_id}/approve-cleanup")
    def approve_cleanup(plan_id: str, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        return s.repairs.approve_cleanup(plan_id)

    @app.post("/api/repairs/{plan_id}/callback", include_in_schema=False)
    async def callback(plan_id: str, request: Request) -> dict[str, Any]:
        """Called by the customer's worker when it has finished; authenticated by HMAC signature, not by a session."""
        body = await request.body()

        def run() -> dict[str, Any]:
            target = svc
            if multi:
                assert state is not None and state.manager is not None and state.ledger is not None
                ws = state.ledger.workspace_of_plan(plan_id)
                if ws is None:
                    raise RepairError("Repair plan not found.", 404)
                target = state.manager.service(ws)
            assert target is not None
            return target.repairs.handle_callback(plan_id, body, request.headers.get("x-ragi-timestamp", ""),
                                                  request.headers.get("x-ragi-signature", ""))

        return await asyncio.to_thread(run)

    # ------------------------------------------------------------------ demo (single-user demo mode only)
    @app.post("/api/demo/reset")
    def demo_reset(req: DemoResetRequest | None = None, s: IntegrityService = Depends(get_svc)) -> dict[str, Any]:
        if not settings.is_demo:
            raise HTTPException(404, "Not available outside demo mode")
        s.demo_reset(seed=(req.seed if req else None))
        return {"ok": True}

    return app
