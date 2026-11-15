"""Feature 4, deletion and retrieval verification: a document is deleted from the source; is it really gone?

The failure this guards against: a confidential file is deleted from S3, its vectors stay in Qdrant, and a user's search still
returns its text. Each test is one version of that story, from the clean deletion to the leak that a search proves.
"""

from __future__ import annotations

import os

import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from ragintegrity.config import Settings
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.engine.deletions import verify_deletions
from ragintegrity.ledger import Ledger
from ragintegrity.models import Fingerprint, IndexedChunk, ManifestRow, SourceDoc
from ragintegrity.service import AuditBusy, IntegrityService
from tests.test_source_only import FakeManifest, FakeSource

SECRET = "confidential_policy.pdf"
KEEP = "handbook.pdf"
T = "default"


def src(doc, tenant=T) -> SourceDoc:
    return SourceDoc(tenant, doc, f"s3://b/{doc}", source_hash=f"h-{doc}", size_bytes=1)


def row(doc, status="success", n=12, tenant=T) -> ManifestRow:
    return ManifestRow(tenant, doc, source_uri=f"s3://b/{doc}", source_hash=f"h-{doc}", processing_status=status,
                       expected_chunk_count=n, indexed_chunk_count=n)


RAW: dict[str, object] = {}  # point id -> the document value the index returns for a hit (may be a number)


def pt(doc, k, *, tenant=T, coll="c", raw_doc=None) -> IndexedChunk:
    if raw_doc is not None:
        RAW[f"{doc}-{k}"] = raw_doc
    return IndexedChunk(coll, f"{doc}-{k}", tenant, doc, chunk_id=f"{doc}#{k}", chunk_index=k, source_hash=f"h-{doc}",
                        fingerprint=Fingerprint(), present_fields=frozenset({"document_id", "source_hash"}))


class SearchIndex:
    """An index that answers searches: querying with a point returns the points of its own document first (they are the most
    similar), then the rest. ``searchable=False`` models content that is present but never ranks."""

    def __init__(self, points, *, searchable=True, probe_error=None):
        self.points, self.searchable, self.probe_error, self.probes = list(points), searchable, probe_error, []
        self.deadline = None

    def collections(self):
        return sorted({p.collection for p in self.points}) or ["c"]

    def vector_sizes(self):
        return {c: 3 for c in self.collections()}

    def scan(self, scope=None, with_vectors=False):
        return iter(p for p in self.points if scope is None or scope.is_full or scope.matches((p.tenant_id or T, p.document_id)))

    def probe(self, collection, point_id, tenant_id, top_k):
        self.probes.append(point_id)
        if self.probe_error is not None:
            raise self.probe_error
        me = next((p for p in self.points if p.point_id == point_id), None)
        if me is None:
            return None
        pool = [p for p in self.points if tenant_id is None or p.tenant_id == tenant_id]
        same = [p for p in pool if p.document_id == me.document_id] if self.searchable else []
        rest = [p for p in pool if p.document_id != me.document_id]
        return [(p.point_id, 1.0 - 0.01 * i, RAW.get(p.point_id, p.document_id)) for i, p in enumerate((same + rest)[:top_k])]


def world(*, secret_points=12, status="success", searchable=True, **kw):
    points = [pt(KEEP, k) for k in range(6)] + [pt(SECRET, k) for k in range(secret_points)]
    return (FakeSource([src(KEEP)]), FakeManifest([row(KEEP, n=6), row(SECRET, status=status, n=12)]),
            SearchIndex(points, searchable=searchable, **kw))


def verify(source, manifest, index, candidates=None, **kw):
    opts = AuditOptions(probe=False, required_fields=["document_id"])
    return verify_deletions(source, manifest, index, opts, candidates or {(T, SECRET): "it was in the source at the last audit and is gone now"}, **kw)


def check(row, name):
    return next(c for c in row["checks"] if c["check"] == name)


# ------------------------------------------------------------------------------------- the story from the feature description
def test_deleted_from_the_source_but_still_in_the_index_and_still_returned_by_a_search():
    report, result, scope = verify(*world())
    [doc] = report["documents"]
    assert doc["verdict"] == "deletion_mismatch" and doc["title"] == "Deletion mismatch"
    assert (check(doc, "Source document")["result"], check(doc, "Source document")["status"]) == ("Deleted", "ok")
    assert (check(doc, "Manifest status")["result"], check(doc, "Manifest status")["status"]) == ("success", "mismatch")  # still believed indexed
    assert (check(doc, "Vector chunks found")["result"], check(doc, "Vector chunks found")["status"]) == (12, "mismatch")
    test = check(doc, "Retrieval test")
    assert test["status"] == "mismatch" and "matching chunk(s) returned (best rank 1)" in test["result"]
    assert doc["retrieval"]["reachable"] is True and doc["retrieval"]["queries"] == 3 and doc["retrieval"]["returned_chunks"] >= 10
    assert "Review the 12 remaining vector(s)" in doc["recommended_action"] and "approved cleanup" in doc["recommended_action"]
    # the evidence is recorded with the issue, and a confirmed leak is critical
    [f] = result.findings
    assert f.type.value == "orphan_vector" and f.severity.value == "critical" and "Confirmed:" in f.detail
    assert f.evidence["retrieval_probe"]["reachable"] is True and f.evidence["deletion_verification"]["verdict"] == "deletion_mismatch"
    assert scope.keys == frozenset({(T, SECRET)})
    s = report["summary"]
    assert (s["documents_checked"], s["deletion_mismatch"], s["vectors_remaining"], s["retrievable"], s["verified_deleted"]) == (1, 1, 12, 1, 0)


def test_content_that_remains_but_never_ranks_is_high_not_critical_and_says_so():
    report, result, _ = verify(*world(searchable=False))
    [doc] = report["documents"]
    assert doc["verdict"] == "deletion_mismatch" and doc["retrieval"]["reachable"] is False
    assert "not returned in the top 10 of 3 queries" in check(doc, "Retrieval test")["result"]
    assert [f.severity.value for f in result.findings] == ["high"]


def test_a_clean_deletion_is_verified_across_the_source_the_manifest_and_the_index():
    report, result, _ = verify(*world(secret_points=0, status="deleted"))
    [doc] = report["documents"]
    assert doc["verdict"] == "verified_deleted" and result.findings == []
    assert [c["status"] for c in doc["checks"]] == ["ok", "ok", "ok", "ok"]
    assert check(doc, "Retrieval test")["result"] == "not run: no vectors remain" and doc["retrieval"] is None
    assert doc["recommended_action"].startswith("Nothing to do")


def test_vectors_gone_but_the_manifest_still_says_indexed_is_a_manifest_to_update():
    report, result, _ = verify(*world(secret_points=0, status="success"))
    [doc] = report["documents"]
    assert doc["verdict"] == "manifest_not_updated" and "Mark the document deleted" in doc["recommended_action"]
    assert [f.type.value for f in result.findings] == ["manifest_orphan"]


def test_a_cleanup_that_removed_only_some_vectors_is_still_a_mismatch_with_the_real_count():
    report, result, _ = verify(*world(secret_points=5))
    [doc] = report["documents"]
    assert doc["verdict"] == "deletion_mismatch" and doc["vectors"] == 5 and "Review the 5 remaining" in doc["recommended_action"]


def test_a_search_that_fails_is_reported_in_the_row_and_never_raised():
    report, result, _ = verify(*world(probe_error=RuntimeError("search backend unavailable")))
    [doc] = report["documents"]
    assert doc["verdict"] == "deletion_mismatch" and doc["retrieval"]["run"] is False
    test = check(doc, "Retrieval test")
    assert test["status"] == "unknown" and "could not be run" in test["result"] and "search backend unavailable" in test["result"]
    assert [f.severity.value for f in result.findings] == ["high"]  # not escalated: nothing was proven


def test_a_named_document_that_still_exists_is_not_a_deletion():
    source, manifest, index = world()
    report, result, _ = verify(source, manifest, index, {(T, KEEP): "you asked for it"})
    [doc] = report["documents"]
    assert doc["verdict"] == "not_deleted" and doc["source_present"] is True and doc["retrieval"] is None
    assert check(doc, "Source document")["result"] == "Still in the source" and "delete it there first" in doc["recommended_action"]
    assert result.findings == []


def test_the_same_document_id_alive_in_another_tenant_is_reported_as_wrong_tenant_vectors():
    source = FakeSource([src(SECRET, tenant="globex")])  # alive for globex; acme's copy was deleted
    manifest = FakeManifest([row(SECRET, tenant="globex", n=4)])
    index = SearchIndex([pt(SECRET, k, tenant="acme") for k in range(4)] + [pt(SECRET, k, tenant="globex") for k in range(4)])
    report, result, _ = verify(source, manifest, index, {("acme", SECRET): "it was in the source at the last audit and is gone now"})
    [f] = result.findings
    assert f.type.value == "tenant_mismatch" and f.severity.value == "critical"  # acme's vectors are tagged for a tenant that has no such file
    assert report["documents"][0]["verdict"] == "deletion_mismatch" and report["documents"][0]["vectors"] == 4


def test_vectors_spread_over_two_collections_are_all_counted_and_the_search_uses_one_of_them():
    points = [pt(KEEP, 0)] + [pt(SECRET, k, coll="docs-a") for k in range(4)] + [pt(SECRET, k + 4, coll="docs-b") for k in range(3)]
    report, _, _ = verify(FakeSource([src(KEEP)]), FakeManifest([row(KEEP, n=1), row(SECRET, n=7)]), SearchIndex(points))
    [doc] = report["documents"]
    assert doc["vectors"] == 7 and doc["collections"] == ["docs-a", "docs-b"] and doc["retrieval"]["returned_chunks"] > 0


def test_a_document_id_stored_as_a_number_is_still_recognised_in_the_search_results():
    doc_id = "2329961"
    points = [pt(doc_id, k, raw_doc=2329961) for k in range(5)]  # the index returns the id as a number
    report, _, _ = verify(FakeSource([]), FakeManifest([row(doc_id, n=5)]), SearchIndex(points), {(T, doc_id): "named"})
    assert report["documents"][0]["retrieval"]["reachable"] is True and report["documents"][0]["retrieval"]["returned_chunks"] >= 5


def test_the_number_of_searches_per_document_is_bounded():
    source, manifest, index = world(secret_points=40)
    verify(source, manifest, index, probes_per_document=2)
    assert len(index.probes) == 2  # a document with forty chunks costs two searches, not forty


# ------------------------------------------------------------------------------------- while only the source's documents are audited
def other_states(n=50):
    return [row(f"other-{i}", n=3) for i in range(n)]  # manifest rows of a document type that is not in this bucket


def audit_source_only(source, manifest, index, **kw):
    return run_reconciliation(source, manifest, index, AuditOptions(source_only=True, probe=False, required_fields=["document_id"], **kw))


def test_an_audit_that_ignores_other_documents_still_checks_the_ones_that_were_deleted():
    source = FakeSource([src(KEEP)])
    manifest = FakeManifest([row(KEEP, n=6), row(SECRET), *other_states()])
    index = SearchIndex([pt(KEEP, k) for k in range(6)] + [pt(SECRET, k) for k in range(12)])
    result = audit_source_only(source, manifest, index, prior_source_keys=frozenset({(T, KEEP), (T, SECRET)}))
    assert [(f.key, f.type.value) for f in result.findings] == [((T, SECRET), "orphan_vector")]  # and no noise from the 50 other rows
    assert result.stats["deletion_check"] == {"documents_checked": 1, "with_remaining_vectors": 1, "verified_gone": 0}


def test_a_document_the_manifest_marks_deleted_is_checked_without_any_earlier_audit():
    manifest = FakeManifest([row(KEEP, n=6), row(SECRET, status="deleted"), *other_states(10)])
    index = SearchIndex([pt(KEEP, k) for k in range(6)] + [pt(SECRET, k) for k in range(12)])
    leaking = audit_source_only(FakeSource([src(KEEP)]), manifest, index)
    assert [(f.key, f.type.value) for f in leaking.findings] == [((T, SECRET), "orphan_vector")]
    clean = audit_source_only(FakeSource([src(KEEP)]), manifest, SearchIndex([pt(KEEP, k) for k in range(6)]))
    assert clean.findings == [] and clean.stats["deletion_check"] == {"documents_checked": 1, "with_remaining_vectors": 0, "verified_gone": 1}


def test_vectors_of_documents_that_are_not_in_the_source_stay_out_of_scope_without_any_deletion_signal():
    """The reason for the setting: a shared index holds other sources. Without evidence of a deletion they are not reported."""
    manifest = FakeManifest([row(KEEP, n=6)])
    index = SearchIndex([pt(KEEP, k) for k in range(6)] + [pt("someone-elses.pdf", k) for k in range(30)])
    result = audit_source_only(FakeSource([src(KEEP)]), manifest, index)
    assert result.findings == [] and result.stats["deletion_check"]["documents_checked"] == 0


# ------------------------------------------------------------------------------------- the whole workflow through the service
def service(tmp_path, source, manifest, index) -> IntegrityService:
    s = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{(tmp_path / 'del.db').as_posix()}", source_documents_only=True,
                 probe_retrieval=False)
    return IntegrityService(s, Ledger(s.database_url), Connectors(source, manifest, index))


def open_issues(svc):
    return [(i["document_id"], i["type"], i["severity"]) for i in svc.ledger.list_issues(status="open", limit=100)[0]]


def test_from_the_deletion_to_the_verified_cleanup(tmp_path):
    source = FakeSource([src(KEEP), src(SECRET)])
    manifest = FakeManifest([row(KEEP, n=6), row(SECRET), *other_states(20)])
    index = SearchIndex([pt(KEEP, k) for k in range(6)] + [pt(SECRET, k) for k in range(12)])
    svc = service(tmp_path, source, manifest, index)
    first = svc.run_audit()
    assert first.status == "completed" and open_issues(svc) == []  # both documents are healthy and in the source

    source.docs = [src(KEEP)]  # the confidential document is deleted from S3; nothing touches its vectors
    second = svc.run_audit()
    assert open_issues(svc) == [(SECRET, "orphan_vector", "high")]  # found although only the source's documents are audited
    assert second.stats["deletion_check"]["with_remaining_vectors"] == 1

    report = svc.verify_deletions()
    [doc] = report["documents"]
    assert doc["verdict"] == "deletion_mismatch" and doc["vectors"] == 12 and doc["retrieval"]["reachable"] is True
    assert report["recorded"]["run_id"] and report["recorded"]["opened"] + report["recorded"]["unchanged"] >= 1
    assert open_issues(svc) == [(SECRET, "orphan_vector", "critical")]  # the search proved it: escalated
    runs = svc.ledger.list_runs(limit=10, kind="scoped")
    assert runs[0]["trigger"] == "deletion-check" and runs[0]["status"] == "completed"

    index.points = [p for p in index.points if p.document_id != SECRET]  # the approved cleanup has run
    after = svc.verify_deletions()
    assert after["documents"][0]["verdict"] == "manifest_not_updated"  # vectors are gone; the manifest still says "success"
    assert after["recorded"]["resolved"] >= 0 and not [i for i in open_issues(svc) if i[1] == "orphan_vector"]
    manifest.rows = [r for r in manifest.rows if r.document_id != SECRET]
    final = svc.verify_deletions()
    assert final["summary"]["documents_checked"] == 0 and "Nothing to verify" in final["note"]  # nothing left to worry about


def test_looking_without_recording_leaves_no_trace_and_recording_never_runs_beside_an_audit(tmp_path):
    source, manifest, index = world()
    svc = service(tmp_path, source, manifest, index)
    report = svc.verify_deletions([(T, SECRET)], record=False)
    assert report["recorded"] is None and svc.ledger.list_runs() == [] and svc.ledger.list_issues(status="all")[1] == 0
    assert report["documents"][0]["reason"] == "you asked for it"
    assert svc._lock.acquire(blocking=False)
    try:
        with pytest.raises(AuditBusy):
            svc.verify_deletions([(T, SECRET)], record=True)
        assert svc.verify_deletions([(T, SECRET)], record=False)["documents"]  # looking is always allowed
    finally:
        svc._lock.release()


def test_the_check_is_capped_and_says_how_many_it_left_out(tmp_path):
    names = [f"gone-{i:03d}.pdf" for i in range(30)]
    manifest = FakeManifest([row(KEEP, n=1)] + [row(n, status="deleted", n=1) for n in names])
    svc = service(tmp_path, FakeSource([src(KEEP)]), manifest, SearchIndex([pt(KEEP, 0)]))
    report = svc.verify_deletions(record=False, max_documents=10)
    assert report["summary"]["documents_checked"] == 10 and report["truncated"] == 20


# ------------------------------------------------------------------------------------- over HTTP, on the demo world
def test_the_endpoint_verifies_the_demo_worlds_orphans_and_records_them(tmp_path):
    from tests.test_api import make_client

    client, svc = make_client(tmp_path)
    with client:
        before = len(client.get("/api/audits").json())
        r = client.post("/api/deletion-check", json={"record": False})
        assert r.status_code == 200 and r.json()["recorded"] is None
        body = r.json()
        assert body["summary"]["deletion_mismatch"] >= 1 and body["summary"]["documents_checked"] >= body["summary"]["deletion_mismatch"]
        assert all(d["checks"] and d["recommended_action"] for d in body["documents"])
        assert len(client.get("/api/audits").json()) == before  # looking recorded nothing
        recorded = client.post("/api/deletion-check", json={}).json()
        assert recorded["recorded"]["run_id"] and len(client.get("/api/audits").json()) == before + 1
        one = client.post("/api/deletion-check", json={"documents": [{"tenant_id": "acme", "document_id": "no-such-document.md"}], "record": False})
        assert one.status_code == 200 and any(d["document_id"] == "no-such-document.md" and d["verdict"] == "verified_deleted"
                                              for d in one.json()["documents"])


def test_the_endpoint_needs_a_session_and_is_rate_limited_in_the_hosted_app(tmp_path):
    from tests.test_app_mode import make, signup

    c, *_ = make(tmp_path)
    with c:
        assert c.post("/api/deletion-check").status_code == 401
        signup(c)
        codes = [c.post("/api/deletion-check", json={"record": False}).status_code for _ in range(21)]
        assert codes[0] == 409 and codes[-1] == 429  # nothing connected yet (409), and 20 per 10 minutes per workspace


# ------------------------------------------------------------------------------------- against a real Qdrant server
URL, KEY = os.environ.get("RAGI_TEST_QDRANT_URL"), os.environ.get("RAGI_TEST_QDRANT_KEY")


@pytest.mark.skipif(not URL, reason="RAGI_TEST_QDRANT_URL not set")
@pytest.mark.parametrize("stored_as", ["text", "number"])
def test_a_real_search_returns_deleted_content_until_its_vectors_are_removed(stored_as):
    client = QdrantClient(url=URL, api_key=KEY, timeout=30)
    name = "ragi_test_deletion"
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(name, vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    gone = "2329961" if stored_as == "number" else SECRET
    stored = int(gone) if stored_as == "number" else gone
    try:
        points = [qm.PointStruct(id=1000 + k, vector=[1.0, 0.1 * k, 0.0], payload={"document_id": stored, "chunk_id": f"g{k}", "chunk_index": k,
                                                                                    "source_hash": "h-gone"}) for k in range(8)]
        points += [qm.PointStruct(id=2000 + k, vector=[0.0, 1.0, 0.1 * k], payload={"document_id": KEEP, "chunk_id": f"k{k}", "chunk_index": k,
                                                                                      "source_hash": f"h-{KEEP}"}) for k in range(5)]
        client.upsert(name, points=points, wait=True)
        idx = QdrantIndex(Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY, qdrant_collections=name), client=client)
        manifest = FakeManifest([row(KEEP, n=5), row(gone, n=8)])
        report, result, _ = verify_deletions(FakeSource([src(KEEP)]), manifest, idx, AuditOptions(probe=False, required_fields=["document_id"]),
                                             {(T, gone): "named"})
        [doc] = report["documents"]
        assert doc["verdict"] == "deletion_mismatch" and doc["vectors"] == 8
        assert doc["retrieval"]["reachable"] is True and doc["retrieval"]["best_rank"] == 1 and doc["retrieval"]["returned_chunks"] >= 5
        assert [f.severity.value for f in result.findings] == ["critical"]

        client.delete(name, points_selector=qm.PointIdsList(points=[p.id for p in points[:8]]), wait=True)  # the approved cleanup
        after, again, _ = verify_deletions(FakeSource([src(KEEP)]), manifest, idx, AuditOptions(probe=False, required_fields=["document_id"]),
                                           {(T, gone): "named"})
        assert after["documents"][0]["verdict"] == "manifest_not_updated" and after["documents"][0]["vectors"] == 0
        assert after["documents"][0]["retrieval"] is None
    finally:
        client.delete_collection(name)


# ------------------------------------------------------------------------------------- the probe and the tenant
def test_a_probe_filters_by_tenant_only_when_the_points_have_one():
    """Without this a corpus whose payloads carry no tenant (a single-tenant index) answered every probe with zero hits, which
    reads as "not searchable" when nothing had been searched at all."""
    client = QdrantClient(":memory:")
    client.create_collection("c", vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    client.upsert("c", points=[
        *[qm.PointStruct(id=1 + k, vector=[1.0, 0.01 * k, 0.0], payload={"document_id": "plain"}) for k in range(3)],
        *[qm.PointStruct(id=10 + k, vector=[1.0, 0.02 * k, 0.0], payload={"document_id": "of-t1", "tenant_id": "t1"}) for k in range(3)],
        *[qm.PointStruct(id=20 + k, vector=[1.0, 0.03 * k, 0.0], payload={"document_id": "of-t2", "tenant_id": "t2"}) for k in range(3)],
    ])
    idx = QdrantIndex(Settings(_env_file=None, qdrant_collections="c"), client=client)
    tenantless = idx.probe("c", "1", "default", 20)
    assert tenantless and {d for _, _, d in tenantless} == {"plain", "of-t1", "of-t2"}  # no tenant on the point: nothing to scope by
    scoped = idx.probe("c", "10", "t1", 20)
    assert {d for _, _, d in scoped} == {"of-t1"}  # a tenant on the point: the search stays inside it, as a real query would
