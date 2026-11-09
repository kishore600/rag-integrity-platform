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


def audit(src, man, chunks, index=None, **kw):
    return run_reconciliation(Src(src), Man(man), index or Idx(chunks), AuditOptions(**{"probe": False, **kw}))


class ProbingIdx(Idx):
    """An index whose live search always answers ``hits`` (a list of (point id, score, document id))."""

    def __init__(self, chunks, hits):
        super().__init__(chunks)
        self.hits = hits

    def probe(self, collection, point_id, tenant_id, top_k):
        return self.hits


def leak_world(leaks=1):
    src = [SourceDoc("a", f"d{i}", f"s3://b/a/d{i}", source_hash="h") for i in range(1, leaks + 1)]
    src.append(SourceDoc("b", "other", "s3://b/b/other", source_hash="h"))
    chunks = [point(i, "a", f"d{i}") for i in range(1, leaks + 1)]
    chunks += [point(100 + i, "b", f"d{i}") for i in range(1, leaks + 1)]  # each of a's documents also sits under tenant b
    chunks.append(point(999, "b", "other"))
    return src, chunks


def reach_check(iso):
    return next(c for c in iso["checks"] if c["name"].startswith("Leaks confirmed"))


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


def test_a_leak_nobody_searched_for_is_a_warning_not_a_pass():
    src, chunks = leak_world()
    iso = _iso(audit(src, [], chunks))  # live searches off
    c = reach_check(iso)
    assert c["status"] == "warn" and "None of the 1 leaked" in c["detail"] and "unknown" in c["detail"]
    assert iso["overall"]["leaks_tested_by_search"] == 0 and iso["overall"]["leaks_confirmed_reachable"] == 0


def test_a_leak_returned_by_a_live_search_fails_the_check():
    src, chunks = leak_world()
    iso = _iso(audit(src, [], chunks, index=ProbingIdx(chunks, [("p101", 0.9, "d1")]), probe=True))
    c = reach_check(iso)
    assert c["status"] == "fail" and "1 of 1" in c["detail"]
    assert iso["overall"]["leaks_tested_by_search"] == 1 and iso["overall"]["leaks_confirmed_reachable"] == 1


def test_a_leak_searched_but_not_returned_passes_but_says_the_labels_are_still_wrong():
    src, chunks = leak_world()
    iso = _iso(audit(src, [], chunks, index=ProbingIdx(chunks, []), probe=True))  # a search was sent and returned nothing
    c = reach_check(iso)
    assert c["status"] == "pass" and "labels are still wrong" in c["detail"]
    assert iso["overall"]["status"] == "leak"  # the leak itself is unchanged


def test_leaks_that_were_only_partly_searched_are_a_warning():
    src, chunks = leak_world(leaks=2)
    iso = _iso(audit(src, [], chunks, index=ProbingIdx(chunks, []), probe=True, probe_max=1))
    c = reach_check(iso)
    assert c["status"] == "warn" and "1 of 2 leaked" in c["detail"] and "1 were not searched" in c["detail"]


def test_checks_that_were_not_run_say_so_and_never_read_like_a_pass(world, connectors, opts):
    limited = _iso(run_reconciliation(*connectors, dataclasses.replace(opts, source_only=True)))
    single = _iso(audit([SourceDoc("default", "d1", "s3://b/d1", source_hash="h")], [], [point(1, "default", "d1", acl=None)]))
    for iso in (limited, single):
        for c in iso["checks"]:
            assert c["status"] == "na" and c["detail"].startswith("Not checked") and "All " not in c["detail"], c


def test_the_report_never_prints_none():
    src = [SourceDoc("a", "d1", "s3://b/a/d1", source_hash="h")]
    iso = _iso(audit(src, [ManifestRow("b", "d9", processing_status="success")], [point(1, "a", "d1")]))  # tenant b: no vectors
    assert next(t for t in iso["tenants"] if t["tenant_id"] == "b")["tenant_label_pct"] is None
    from ragintegrity.engine.isolation import pct_text, to_markdown

    md = to_markdown({"available": True, "audit": {"run_id": "r1", "finished_at": "now"}, **iso, "findings": []})
    assert "None%" not in md and "| None |" not in md and "n/a" in md  # ("None found." in a check is real wording)
    assert pct_text(None) == "n/a" and pct_text(87.5) == "87.5%"


def test_the_drill_previews_the_alert_in_the_real_alert_format(svc):
    out = svc.isolation_drill()
    alert = out["would_alert"]
    assert alert["sent"] is False and alert["severity"] == "critical" and "never sends it" in alert["note"]
    assert alert["text"].startswith("*RAG Integrity*: 1 new issue(s) at or above `high` (health ")  # what alerts.notify posts
    assert "[CRITICAL]" in alert["text"] and out["document"]["document_id"] in alert["text"] and "None" not in alert["text"]


def test_findings_say_when_they_no_longer_match_the_last_full_audit(svc):
    out = svc.isolation()
    assert out["findings_live"] is True and out["findings_changed_since_audit"] is False
    leak = next(f for f in out["findings"] if f["type"] == "tenant_mismatch")
    assert svc.ledger.set_issue_status(leak["issue_id"], "ignored", "test")  # someone ignores it after the audit
    after = svc.isolation()
    assert after["findings_changed_since_audit"] is True and after["findings_total"] == out["findings_total"] - 1
    assert after["overall"]["leaking_documents"] == out["overall"]["leaking_documents"]  # the audit's own numbers stay as they were


def test_the_summary_sentence_always_uses_the_current_wording(svc):
    """An audit stored earlier holds the sentence it was written with; reading it must show today's wording."""
    from ragintegrity.engine.isolation import OVERALL_TEXT

    run = svc.ledger.list_runs(limit=1, kind="full", status="completed")[0]
    stats = dict(run["stats"])
    stats["isolation"]["overall"]["summary"] = "OLD WORDING FROM AN EARLIER VERSION"
    svc.ledger.finish_run(run["id"], "completed", stats)
    assert svc.ledger.list_runs(limit=1, kind="full", status="completed")[0]["stats"]["isolation"]["overall"]["summary"].startswith("OLD")

    out = svc.isolation()
    assert out["overall"]["summary"] == OVERALL_TEXT[out["overall"]["status"]] and "OLD" not in out["overall"]["summary"]
    assert OVERALL_TEXT[out["overall"]["status"]] in svc.isolation_report("md")  # the evidence report uses it too


def test_the_limited_advice_does_not_send_a_large_index_into_a_timeout():
    from ragintegrity.engine.isolation import OVERALL_TEXT

    text = OVERALL_TEXT["limited"]
    assert "ragi audit" in text and "only when the index is small" in text  # not a bare "turn it off"
    assert "Only audit documents found in the source (S3)" in text  # still names the switch


def test_a_zero_percent_tenant_label_is_explained_in_the_report():
    from ragintegrity.engine.isolation import label_text, to_markdown

    assert "no tenant field" in label_text(0.0) and label_text(87.5) == "87.5%" and label_text(None) == "n/a"
    src = [SourceDoc("default", "d1", "s3://b/d1", source_hash="h")]
    iso = _iso(audit(src, [], [point(1, None, "d1", acl=None)]))  # the payload has no tenant field
    assert iso["overall"]["tenant_label_pct"] == 0.0
    md = to_markdown({"available": True, "audit": {"run_id": "r1", "finished_at": "now"}, **iso, "findings": []})
    assert "0.0% (the payload has no tenant field" in md


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
