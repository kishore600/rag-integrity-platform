"""HTTP API + dashboard."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Settings, get_settings
from ..connectors.base import ConnectorError
from ..models import Scope
from ..repair import RepairError
from ..service import AuditBusy, IntegrityService

log = logging.getLogger("ragintegrity.api")
STATIC = Path(__file__).parent / "static"
Sev = Literal["critical", "high", "medium", "low", "info"]


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


def create_app(service: IntegrityService | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or (service.settings if service else get_settings())
    svc = service or IntegrityService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks: list[asyncio.Task] = []
        try:
            await asyncio.to_thread(svc.bootstrap)
        except Exception:
            log.exception("bootstrap audit failed")
        if settings.audit_interval_minutes > 0:
            tasks.append(asyncio.create_task(scheduler_loop(svc, settings.audit_interval_minutes * 60)))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="RAG Integrity", version=__version__, lifespan=lifespan,
                  description="Know when your RAG index is wrong - before your users do.")
    app.state.service = svc

    # ------------------------------------------------------------------ cross-cutting
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

    @app.exception_handler(AuditBusy)
    async def _busy(_: Request, exc: AuditBusy):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(RepairError)
    async def _repair(_: Request, exc: RepairError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ConnectorError)
    async def _connector(_: Request, exc: ConnectorError):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(ValueError)
    async def _value(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def require_key(request: Request) -> None:
        expected = settings.api_key
        if not expected:
            return
        supplied = request.headers.get("x-api-key") or ""
        auth = request.headers.get("authorization") or ""
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:]
        if not supplied or not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "Missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})

    auth = [Depends(require_key)]

    # ------------------------------------------------------------------ public
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, Any]:
        ok, detail = svc.ledger.ping()
        return {"ok": ok, "version": __version__, "mode": settings.mode, "ledger": detail}

    @app.get("/api/auth", include_in_schema=False)
    def auth_info() -> dict[str, bool]:
        return {"required": bool(settings.api_key)}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------------------ overview / connections
    @app.get("/api/overview", dependencies=auth)
    def overview() -> dict[str, Any]:
        return svc.overview()

    @app.get("/api/connections", dependencies=auth)
    def connections() -> list[dict[str, Any]]:
        return svc.connections()

    # ------------------------------------------------------------------ audits
    @app.post("/api/audits", status_code=202, dependencies=auth)
    def start_audit(req: AuditRequest | None = None) -> dict[str, Any]:
        req = req or AuditRequest()
        scope = None
        if req.tenant or req.documents:
            keys = frozenset((d.tenant_id, d.document_id) for d in req.documents) if req.documents else None
            scope = Scope(tenant=req.tenant, keys=keys)
        if req.wait:
            r = svc.run_audit(scope=scope, trigger="api", probe=req.probe)
            return {"run_id": r.run_id, "status": "completed", "stats": r.stats}
        return {"run_id": svc.start_audit_async(scope=scope, trigger="api", probe=req.probe), "status": "running"}

    @app.get("/api/audits", dependencies=auth)
    def list_audits(limit: int = Query(30, ge=1, le=200)) -> list[dict[str, Any]]:
        return svc.ledger.list_runs(limit=limit)

    @app.get("/api/audits/{run_id}", dependencies=auth)
    def get_audit(run_id: str) -> dict[str, Any]:
        run = svc.ledger.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Audit run not found")
        return run

    # ------------------------------------------------------------------ issues
    @app.get("/api/issues", dependencies=auth)
    def list_issues(
        status: str | None = Query("open", pattern="^(open|resolved|ignored|all)$"),
        severity: Sev | None = None, type: str | None = Query(None, max_length=40), tenant: str | None = Query(None, max_length=256),
        q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        rows, total = svc.ledger.list_issues(status=status, severity=severity, type=type, tenant=tenant, q=q,
                                             limit=limit, offset=offset)
        return {"total": total, "items": rows}

    @app.get("/api/issues/{issue_id}", dependencies=auth)
    def get_issue(issue_id: str) -> dict[str, Any]:
        issue = svc.ledger.get_issue(issue_id)
        if issue is None:
            raise HTTPException(404, "Issue not found")
        return {**issue, "events": svc.ledger.issue_events(issue_id)}

    @app.post("/api/issues/{issue_id}/ignore", dependencies=auth)
    def ignore_issue(issue_id: str, req: IgnoreRequest | None = None) -> dict[str, bool]:
        if not svc.ledger.set_issue_status(issue_id, "ignored", (req.reason if req else None)):
            raise HTTPException(404, "Issue not found")
        return {"ok": True}

    @app.post("/api/issues/{issue_id}/reopen", dependencies=auth)
    def reopen_issue(issue_id: str) -> dict[str, bool]:
        if not svc.ledger.set_issue_status(issue_id, "open"):
            raise HTTPException(404, "Issue not found")
        return {"ok": True}

    # ------------------------------------------------------------------ documents
    @app.get("/api/documents", dependencies=auth)
    def list_documents(
        status: str | None = Query(None, pattern="^(healthy|degraded|broken|pending|orphaned|all)$"),
        tenant: str | None = Query(None, max_length=256), q: str | None = Query(None, max_length=200),
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        rows, total = svc.ledger.list_documents(status=status, tenant=tenant, q=q, limit=limit, offset=offset)
        return {"total": total, "items": rows}

    @app.get("/api/document", dependencies=auth)
    def get_document(tenant: str = Query(max_length=256), document_id: str = Query(max_length=2048), live: bool = False) -> dict[str, Any]:
        doc = svc.ledger.get_document(tenant, document_id)
        issues = svc.ledger.issues_for_document(tenant, document_id)
        if doc is None and not issues:
            raise HTTPException(404, "Document not found")
        out: dict[str, Any] = {"document": doc, "issues": issues}
        if live:
            out["live"] = svc.inspect(tenant, document_id)
        return out

    @app.get("/api/report", dependencies=auth)
    def get_report(format: Literal["json", "md", "csv"] = "json", include_healthy: bool = False,
                   tenant: str | None = Query(None, max_length=256)) -> Response:
        data = svc.report(format, include_healthy=include_healthy, tenant=tenant)
        if format == "json":
            return JSONResponse(data)
        media = "text/markdown" if format == "md" else "text/csv"
        return PlainTextResponse(data, media_type=media,
                                 headers={"Content-Disposition": f'attachment; filename="rag-integrity-report.{format}"'})

    # ------------------------------------------------------------------ recommendations / blast radius / query log
    @app.get("/api/recommendations", dependencies=auth)
    def recommendations(min_severity: Sev | None = None) -> dict[str, Any]:
        return svc.recommendations(min_severity)

    @app.post("/api/blast-radius", dependencies=auth)
    def blast(req: BlastRequest) -> dict[str, Any]:
        return svc.blast_radius(req.scenario)

    @app.post("/api/query-log", dependencies=auth)
    def ingest_queries(req: QueryLogRequest) -> dict[str, int]:
        return {"ingested": svc.ingest_queries(req.queries)}

    @app.get("/api/history", dependencies=auth)
    def history(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return svc.ledger.history(limit)

    # ------------------------------------------------------------------ repairs
    @app.post("/api/repairs", status_code=201, dependencies=auth)
    def create_plan(req: PlanRequest | None = None) -> dict[str, Any]:
        req = req or PlanRequest()
        return svc.repairs.create_plan(issue_ids=req.issue_ids, min_severity=req.min_severity, tenant=req.tenant, types=req.types)

    @app.get("/api/repairs", dependencies=auth)
    def list_plans() -> list[dict[str, Any]]:
        return svc.ledger.list_plans()

    @app.get("/api/repairs/{plan_id}", dependencies=auth)
    def get_plan(plan_id: str) -> dict[str, Any]:
        return svc.repairs.get(plan_id)

    @app.get("/api/repairs/{plan_id}/payload", dependencies=auth)
    def plan_payload(plan_id: str, phase: Literal["reindex"] = "reindex") -> dict[str, Any]:
        return svc.repairs.payload(svc.repairs.get(plan_id), phase)

    @app.post("/api/repairs/{plan_id}/trigger", dependencies=auth)
    def trigger(plan_id: str) -> dict[str, Any]:
        return svc.repairs.trigger(plan_id)

    @app.post("/api/repairs/{plan_id}/verify", dependencies=auth)
    def verify(plan_id: str) -> dict[str, Any]:
        return svc.repairs.verify(plan_id)

    @app.post("/api/repairs/{plan_id}/approve-cleanup", dependencies=auth)
    def approve_cleanup(plan_id: str) -> dict[str, Any]:
        return svc.repairs.approve_cleanup(plan_id)

    @app.post("/api/repairs/{plan_id}/callback", include_in_schema=False)
    async def callback(plan_id: str, request: Request) -> dict[str, Any]:
        """Called by the customer's worker when it has finished; authenticated by HMAC signature, not the API key."""
        body = await request.body()
        return await asyncio.to_thread(
            svc.repairs.handle_callback, plan_id, body, request.headers.get("x-ragi-timestamp", ""),
            request.headers.get("x-ragi-signature", ""))

    # ------------------------------------------------------------------ demo
    @app.post("/api/demo/reset", dependencies=auth)
    def demo_reset(req: DemoResetRequest | None = None) -> dict[str, Any]:
        if not settings.is_demo:
            raise HTTPException(404, "Not available outside demo mode")
        svc.demo_reset(seed=(req.seed if req else None))
        return {"ok": True}

    return app
