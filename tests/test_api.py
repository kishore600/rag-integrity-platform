from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.connectors.factory import build_connectors
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.repair import sign
from ragintegrity.service import IntegrityService


def make_client(tmp_path, **overrides):
    settings = Settings(
        _env_file=None, mode="demo", database_url=f"sqlite:///{tmp_path / 'api.db'}", grace_minutes=0,
        **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()}, **overrides,
    )
    svc = IntegrityService(settings, Ledger(settings.database_url),
                           build_connectors(settings, DemoWorld(seed=5, docs_per_tenant=40)))
    return TestClient(create_app(svc, settings)), svc


@pytest.fixture()
def client(tmp_path):
    with make_client(tmp_path)[0] as c:  # `with` runs the lifespan: bootstrap audit
        yield c


def test_dashboard_and_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "RAG Integrity" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/overview").headers["cache-control"] == "no-store"
    assert client.get("/healthz").json()["ok"] is True


def test_overview_issues_documents(client):
    ov = client.get("/api/overview").json()
    assert ov["demo"] and ov["issues"]["open"] > 0 and ov["documents"]["health_score"] < 100
    issues = client.get("/api/issues", params={"severity": "critical", "limit": 5}).json()
    assert issues["total"] > 0 and all(i["severity"] == "critical" for i in issues["items"])
    one = client.get(f"/api/issues/{issues['items'][0]['id']}").json()
    assert one["events"][0]["event"] == "opened"
    docs = client.get("/api/documents", params={"status": "broken", "limit": 5}).json()
    assert docs["total"] > 0
    d = docs["items"][0]
    detail = client.get("/api/document", params={"tenant": d["tenant_id"], "document_id": d["document_id"], "live": "true"}).json()
    assert detail["live"]["source"] is not None or detail["live"]["index"]["points"] > 0
    assert client.get("/api/document", params={"tenant": "x", "document_id": "nope"}).status_code == 404


def test_validation_and_unknown_resources(client):
    assert client.get("/api/issues", params={"severity": "catastrophic"}).status_code == 422
    assert client.get("/api/issues", params={"limit": 100000}).status_code == 422
    assert client.get("/api/issues/doesnotexist").status_code == 404
    assert client.get("/api/audits/doesnotexist").status_code == 404
    assert client.post("/api/issues/doesnotexist/ignore").status_code == 404
    assert client.post("/api/blast-radius", json={"scenario": {"type": "nonsense"}}).status_code == 400
    assert client.get("/api/repairs/nope").status_code == 404


def test_sql_injection_in_filters_is_inert(client):
    r = client.get("/api/issues", params={"q": "'; DROP TABLE issues; --", "tenant": "x' OR '1'='1"})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/overview").json()["issues"]["open"] > 0


def test_audit_async_and_wait(client):
    r = client.post("/api/audits", json={})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    for _ in range(50):
        run = client.get(f"/api/audits/{run_id}").json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "completed" and run["stats"]["documents_total"] > 0
    sync = client.post("/api/audits", json={"tenant": "acme", "wait": True}).json()
    assert sync["status"] == "completed" and sync["stats"]["scope"] == {"tenant": "acme"}
    assert any(a["id"] == run_id for a in client.get("/api/audits").json())


def test_concurrent_audit_returns_409(client, tmp_path):
    c, svc = make_client(tmp_path)
    assert svc._lock.acquire(blocking=False)
    try:
        assert c.post("/api/audits", json={}).status_code == 409
    finally:
        svc._lock.release()


def test_ignore_and_reopen(client):
    issue = client.get("/api/issues", params={"limit": 1}).json()["items"][0]
    assert client.post(f"/api/issues/{issue['id']}/ignore", json={"reason": "accepted risk"}).json() == {"ok": True}
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "ignored"
    assert client.post(f"/api/issues/{issue['id']}/reopen").json() == {"ok": True}
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "open"


def test_report_formats(client):
    md = client.get("/api/report", params={"format": "md"})
    assert md.headers["content-type"].startswith("text/markdown") and "attachment" in md.headers["content-disposition"]
    assert client.get("/api/report", params={"format": "csv"}).text.startswith("tenant_id,document_id")
    assert client.get("/api/report").json()["documents"]


def test_repair_flow_over_http(client):
    plan = client.post("/api/repairs", json={"min_severity": "high"}).json()
    assert plan["status"] == "draft"
    payload = client.get(f"/api/repairs/{plan['id']}/payload").json()
    assert payload["event"] == "repair.requested" and payload["items"] and payload["safety"]["delete_policy"] == "never_before_verified"
    assert client.post(f"/api/repairs/{plan['id']}/verify").status_code == 409  # not triggered yet
    assert client.post(f"/api/repairs/{plan['id']}/trigger").json()["status"] == "triggered"
    verified = client.post(f"/api/repairs/{plan['id']}/verify").json()
    assert verified["status"] in ("cleanup_pending", "completed")
    if verified["status"] == "cleanup_pending":
        assert client.post(f"/api/repairs/{plan['id']}/approve-cleanup").json()["status"] == "cleanup_triggered"
        assert client.post(f"/api/repairs/{plan['id']}/verify").json()["status"] == "completed"
    assert any(p["id"] == plan["id"] for p in client.get("/api/repairs").json())
    assert client.get("/api/history").json()


def test_impact_endpoints_and_query_log(client):
    rec = client.get("/api/recommendations").json()
    assert rec["summary"]["documents_affected"] > 0
    n = client.post("/api/query-log", json={"queries": [
        {"tenant_id": "acme", "retrieved_doc_ids": ["a.md", "b.md"], "query_text": "secret question"},
        {"tenant_id": "acme", "retrieved_doc_ids": []},  # ignored: nothing retrieved
    ]}).json()
    assert n == {"ingested": 1}
    blast = client.post("/api/blast-radius", json={"scenario": {"type": "ingestion_failure", "since": "2020-01-01T00:00:00Z"}}).json()
    assert blast["documents"]["affected"] > 0
    assert client.post("/api/query-log", json={"queries": [{}] * 6000}).status_code == 422  # bounded input


def test_query_text_is_hashed_not_stored(client, tmp_path):
    c, svc = make_client(tmp_path)
    with c:
        c.post("/api/query-log", json={"queries": [{"tenant_id": "acme", "retrieved_doc_ids": ["x"], "query_text": "my confidential question"}]})
        stored = json.dumps(svc.ledger.queries_since(1), default=str)
        assert "confidential" not in stored and "query_hash" in stored


def test_api_key_enforcement(tmp_path):
    c, _ = make_client(tmp_path, api_key="s3cret-key")
    with c:
        assert c.get("/healthz").status_code == 200  # public
        assert c.get("/api/auth").json() == {"required": True}
        assert c.get("/").status_code == 200  # the shell is public, the data is not
        assert c.get("/api/overview").status_code == 401
        assert c.get("/api/overview", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/api/overview", headers={"X-API-Key": "s3cret-key"}).status_code == 200
        assert c.get("/api/overview", headers={"Authorization": "Bearer s3cret-key"}).status_code == 200
        assert c.post("/api/audits", json={}).status_code == 401
        assert c.post("/api/repairs", json={}).status_code == 401
        assert c.post("/api/demo/reset", json={}).status_code == 401


def test_worker_callback_requires_valid_signature(tmp_path):
    c, svc = make_client(tmp_path, repair_webhook_secret="whsec")
    with c:
        plan = c.post("/api/repairs", json={"types": ["stale_embedding"]}).json()
        c.post(f"/api/repairs/{plan['id']}/trigger")
        body = b'{"done": true}'
        assert c.post(f"/api/repairs/{plan['id']}/callback", content=body).status_code == 401
        ts = str(int(time.time()))
        bad = c.post(f"/api/repairs/{plan['id']}/callback", content=body,
                     headers={"X-Ragi-Timestamp": ts, "X-Ragi-Signature": sign("wrong", ts, body)})
        assert bad.status_code == 401
        old = str(int(time.time()) - 3600)
        replay = c.post(f"/api/repairs/{plan['id']}/callback", content=body,
                        headers={"X-Ragi-Timestamp": old, "X-Ragi-Signature": sign("whsec", old, body)})
        assert replay.status_code == 401  # stale timestamp: replay protection
        ok = c.post(f"/api/repairs/{plan['id']}/callback", content=body,
                    headers={"X-Ragi-Timestamp": ts, "X-Ragi-Signature": sign("whsec", ts, body)})
        assert ok.status_code == 200 and ok.json()["status"] in ("cleanup_pending", "completed")


def test_demo_reset_endpoint_hidden_in_live_mode(tmp_path):
    settings = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{tmp_path / 'l.db'}")
    svc = IntegrityService(settings, Ledger(settings.database_url), connectors=build_connectors(
        Settings(_env_file=None, mode="demo"), DemoWorld(seed=1, docs_per_tenant=5)))
    with TestClient(create_app(svc, settings)) as c:
        assert c.post("/api/demo/reset", json={}).status_code == 404


def test_scheduler_loop_runs_audits_and_survives_failures(tmp_path):
    import asyncio

    from ragintegrity.api.app import scheduler_loop

    _, svc = make_client(tmp_path)
    svc.bootstrap()

    async def run_for(seconds: float) -> None:
        task = asyncio.create_task(scheduler_loop(svc, 0.05))
        await asyncio.sleep(seconds)
        task.cancel()

    asyncio.run(run_for(0.6))
    scheduled = [r for r in svc.ledger.list_runs(limit=50) if r["trigger"] == "schedule"]
    assert scheduled and all(r["status"] == "completed" for r in scheduled)

    svc.connectors.world.sources = None  # sabotage: the loop must log the failure and keep going
    asyncio.run(run_for(0.3))
    assert any(r["status"] == "failed" for r in svc.ledger.list_runs(limit=50))
