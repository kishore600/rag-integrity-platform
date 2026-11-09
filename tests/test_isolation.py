"""Tenant isolation: the summary built from every full audit, its report and API, and the read-only drill."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from ragintegrity.api.app import create_app
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.engine.drills import DRILL_TENANT
from ragintegrity.models import ConnectionStatus, IndexedChunk, IssueType, ManifestRow, Scope, SourceDoc
from tests.test_service import make_service


def _iso(result):
    return result.stats["isolation"]


# ------------------------------------------------------------------------------------- the summary
def test_the_summary_matches_the_planted_faults(world, connectors, opts):
    result = run_reconciliation(*connectors, opts)
    iso = _iso(result)
    leaks = [f for f in result.findings if f.type == IssueType.TENANT_MISMATCH]
    acl = [f for f in result.findings if f.type == IssueType.METADATA_INCONSISTENT
           and any(p["code"] == "acl_mismatch" for p in f.evidence["problems"])]
    assert leaks and acl, "the demo world must contain both faults for this test to mean anything"

    o = iso["overall"]
    assert o["status"] == "leak" and o["tenants"] == len(world.tenants) == len(iso["tenants"])
    assert o["leaking_documents"] == len(leaks) and o["permission_mismatch_documents"] == len(acl)
    assert o["leaks_confirmed_reachable"] == len(leaks)  # the live probe proved each one is returned by a search
    assert o["points_checked"] == len(world.points) and o["permissions_recorded"] is True
    by = {t["tenant_id"]: t for t in iso["tenants"]}
    assert all(by[f.tenant_id]["status"] == "leak" and by[f.tenant_id]["foreign_documents"] >= 1 for f in leaks)
    assert iso["tenants"][0]["status"] == "leak"  # worst first
    checks = {c["name"]: c["status"] for c in iso["checks"]}
    assert checks["Documents indexed under the wrong tenant"] == "fail"
    assert checks["Leaks confirmed reachable by a real search"] == "fail"
    assert checks["Permission labels agree with the manifest"] == "fail"
    assert checks["Every vector carries a tenant label"] == "pass"


def test_scoped_audits_do_not_overwrite_the_picture(world, connectors, opts):
    assert "isolation" not in run_reconciliation(*connectors, opts, Scope(tenant=world.tenants[0] if hasattr(world, "tenants") else "acme")).stats


def test_turning_on_source_only_marks_the_picture_as_limited(world, connectors, opts):
    """Wrong-tenant vectors are not even read when only the source's own documents are scanned: say so, don't claim 'clean'."""
    iso = _iso(run_reconciliation(*connectors, dataclasses.replace(opts, source_only=True)))
    assert iso["overall"]["status"] == "limited" and "Only audit documents found in the source" in iso["overall"]["summary"]
    assert {c["status"] for c in iso["checks"] if c["name"] in (
        "Documents indexed under the wrong tenant", "Leaks confirmed reachable by a real search")} == {"na"}


class Src:
    def __init__(self, docs):
        self.docs = docs

    def inventory(self, scope=None):
        yield from self.docs

    def health(self):
        return ConnectionStatus("s", "source", True)


class Man:
    has_chunk_manifest = False

    def __init__(self, rows=()):
        self.rows = list(rows)

    def documents(self, scope=None):
        yield from self.rows

    def chunks(self, scope=None):
        return iter(())

    def health(self):
        return ConnectionStatus("m", "manifest", True)


class Idx:
    def __init__(self, chunks):
        self.chunks = chunks

    def collections(self):
        return ["c"]

    def vector_sizes(self):
        return {"c": 3}

    def scan(self, scope=None, with_vectors=False):
        return iter(self.chunks)

    def probe(self, *a, **k):
        return None

    def health(self):
        return ConnectionStatus("i", "index", True)


def point(i, tenant, doc, acl="a1"):
    return IndexedChunk("c", f"p{i}", tenant, doc, chunk_id=f"k{i}", source_hash="h", acl_hash=acl,
                        present_fields=frozenset({"document_id", "source_hash"}))


def audit(src, man, chunks, **kw):
    return run_reconciliation(Src(src), Man(man), Idx(chunks), AuditOptions(probe=False, **kw))


def test_one_tenant_means_isolation_does_not_apply():
    src = [SourceDoc("default", "d1", "s3://b/d1", source_hash="h")]
    iso = _iso(audit(src, [], [point(1, "default", "d1")]))
    assert iso["overall"]["status"] == "not_applicable" and iso["tenants"][0]["status"] == "single_tenant"
    assert iso["overall"]["tenants"] == 1


def test_clean_with_two_tenants():
    src = [SourceDoc("a", "d1", "s3://b/a/d1", source_hash="h"), SourceDoc("b", "d2", "s3://b/b/d2", source_hash="h")]
    iso = _iso(audit(src, [], [point(1, "a", "d1"), point(2, "b", "d2")]))
    assert iso["overall"]["status"] == "clean" and {t["status"] for t in iso["tenants"]} == {"clean"}
    assert iso["overall"]["tenant_label_pct"] == 100.0 and iso["overall"]["permission_label_pct"] == 100.0
    assert {c["status"] for c in iso["checks"]} == {"pass", "na"}


def test_vectors_without_a_tenant_label_need_attention():
    src = [SourceDoc("a", "d1", "s3://b/a/d1", source_hash="h"), SourceDoc("b", "d2", "s3://b/b/d2", source_hash="h")]
    chunks = [point(1, "a", "d1"), point(2, "b", "d2"), point(3, None, "d1")]  # the third has no tenant: assumed to be 'a'
    iso = _iso(audit(src, [], chunks, default_tenant="a"))
    by = {t["tenant_id"]: t for t in iso["tenants"]}
    assert by["a"]["points"] == 2 and by["a"]["tenant_label_pct"] == 50.0  # one of tenant a's two vectors carries a label
    assert by["a"]["status"] == "attention" and by["b"]["status"] == "clean"
    assert iso["overall"]["tenant_label_pct"] == pytest.approx(66.7, abs=0.1)  # two of the three vectors overall
    assert iso["overall"]["status"] == "attention"
    assert {c["name"]: c["status"] for c in iso["checks"]}["Every vector carries a tenant label"] == "warn"


def test_permissions_not_recorded_is_not_a_failure():
    src = [SourceDoc("a", "d1", "s3://b/a/d1", source_hash="h"), SourceDoc("b", "d2", "s3://b/b/d2", source_hash="h")]
    iso = _iso(audit(src, [], [point(1, "a", "d1", acl=None), point(2, "b", "d2", acl=None)]))
    assert iso["overall"]["permissions_recorded"] is False and iso["overall"]["permission_label_pct"] is None
    assert iso["overall"]["status"] == "clean"
    assert {c["name"]: c["status"] for c in iso["checks"]}["Every vector carries a permission label"] == "na"


def test_a_planted_leak_with_two_tenants_is_critical():
    src = [SourceDoc("a", "d1", "s3://b/a/d1", source_hash="h"), SourceDoc("b", "d2", "s3://b/b/d2", source_hash="h")]
    chunks = [point(1, "a", "d1"), point(2, "b", "d2"), point(3, "b", "d1")]  # a's document d1 also sits under tenant b
    result = audit(src, [], chunks)
    iso = _iso(result)
    assert iso["overall"]["status"] == "leak" and iso["overall"]["leaking_documents"] == 1
    assert {t["tenant_id"]: t["status"] for t in iso["tenants"]}["b"] == "leak"
    leak = next(f for f in result.findings if f.type == IssueType.TENANT_MISMATCH)
    assert leak.severity.value == "critical" and leak.tenant_id == "b" and leak.evidence["expected_tenants"] == ["a"]


# ------------------------------------------------------------------------------------- the service, the drill and the API
@pytest.fixture()
def svc(tmp_path):
    s = make_service(tmp_path)
    s.bootstrap()
    return s


def test_no_audit_no_picture(tmp_path):
    s = make_service(tmp_path)
    s.ledger.init()
    out = s.isolation()
    assert out["available"] is False and "full audit" in out["note"]


def test_the_service_serves_the_latest_picture_with_its_findings(svc):
    out = svc.isolation()
    assert out["available"] and out["overall"]["status"] == "leak" and out["audit"]["kind"] == "full"
    types = {f["type"] for f in out["findings"]}
    assert "tenant_mismatch" in types and "metadata_inconsistent" in types
    assert out["findings_total"] >= len(out["findings"]) >= 1


def test_the_drill_catches_a_pretend_leak_and_changes_nothing(svc):
    index = svc.connectors.index
    before_points = {pid: dict(sp.payload) for pid, sp in index.world.points.items()}
    before_issues, before_runs = svc.ledger.issue_counts(), len(svc.ledger.list_runs(limit=100))

    out = svc.isolation_drill()

    assert out["drill"] is True and out["caught"] is True and out["document"]["points"] > 0
    leak = next(f for f in out["findings"] if f["type"] == "tenant_mismatch")
    assert leak["severity"] == "critical" and leak["tenant_id"] == DRILL_TENANT
    assert out["would_alert"]["severity"] == "critical" and out["document"]["document_id"] in out["would_alert"]["text"]
    assert "Nothing was written" in out["nothing_changed"]
    # nothing real moved: the index, the issue ledger and the audit history are exactly as they were
    assert {pid: dict(sp.payload) for pid, sp in index.world.points.items()} == before_points
    assert svc.ledger.issue_counts() == before_issues and len(svc.ledger.list_runs(limit=100)) == before_runs


def test_the_drill_can_target_a_chosen_document_and_validates_its_input(svc):
    rows, _ = svc.ledger.list_documents(status="healthy", limit=5)
    doc = next(r for r in rows if r["index_present"] and r["indexed_chunks"])
    out = svc.isolation_drill(doc["tenant_id"], doc["document_id"])
    assert out["caught"] and out["document"]["document_id"] == doc["document_id"]
    with pytest.raises(ValueError, match="both tenant and document_id"):
        svc.isolation_drill(tenant="acme")
    with pytest.raises(ValueError, match="not been audited"):
        svc.isolation_drill("acme", "no-such-document")


def test_the_drill_needs_an_audit_first(tmp_path):
    s = make_service(tmp_path)
    s.ledger.init()
    with pytest.raises(ValueError, match="Run a full audit"):
        s.isolation_drill()


def test_the_api(tmp_path):
    s = make_service(tmp_path)
    s.bootstrap()
    with TestClient(create_app(s, s.settings)) as c:
        body = c.get("/api/isolation").json()
        assert body["available"] and body["overall"]["status"] == "leak" and body["tenants"] and body["checks"]

        md = c.get("/api/isolation/report", params={"format": "md"})
        assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
        assert "attachment" in md.headers["content-disposition"]
        assert "# Tenant isolation report" in md.text and "LEAK" in md.text and "nothing in your S3" in md.text
        assert c.get("/api/isolation/report").json()["overall"]["status"] == "leak"

        drill = c.post("/api/isolation/drill", json={})
        assert drill.status_code == 200 and drill.json()["caught"] is True
        assert c.post("/api/isolation/drill").status_code == 200  # the body is optional
        bad = c.post("/api/isolation/drill", json={"tenant": "acme"})
        assert bad.status_code == 400 and "both tenant and document_id" in bad.json()["detail"]
        assert c.post("/api/isolation/drill", json={"tenant": "x" * 300, "document_id": "d"}).status_code == 422


def test_an_unavailable_report_says_so():
    from ragintegrity.engine.isolation import to_markdown

    assert "No full audit has finished" in to_markdown({"available": False})


def test_stored_summaries_stay_small():
    from ragintegrity.engine.isolation import MAX_TENANTS

    assert MAX_TENANTS == 200


def test_manifest_rows_alone_do_not_hide_a_tenant():
    """A tenant that exists only in the manifest still appears (with no vectors) instead of vanishing from the report."""
    src = [SourceDoc("a", "d1", "s3://b/a/d1", source_hash="h")]
    man = [ManifestRow("b", "d9", processing_status="success")]
    iso = _iso(audit(src, man, [point(1, "a", "d1")]))
    assert {t["tenant_id"] for t in iso["tenants"]} == {"a", "b"}
