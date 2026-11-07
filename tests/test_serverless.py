"""Behaviour that only matters on serverless hosts such as Vercel."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.connectors.factory import build_connectors
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.service import IntegrityService

ROOT = Path(__file__).parent.parent


def make(tmp_path, **kw):
    settings = Settings(_env_file=None, mode="demo", database_url=f"sqlite:///{tmp_path / 's.db'}", grace_minutes=0,
                        **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()}, **kw)
    svc = IntegrityService(settings, Ledger(settings.database_url),
                           build_connectors(settings, DemoWorld(seed=5, docs_per_tenant=20)))
    return svc, settings


def test_inline_audits_never_spawn_threads(tmp_path):
    svc, settings = make(tmp_path, sync_audits=True)
    assert settings.run_audits_inline
    before = {t.name for t in threading.enumerate()}
    run_id = svc.start_audit_async(trigger="api")
    assert svc.ledger.get_run(run_id)["status"] == "completed"  # finished before returning
    assert not [t for t in threading.enumerate() if t.name.startswith("audit-") and t.name not in before]


def test_vercel_environment_implies_inline_audits(tmp_path, monkeypatch):
    _, settings = make(tmp_path)
    assert not settings.run_audits_inline
    monkeypatch.setenv("VERCEL", "1")
    assert settings.run_audits_inline


def test_api_reports_completed_for_inline_audit(tmp_path):
    svc, settings = make(tmp_path, sync_audits=True)
    with TestClient(create_app(svc, settings)) as c:
        r = c.post("/api/audits", json={})
        assert r.status_code == 202 and r.json()["status"] == "completed"
        assert c.get(f"/api/audits/{r.json()['run_id']}").json()["stats"]["documents_total"] > 0


def test_first_api_request_bootstraps_without_lifespan(tmp_path):
    """Serverless hosts may never run the ASGI lifespan: the first /api/ request must do the start-up work."""
    svc, settings = make(tmp_path)
    c = TestClient(create_app(svc, settings))  # deliberately NOT used as a context manager: no lifespan
    assert c.get("/healthz").status_code == 200
    assert svc.ledger.list_runs(limit=1) == []  # health checks stay cheap and do not trigger the audit
    ov = c.get("/api/overview").json()
    assert ov["documents"]["total"] > 0 and ov["issues"]["open"] > 0
    runs_after_first = len(svc.ledger.list_runs(limit=50))
    c.get("/api/overview")
    assert len(svc.ledger.list_runs(limit=50)) == runs_after_first  # bootstrapped once, not per request


def test_bootstrap_failure_is_a_clean_503_and_retries(tmp_path):
    svc, settings = make(tmp_path)
    calls = {"n": 0}
    real = svc.bootstrap

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database unreachable: postgresql://user:SECRET@host/db")
        real()

    svc.bootstrap = flaky  # type: ignore[method-assign]
    c = TestClient(create_app(svc, settings))
    r = c.get("/api/overview")
    assert r.status_code == 503 and "SECRET" not in r.text and "RuntimeError" in r.text  # no connection string leak
    assert c.get("/api/overview").status_code == 200  # recovered on the next request
    assert c.get("/api/auth").status_code == 200  # public endpoints never needed the ledger


def test_vercel_entrypoint_serves_the_dashboard_and_api(tmp_path, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("RAGI_DATABASE_URL", f"sqlite:///{tmp_path / 'vercel.db'}")
    monkeypatch.setenv("RAGI_MODE", "demo")
    from ragintegrity.config import get_settings

    get_settings.cache_clear()
    spec = importlib.util.spec_from_file_location("vercel_index", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        c = TestClient(mod.app)
        assert "RAG Integrity" in c.get("/").text
        assert c.get("/static/app.js").status_code == 200
        assert c.get("/api/overview").json()["demo"] is True
        run = c.post("/api/audits", json={}).json()
        assert run["status"] == "completed"
        plan = c.post("/api/repairs", json={"min_severity": "high"}).json()
        assert c.post(f"/api/repairs/{plan['id']}/trigger").json()["status"] == "triggered"
    finally:
        get_settings.cache_clear()


def test_serverless_install_is_lean():
    lines = [ln.strip().lower() for ln in (ROOT / "requirements.txt").read_text().splitlines()]
    deps = {ln.split(">=")[0].split("[")[0] for ln in lines if ln and not ln.startswith("#")}
    # the hosted product runs the real connectors, so it needs their client libraries and the vault's crypto
    assert {"fastapi", "sqlalchemy", "pydantic", "psycopg", "boto3", "qdrant-client", "cryptography"} <= deps
    # ...but nothing it does not use (the bundle must stay well under Vercel's 250 MB function limit)
    assert not deps & {"numpy", "grpcio", "pandas", "scipy", "torch", "uvicorn"}
    # starting the web app must not import the live-mode libraries (they are not installed on Vercel)
    code = ("import sys, ragintegrity.api.app as a; "
            "print(sorted(m for m in ('boto3', 'botocore', 'qdrant_client', 'grpc', 'numpy', 'uvicorn') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert out.stdout.strip() == "[]", out.stdout


def test_vercel_config_is_consistent():
    import json

    cfg = json.loads((ROOT / "vercel.json").read_text())
    # Vercel detects FastAPI and routes every path to the app. A catch-all rewrite to /api/index makes the app see
    # "/api/index" instead of the real path, so every route 404s (learned the hard way on the first deployment).
    assert "rewrites" not in cfg and "routes" not in cfg
    assert cfg["functions"]["api/index.py"]["maxDuration"] <= 60  # Hobby-plan ceiling
    assert (ROOT / "api" / "index.py").exists()
    assert "pyproject.toml" in (ROOT / ".vercelignore").read_text()  # requirements.txt is the single install source
