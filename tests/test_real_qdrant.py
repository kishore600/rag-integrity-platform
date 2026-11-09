"""The Qdrant connector against a REAL Qdrant server over HTTP.

Skipped unless RAGI_TEST_QDRANT_URL is set (and RAGI_TEST_QDRANT_KEY if the server enforces an API key):
    RAGI_TEST_QDRANT_URL=http://127.0.0.1:6333 RAGI_TEST_QDRANT_KEY=... pytest tests/test_real_qdrant.py
These cover what Qdrant's in-process local mode cannot: URL handling, API-key auth, JSON filter serialisation, paging.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from qdrant_client import QdrantClient

from ragintegrity.config import Settings
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.demo.seed import seed_qdrant
from ragintegrity.demo.world import DemoWorld
from ragintegrity.models import Scope

URL = os.environ.get("RAGI_TEST_QDRANT_URL")
KEY = os.environ.get("RAGI_TEST_QDRANT_KEY")
pytestmark = pytest.mark.skipif(not URL, reason="RAGI_TEST_QDRANT_URL not set")


def settings(**kw) -> Settings:
    return Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY, qdrant_collections="kb_main", qdrant_page_size=100, **kw)


@pytest.fixture(scope="module")
def world():
    w = DemoWorld(seed=41, docs_per_tenant=30, now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    seed_qdrant(QdrantClient(url=URL, api_key=KEY, timeout=30), w)
    return w


def test_full_scan_pages_through_every_point(world):
    pts = list(QdrantIndex(settings()).scan())
    assert len(pts) == len(world.points) and len(pts) > 100  # more than one page of 100: paging works
    assert {p.point_id for p in pts} == set(world.points)
    assert all(p.document_id and p.tenant_id and p.source_hash for p in pts)


def test_scoped_scans_use_real_server_side_filters(world):
    idx = QdrantIndex(settings())
    tenant = next(iter(world.tenants))
    mine = list(idx.scan(Scope(tenant=tenant)))
    assert mine and {p.tenant_id for p in mine} == {tenant}
    key = next(k for k in world.sources if k[0] == tenant)
    one = list(idx.scan(Scope(keys=frozenset({key}))))
    assert one and {(p.tenant_id, p.document_id) for p in one} == {key}
    assert list(idx.scan(Scope(keys=frozenset({("nobody", "nothing.md")})))) == []


def test_a_long_document_list_is_read_in_filtered_batches_without_duplicates(world, monkeypatch):
    monkeypatch.setattr("ragintegrity.connectors.qdrant.FILTER_BATCH", 2)  # 5 documents -> 3 real filtered scroll passes
    keys = frozenset(list(world.sources)[:5])
    pts = list(QdrantIndex(settings()).scan(Scope(keys=keys)))
    ids = [p.point_id for p in pts]
    expected = {pid for pid, sp in world.points.items() if (sp.payload["tenant_id"], sp.payload["document_id"]) in keys}
    assert expected and len(ids) == len(set(ids)) and set(ids) == expected


def test_isolation_summary_and_drill_behave_the_same_on_a_real_server(world):
    from ragintegrity.demo.world import TARGET_FP, DemoIndex, DemoManifest, DemoSource
    from ragintegrity.engine.audit import AuditOptions, run_reconciliation
    from ragintegrity.engine.drills import DRILL_TENANT, drill_tenant_mismatch

    opts = AuditOptions(target=TARGET_FP, check_vectors=True, probe=True, now=datetime(2026, 11, 7, tzinfo=timezone.utc),
                        grace_minutes=10)
    real = run_reconciliation(DemoSource(world), DemoManifest(world), QdrantIndex(settings()), opts)
    memory = run_reconciliation(DemoSource(world), DemoManifest(world), DemoIndex(world), opts)
    keys = ("status", "tenants", "points_checked", "leaking_documents", "permission_mismatch_documents", "permissions_recorded")
    assert {k: real.stats["isolation"]["overall"][k] for k in keys} == {k: memory.stats["isolation"]["overall"][k] for k in keys}
    assert real.stats["isolation"]["overall"]["points_checked"] == len(world.points)

    healthy = next(s for s in real.summaries if s.status == "healthy" and s.indexed_chunks)
    out = drill_tenant_mismatch(DemoSource(world), DemoManifest(world), QdrantIndex(settings()), opts, healthy.key)
    assert out["caught"] and out["document"]["points"] > 0
    assert any(f["type"] == "tenant_mismatch" and f["tenant_id"] == DRILL_TENANT for f in out["findings"])
    after = list(QdrantIndex(settings()).scan(Scope(keys=frozenset({healthy.key}))))
    assert after and {p.tenant_id for p in after} == {healthy.tenant_id}  # the real vectors still carry their real tenant


def test_empty_embeddings_are_found_when_vectors_are_fetched(world):
    idx = QdrantIndex(settings())
    bad = [p for p in idx.scan(with_vectors=True) if p.vector_checked and not p.vector_ok]
    expected = {pid for pid, sp in world.points.items() if not any(sp.vector)}
    assert expected and {p.point_id for p in bad} == expected


def test_retrieval_probe_ranks_the_chunk_first_and_respects_the_tenant_filter(world):
    idx = QdrantIndex(settings())
    pid, sp = next(iter(world.points.items()))
    tenant = sp.payload["tenant_id"]
    hits = idx.probe("kb_main", pid, tenant, 5)
    assert hits and hits[0][0] == pid and hits[0][2] == sp.payload["document_id"]
    other_tenants = {p.point_id for p in idx.scan() if p.tenant_id != tenant}
    assert not other_tenants & {h[0] for h in hits}  # another tenant's vectors never surface for this tenant's query
    assert idx.probe("kb_main", "00000000-0000-0000-0000-000000000000", tenant, 5) is None


def test_diagnostics_describe_a_healthy_collection(world):
    checks = {c["name"]: c for c in QdrantIndex(settings()).diagnose()}
    assert checks["Qdrant reachable"]["status"] == "ok" and checks["Collections"]["status"] == "ok"
    assert checks["Payload of kb_main"]["status"] == "ok" and "source_hash" in checks["Payload of kb_main"]["detail"]
    assert QdrantIndex(settings()).vector_sizes() == {"kb_main": 16}
    assert QdrantIndex(settings()).health().ok


def test_a_missing_collection_is_named(world):
    checks = QdrantIndex(Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY,
                                  qdrant_collections="kb_main,does_not_exist")).diagnose()
    assert any(c["status"] == "fail" and "does_not_exist" in c["detail"] for c in checks)


@pytest.mark.skipif(not KEY, reason="the server is not enforcing an API key")
def test_a_wrong_api_key_gets_a_specific_message():
    checks = QdrantIndex(Settings(_env_file=None, qdrant_url=URL, qdrant_api_key="wrong-key", qdrant_collections="kb_main")).diagnose()
    assert checks[0]["status"] == "fail" and "API key" in checks[0]["detail"]
    no_key = QdrantIndex(Settings(_env_file=None, qdrant_url=URL, qdrant_collections="kb_main")).diagnose()
    assert no_key[0]["status"] == "fail" and "API key" in no_key[0]["detail"]


def test_unreachable_server_is_a_quick_clean_failure():
    checks = QdrantIndex(Settings(_env_file=None, qdrant_url="http://127.0.0.1:1", qdrant_collections="kb_main")).diagnose()
    assert checks[0]["status"] == "fail" and checks[0]["name"] == "Qdrant reachable"
