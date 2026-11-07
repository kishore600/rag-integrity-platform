"""Live mode end to end: real connector code against S3 (moto), a SQL manifest and Qdrant (local mode).

The demo world is written into those systems and the engine - now reading through S3Source,
PostgresManifest and QdrantIndex - must still find exactly the injected faults. Uses real Postgres when
RAGI_TEST_PG_URL is set, otherwise SQLite for the manifest.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from ragintegrity.config import Settings, normalize_db_url
from ragintegrity.connectors.base import ConnectorError
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.demo.seed import seed_manifest, seed_qdrant, seed_s3
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.service import IntegrityService

PG_URL = os.environ.get("RAGI_TEST_PG_URL")


@pytest.fixture()
def live(tmp_path):
    world = DemoWorld(seed=17, docs_per_tenant=30, now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        seed_s3(s3, "docs", world)
        qd = QdrantClient(":memory:")
        seed_qdrant(qd, world)
        if PG_URL:
            eng = create_engine(normalize_db_url(PG_URL), pool_size=2, max_overflow=0, connect_args={"prepare_threshold": None})
            seed_manifest(eng, world, schema="public")
            manifest_url = PG_URL
        else:
            db = tmp_path / "manifest.db"
            eng = create_engine(f"sqlite:///{db}")
            seed_manifest(eng, world)
            manifest_url = f"sqlite:///{db}"
        settings = Settings(
            _env_file=None, mode="live", database_url=f"sqlite:///{tmp_path / 'ledger.db'}", grace_minutes=0,
            s3_bucket="docs", s3_region="us-east-1", manifest_database_url=manifest_url, manifest_chunk_table="rag_chunk_manifest",
            qdrant_collections="kb_main", qdrant_check_vectors=True,
            **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()},
        )
        conns = Connectors(S3Source(settings, client=s3), PostgresManifest(settings, engine=eng), QdrantIndex(settings, client=qd))
        svc = IntegrityService(settings, Ledger(settings.database_url), conns)
        yield world, svc, eng


def found_by_doc(svc):
    out = defaultdict(set)
    issues, _ = svc.ledger.list_issues(status="open", limit=500)
    for i in issues:
        out[(i["tenant_id"], i["document_id"])].add(i["type"])
    return out


def test_live_connectors_find_exactly_the_injected_faults(live):
    world, svc, _ = live
    run = svc.run_audit()
    assert run.stats["documents_total"] >= len(world.sources)
    expected = {k: set(v["types"]) for k, v in world.faults.items()}
    assert dict(found_by_doc(svc)) == expected


def test_live_health_and_connection_status(live):
    _, svc, _ = live
    conns = {c["name"]: c for c in svc.connections()}
    assert conns["S3 source"]["ok"] and conns["Manifest (Postgres)"]["ok"] and conns["Vector index (Qdrant)"]["ok"]


def test_unconfigured_live_mode_names_each_broken_connector(tmp_path):
    settings = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{tmp_path / 'l.db'}")
    svc = IntegrityService(settings, Ledger(settings.database_url))
    by_name = {c["name"]: c for c in svc.connections()}
    assert by_name["Issue ledger"]["ok"]
    assert not by_name["S3 source"]["ok"] and "RAGI_S3_BUCKET" in by_name["S3 source"]["detail"]
    assert not by_name["Manifest (Postgres)"]["ok"] and "RAGI_MANIFEST_DATABASE_URL" in by_name["Manifest (Postgres)"]["detail"]
    assert not by_name["Vector index (Qdrant)"]["ok"] and "RAGI_QDRANT_URL" in by_name["Vector index (Qdrant)"]["detail"]
    with pytest.raises(ConnectorError):
        svc.run_audit()  # and an audit fails loudly instead of reporting a clean index
    assert svc.ledger.list_runs(limit=1)[0]["status"] == "failed"


def test_live_scoped_verification_and_inspection(live):
    world, svc, _ = live
    svc.run_audit()
    key = next(k for k, v in world.faults.items() if v["fault"] == "stale")
    view = svc.inspect(*key)
    assert view["source"]["source_hash"] and view["index"]["by_class"].get("stale")
    assert [f["type"] for f in view["findings"]] == ["stale_embedding"]


def test_live_retrieval_probe_against_qdrant(live):
    _, svc, _ = live
    svc.run_audit()
    orphan = next(i for i in svc.ledger.list_issues(type="orphan_vector", limit=5)[0])
    probe = orphan["evidence"]["retrieval_probe"]
    assert probe["reachable"] and probe["rank"] == 1 and orphan["severity"] == "critical"


def test_live_repair_loop_with_external_worker(live):
    """The 'customer worker' here fixes the real stores directly; the platform only verifies."""
    world, svc, eng = live
    svc.run_audit()
    key = next(k for k, v in world.faults.items() if v["fault"] == "partial")
    issue = svc.ledger.issues_for_document(*key)[0]
    assert issue["type"] == "partial_index"

    # worker: re-index the document into Qdrant and refresh the manifest rows
    from qdrant_client import models as qm

    from ragintegrity.demo.pipeline import build_points, make_text
    src = world.sources[key]
    pts, rows = build_points(key[0], key[1], make_text(key[1], world.versions[key]), source_hash=src.source_hash,
                             source_version=src.source_version, fp=TARGET_FP, acl_hash=world._acl(key))
    svc.connectors.index.client.upsert("kb_main", [qm.PointStruct(id=p.point_id, vector=p.vector, payload=p.payload) for p in pts])

    assert svc.run_audit().diff.resolved
    assert svc.ledger.get_issue(issue["id"])["status"] == "resolved"
