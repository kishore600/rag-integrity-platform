"""The multi-user product end to end with the REAL connectors, configured the way a user would: through the settings API.

Needs a real Postgres for the manifest (RAGI_TEST_PG_URL; the app refuses non-Postgres manifests). S3 is moto, Qdrant is
its local mode behind the real client class. Private hosts are allowed here only because the test infrastructure is local.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings, normalize_db_url
from ragintegrity.demo.seed import seed_manifest, seed_qdrant, seed_s3
from ragintegrity.demo.world import TARGET_FP, DemoWorld

PG_URL = os.environ.get("RAGI_TEST_PG_URL")
# With RAGI_TEST_QDRANT_URL (+ RAGI_TEST_QDRANT_KEY) the test talks to a REAL Qdrant server over HTTP; without it, Qdrant's local mode.
QDRANT_URL = os.environ.get("RAGI_TEST_QDRANT_URL")
QDRANT_KEY = os.environ.get("RAGI_TEST_QDRANT_KEY")
pytestmark = pytest.mark.skipif(not PG_URL, reason="RAGI_TEST_PG_URL not set")
KEY, PW = "k" * 40, "a-long-unusual-passphrase"
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    world = DemoWorld(seed=31, docs_per_tenant=25, now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        seed_s3(s3, "customer-docs", world)
        if QDRANT_URL:
            qd = QdrantClient(url=QDRANT_URL, api_key=QDRANT_KEY, timeout=30)
        else:
            qd = QdrantClient(":memory:")
            monkeypatch.setattr("qdrant_client.QdrantClient", lambda **kw: qd)  # the real client class, backed by local storage
        seed_qdrant(qd, world)
        eng = create_engine(normalize_db_url(PG_URL), pool_size=2, max_overflow=0, connect_args={"prepare_threshold": None})
        seed_manifest(eng, world, schema="public")
        settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'app.db'}", secret_key=KEY,
                            allow_private_hosts=True)
        with TestClient(create_app(settings=settings)) as client:
            yield client, world


def signup(client, email="owner@example.com"):
    assert client.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    client.headers.update(ORIGIN)


def configure(client, **overrides):
    s3 = {"bucket": "customer-docs", "region": "us-east-1", "access_key_id": "AKIAFAKEKEY", "secret_access_key": "fakesecret",
          "hash_mode": "metadata"}
    manifest = {"database_url": PG_URL, "schema": "public", "chunk_table": "rag_chunk_manifest"}
    qdrant = {"url": QDRANT_URL or "http://127.0.0.1:6333", "collections": "kb_main", "check_vectors": True}
    if QDRANT_KEY:
        qdrant["api_key"] = QDRANT_KEY
    pipeline = {k: v for k, v in TARGET_FP.to_dict().items()}
    for kind, values in (("s3", s3), ("manifest", manifest), ("qdrant", qdrant), ("pipeline", pipeline), ("policy", {"grace_minutes": 0})):
        r = client.put(f"/api/settings/{kind}", json={"values": {**values, **overrides.get(kind, {})}})
        assert r.status_code == 200, (kind, r.text)
    return r.json()


def issues_by_doc(client):
    out = defaultdict(set)
    for i in client.get("/api/issues", params={"status": "all", "limit": 500}).json()["items"]:
        out[(i["tenant_id"], i["document_id"])].add(i["type"])
    return dict(out)


def test_configure_test_and_audit_real_connectors_through_the_api(stack):
    client, world = stack
    signup(client)
    assert client.get("/api/session").json()["ready"] is False
    final = configure(client)
    assert final["ready"] is True and final["missing"] == []

    # each connector reports specific, truthful diagnostics
    s3 = client.post("/api/settings/s3/test").json()
    assert s3["ok"] and {c["name"]: c["status"] for c in s3["checks"]} == {
        "Bucket reachable": "ok", "Key pattern": "ok", "Content hashes": "ok"}
    manifest = client.post("/api/settings/manifest/test").json()
    names = {c["name"]: c["status"] for c in manifest["checks"]}
    assert manifest["ok"] and names["Database reachable"] == "ok" and names["Manifest table"] == "ok" and names["Chunk manifest"] == "ok"
    qdrant = client.post("/api/settings/qdrant/test").json()
    qnames = {c["name"]: c["status"] for c in qdrant["checks"]}
    assert qdrant["ok"] and qnames["Qdrant reachable"] == "ok" and qnames["Payload of kb_main"] == "ok"
    saved = {k["kind"]: k["last_test"] for k in client.get("/api/settings").json()["kinds"]}
    assert saved["s3"]["ok"] and saved["manifest"]["ok"] and saved["qdrant"]["ok"]  # the last test result is remembered

    # an audit reads the user's real data and finds exactly the faults that were planted
    run = client.post("/api/audits", json={"wait": True}).json()
    assert run["status"] == "completed" and run["stats"]["documents_total"] >= len(world.sources)
    assert issues_by_doc(client) == {k: set(v["types"]) for k, v in world.faults.items()}
    ov = client.get("/api/overview").json()
    assert ov["documents"]["health_score"] < 100 and ov["issues"]["open"] > 0

    # drill-down uses the live connectors too
    key = next(k for k, v in world.faults.items() if v["fault"] == "stale")
    live = client.get("/api/document", params={"tenant": key[0], "document_id": key[1], "live": True}).json()["live"]
    assert live["source"]["source_hash"] and [f["type"] for f in live["findings"]] == ["stale_embedding"]

    # automation: an API key can run the same audit with no browser session
    token = client.post("/api/keys", json={"name": "ci"}).json()["token"]
    bot = TestClient(client.app)
    again = bot.post("/api/audits", json={"wait": True}, headers={"Authorization": f"Bearer {token}"}).json()
    assert again["status"] == "completed" and again["stats"]["diff"]["opened"] == 0  # idempotent: same issues, none duplicated

    # a second user has their own empty workspace and sees none of it
    other = TestClient(client.app)
    signup(other, "someone-else@example.com")
    assert other.get("/api/issues", params={"status": "all"}).json()["total"] == 0
    assert other.get("/api/documents").json()["total"] == 0
    assert other.post("/api/audits", json={}).status_code == 409  # not set up yet: their own workspace has no connections


def test_changing_a_connection_takes_effect_on_the_next_audit(stack):
    client, world = stack
    signup(client)
    configure(client)
    assert client.post("/api/audits", json={"wait": True}).status_code == 202
    bad = client.put("/api/settings/s3", json={"values": {"bucket": "a-bucket-that-does-not-exist"}})
    assert bad.status_code == 200
    r = client.post("/api/audits", json={"wait": True})
    # the user gets a specific, safe message instead of a stack trace...
    assert r.status_code == 502 and r.json()["upstream"] is True and "bucket does not exist" in r.json()["detail"]
    last = client.get("/api/audits").json()[0]  # ...and the failed run is on record with the same explanation
    assert last["status"] == "failed" and "bucket does not exist" in last["error"]
    t = client.post("/api/settings/s3/test").json()
    assert t["ok"] is False and "does not exist" in t["checks"][0]["detail"]
    client.put("/api/settings/s3", json={"values": {"bucket": "customer-docs"}})  # fix it: the next audit just works
    assert client.post("/api/settings/s3/test").json()["ok"] is True
    ok = client.post("/api/audits", json={"wait": True})
    assert ok.status_code == 202 and ok.json()["status"] == "completed"


def test_wrong_manifest_table_and_missing_payload_fields_are_diagnosed(stack):
    client, _ = stack
    signup(client)
    configure(client)
    client.put("/api/settings/manifest", json={"values": {"table": "no_such_table"}})
    t = client.post("/api/settings/manifest/test").json()
    assert t["ok"] is False and any(c["status"] == "fail" and "no_such_table" in c["detail"] for c in t["checks"])
    client.put("/api/settings/manifest", json={"values": {"table": "rag_document_manifest", "column_map": '{"document_id": "missing_col"}'}})
    t = client.post("/api/settings/manifest/test").json()
    assert t["ok"] is False and any("document_id" in c["detail"] for c in t["checks"])
    client.put("/api/settings/qdrant", json={"values": {"collections": "kb_main,ghost"}})
    t = client.post("/api/settings/qdrant/test").json()
    assert t["ok"] is False and any("ghost" in c["detail"] for c in t["checks"])


def test_unreachable_qdrant_reports_a_clean_failure(tmp_path):
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'a.db'}", secret_key=KEY, allow_private_hosts=True)
    with TestClient(create_app(settings=settings)) as c:
        signup(c)
        c.put("/api/settings/qdrant", json={"values": {"url": "http://127.0.0.1:1"}})  # nothing listens here
        t = c.post("/api/settings/qdrant/test").json()
        assert t["ok"] is False and t["checks"][0]["status"] == "fail"
        assert "refused" in t["checks"][0]["detail"].lower() or "timed out" in t["checks"][0]["detail"].lower() or "Connect" in t["checks"][0]["detail"]
