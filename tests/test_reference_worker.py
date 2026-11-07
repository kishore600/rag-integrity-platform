"""The whole loop on real(ish) infrastructure: platform (read-only) -> signed webhook -> reference worker
(writes to S3-sourced data, Qdrant and the SQL manifest) -> platform verifies -> approved cleanup -> verifies again."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from ragintegrity import repair as repair_module
from ragintegrity.config import Settings
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.demo.seed import seed_manifest, seed_qdrant, seed_s3
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.service import IntegrityService

WORKER_PATH = Path(__file__).parent.parent / "examples" / "reference_worker" / "worker.py"


def load_worker_module():
    spec = importlib.util.spec_from_file_location("reference_worker", WORKER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reference_worker"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    rw = load_worker_module()
    world = DemoWorld(seed=23, docs_per_tenant=25, now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        seed_s3(s3, "docs", world)
        qd = QdrantClient(":memory:")
        seed_qdrant(qd, world)
        db = tmp_path / "manifest.db"
        eng = create_engine(f"sqlite:///{db}")
        seed_manifest(eng, world)
        secret = "shared-secret"
        settings = Settings(
            _env_file=None, mode="live", database_url=f"sqlite:///{tmp_path / 'ledger.db'}", grace_minutes=0, s3_bucket="docs",
            s3_region="us-east-1", manifest_database_url=f"sqlite:///{db}", manifest_chunk_table="rag_chunk_manifest",
            qdrant_collections="kb_main", qdrant_check_vectors=True, repair_webhook_url="https://worker.example/ragi-webhook",
            repair_webhook_secret=secret, **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()},
        )
        svc = IntegrityService(settings, Ledger(settings.database_url), Connectors(
            S3Source(settings, client=s3), PostgresManifest(settings, engine=eng), QdrantIndex(settings, client=qd)))

        worker = rw.Worker(s3, "docs", qd, eng)
        worker_client = TestClient(rw.create_app(worker, secret, background=False))
        calls = []

        def fake_post(url, content=None, headers=None, timeout=None):  # route the platform's webhook into the worker app
            calls.append(url)
            return worker_client.post("/ragi-webhook", content=content, headers=headers)

        monkeypatch.setattr(repair_module.httpx, "post", fake_post)
        yield world, svc, qd, calls


def test_signed_webhook_loop_repairs_a_live_stack(stack):
    world, svc, qd, calls = stack
    svc.run_audit()
    before = svc.ledger.issue_counts()["open"]
    assert before > 0

    plan = svc.repairs.create_plan()
    plan = svc.repairs.trigger(plan["id"])  # signed POST -> reference worker adds/replaces vectors
    assert plan["status"] == "triggered" and calls

    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "cleanup_pending"  # replacements verified; removal still waits for an operator
    stale = [p for p in qd.scroll("kb_main", limit=10_000, with_payload=True)[0] if p.payload.get("source_hash") not in
             {s.source_hash for s in world.sources.values()}]
    assert stale, "superseded / orphan vectors must still exist before cleanup is approved"

    plan = svc.repairs.approve_cleanup(plan["id"])  # second signed POST: phase=cleanup with explicit point ids
    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "completed"
    svc.run_audit()
    assert svc.ledger.issue_counts()["open"] == 0
    # fixed documents are really fixed in the stores themselves
    stale_key = next(k for k, v in world.faults.items() if v["fault"] == "stale")
    assert svc.ledger.get_document(*stale_key)["status"] == "healthy"


def test_worker_rejects_unsigned_and_replayed_requests(stack):
    rw = load_worker_module()
    _, svc, _, _ = stack
    worker = rw.Worker(None, "docs", None, None)  # never reached: signature check fails first
    client = TestClient(rw.create_app(worker, "shared-secret", background=False))
    body = b'{"phase":"cleanup","cleanup":[]}'
    assert client.post("/ragi-webhook", content=body).status_code == 401
    assert client.post("/ragi-webhook", content=body, headers={
        "X-Ragi-Timestamp": "1", "X-Ragi-Signature": rw.sign("shared-secret", "1", body)}).status_code == 401  # replay: stale ts
    import time
    ts = str(int(time.time()))
    assert client.post("/ragi-webhook", content=body, headers={
        "X-Ragi-Timestamp": ts, "X-Ragi-Signature": rw.sign("other", ts, body)}).status_code == 401
    assert client.post("/ragi-webhook", content=body, headers={
        "X-Ragi-Timestamp": ts, "X-Ragi-Signature": rw.sign("shared-secret", ts, body)}).status_code == 202


def test_platform_and_worker_agree_on_the_signature_scheme(stack):
    rw = load_worker_module()
    ts, body = "1700000000", b"payload"
    assert repair_module.sign("k", ts, body) == rw.sign("k", ts, body)
