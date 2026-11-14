"""Feature 1, part A: the processing manifest is optional, and the index can be pgvector instead of Qdrant (the settings side).

Most teams have no manifest: their pipeline reads a file, cuts it into chunks, embeds them and saves them. With only S3 and
the vector index, the audit compares the files with the vectors directly, using what every vector already carries (its document id
and the hash of the file it came from). These tests prove which checks still work, which honestly do not, and that the product
says so instead of guessing.
"""

from __future__ import annotations

import dataclasses

from ragintegrity.config import Settings
from ragintegrity.connectors.factory import Connectors, build_connectors
from ragintegrity.connectors.nomanifest import NoManifest
from ragintegrity.connectors.pgvector import PgVectorIndex
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.engine.reconcile import CHECKS_NEEDING_A_MANIFEST
from ragintegrity.ledger import Ledger
from ragintegrity.models import Fingerprint, IndexedChunk, ManifestRow, SourceDoc
from ragintegrity.service import IntegrityService
from ragintegrity.workspaces import _factory, overlay, required_kinds
from tests.test_app_mode import make, signup
from tests.test_scan_reliability import KEY, PointIndex
from tests.test_source_only import FakeManifest, FakeSource


def doc(name: str, h: str = "h", tenant: str = KEY) -> SourceDoc:
    return SourceDoc(tenant, name, f"s3://b/{name}.pdf", source_hash=h, size_bytes=1)


def pt(name: str, k: int, h: str = "h", *, total: int | None = None, tenant: str = KEY, tag: str = "", index: bool = True) -> IndexedChunk:
    return IndexedChunk("c", f"{name}-{k}{tag}", tenant, name, chunk_id=f"{name}#{k}" if index else None, chunk_index=k if index else None,
                        source_hash=h, fingerprint=Fingerprint(), present_fields=frozenset({"document_id", "source_hash"}), chunk_total=total)


def audit(docs, points, manifest=None, **opts):
    return run_reconciliation(FakeSource(docs), manifest if manifest is not None else NoManifest(), PointIndex(points),
                              AuditOptions(probe=False, required_fields=["document_id"], **opts))


def by_doc(result) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in result.findings:
        out.setdefault(f.document_id, set()).add(f.type.value)
    return out


# ------------------------------------------------------------------------------------------------ what still works
def test_two_connections_are_enough_the_example_from_the_product_description():
    """refund-policy is fine; pricing changed; faq was never indexed; old-terms was deleted but its vectors remain."""
    docs = [doc("refund-policy", "abc"), doc("pricing", "xyz"), doc("faq", "f")]
    points = [*(pt("refund-policy", k, "abc") for k in range(3)), *(pt("pricing", k, "old") for k in range(2)),
              *(pt("old-terms", k, "t") for k in range(2))]
    result = audit(docs, points)
    assert by_doc(result) == {"pricing": {"stale_embedding"}, "faq": {"missing_embedding"}, "old-terms": {"orphan_vector"}}
    status = {s.document_id: s.status for s in result.summaries}
    assert status == {"refund-policy": "healthy", "pricing": "broken", "faq": "broken", "old-terms": "orphaned"}
    assert result.stats["manifest_rows"] == 0 and result.stats["manifest"]["connected"] is False
    assert all(s.manifest_present is False for s in result.summaries)


def test_a_document_that_was_never_indexed_is_reported_without_blaming_a_missing_manifest_row():
    missing = next(f for f in audit([doc("faq")], []).findings if f.type.value == "missing_embedding")
    assert missing.severity.value == "high" and "No vector in the index carries this document's id" in missing.detail
    assert "manifest" not in missing.detail.lower() and missing.evidence["pipeline_reported_success"] is False
    # with a manifest that says "success" the same gap is the dangerous one, and it is critical: that check needs the manifest
    claims = ManifestRow(KEY, "faq", processing_status="success", indexed_chunk_count=3)
    worse = next(f for f in audit([doc("faq")], [], FakeManifest([claims])).findings if f.type.value == "missing_embedding")
    assert worse.severity.value == "critical" and worse.evidence["pipeline_reported_success"] is True


def test_no_document_is_called_untracked_just_because_there_is_no_manifest():
    healthy = audit([doc("a")], [pt("a", 0), pt("a", 1)])
    assert healthy.findings == [] and healthy.stats["findings_total"] == 0
    # with a manifest connected but empty, the same documents ARE untracked: the pipeline recorded nothing for them
    tracked = audit([doc("a")], [pt("a", 0), pt("a", 1)], FakeManifest([]))
    assert any("untracked_in_manifest" in str(f.evidence.get("problems")) for f in tracked.findings)


def test_duplicates_empty_vectors_and_the_wrong_tenant_are_found_without_a_manifest():
    empty = dataclasses.replace(pt("d", 1), vector_checked=True, vector_ok=False)
    points = [pt("dup", 0), pt("dup", 0, tag="-again"), pt("d", 0), empty, *(pt("contract", k, tenant="globex") for k in range(2))]
    result = audit([doc("dup"), doc("d"), doc("contract", tenant="acme")], points)
    # the contract is in S3 under tenant acme but its vectors say globex: the leak, and acme's own copy is not indexed at all
    assert by_doc(result) == {"dup": {"duplicate_chunk"}, "d": {"empty_embedding"}, "contract": {"tenant_mismatch", "missing_embedding"}}
    leak = next(f for f in result.findings if f.type.value == "tenant_mismatch")
    assert leak.severity.value == "critical" and leak.tenant_id == "globex"


# ------------------------------------------------------------------------------------------------ half-indexed documents
def test_half_indexed_is_confirmed_when_each_vector_says_how_many_chunks_the_document_has():
    result = audit([doc("d")], [pt("d", 0, total=4), pt("d", 1, total=4), pt("d", 3, total=4)])
    [f] = [f for f in result.findings if f.type.value == "partial_index"]
    assert f.severity.value == "high" and f.evidence["method"] == "payload_chunk_total" and f.evidence["expected_chunks"] == 4
    assert f.evidence["missing_chunks"] == ["c:#2"] and f.evidence["confidence"] == "confirmed"


def test_half_indexed_is_only_suspected_from_a_gap_in_the_chunk_numbers_when_there_is_no_total():
    result = audit([doc("d")], [pt("d", 0), pt("d", 1), pt("d", 3)])
    [f] = [f for f in result.findings if f.type.value == "partial_index"]
    assert f.severity.value == "medium" and f.evidence["method"] == "index_gaps" and f.evidence["confidence"].startswith("suspected")


def test_half_indexed_cannot_be_detected_when_vectors_carry_neither_a_chunk_number_nor_a_total():
    """The honest limit: without a manifest and without chunk numbers, two vectors of a four-chunk document look complete."""
    assert audit([doc("d")], [pt("d", 0, index=False), pt("d", 1, index=False)]).findings == []


def test_the_left_over_tail_of_a_shortened_document_is_found_from_the_total_the_vectors_declare():
    points = [pt("d", k, total=3) for k in range(5)]  # the new version has 3 chunks; chunks 3 and 4 are the old tail
    result = audit([doc("d")], points)
    [f] = [f for f in result.findings if f.type.value == "superseded_active"]
    assert f.evidence["method"] == "payload_chunk_total" and f.evidence["unexpected_chunk_count"] == 2 and f.evidence["expected_chunks"] == 3


# ------------------------------------------------------------------------------------------------ the run says what it left out
def test_the_run_records_which_checks_a_missing_manifest_left_out_and_a_manifest_run_does_not():
    run = audit([doc("a")], [pt("a", 0)])
    assert run.stats["manifest"] == {"connected": False, "checks_not_run": list(CHECKS_NEEDING_A_MANIFEST)}
    assert len(CHECKS_NEEDING_A_MANIFEST) == 4 and all(isinstance(c, str) and len(c) > 40 for c in CHECKS_NEEDING_A_MANIFEST)
    assert audit([doc("a")], [pt("a", 0)], FakeManifest([ManifestRow(KEY, "a", processing_status="success")])).stats["manifest"] == {"connected": True}


def service(tmp_path, docs, points, manifest=None, name="ledger", **kw) -> IntegrityService:
    s = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{(tmp_path / (name + '.db')).as_posix()}", probe_retrieval=False,
                 grace_minutes=0, **kw)
    return IntegrityService(s, Ledger(s.database_url), Connectors(FakeSource(docs), manifest if manifest is not None else NoManifest(),
                                                                  PointIndex(points)))


def test_an_audit_through_the_service_works_with_a_sliced_scan_and_records_the_manifest_note(tmp_path):
    docs = [doc(f"d{i}") for i in range(5)]
    points = [pt(d.document_id, k) for d in docs[:4] for k in range(2)]  # d4 was never indexed
    svc = service(tmp_path, docs, points, source_documents_only=True, audit_slice_documents=2)
    result = svc.run_audit()
    assert result.status == "completed" and result.stats["findings_by_type"] == {"missing_embedding": 1}
    run = svc.ledger.get_run(result.run_id)
    assert run["stats"]["manifest"]["connected"] is False and run["stats"]["scan"]["mode"] == "sliced"
    assert "manifest" in svc.overview()["latest_run"]["stats"]
    row = next(c for c in svc.connections() if c["kind"] == "manifest")
    assert row["ok"] is True and "Not connected" in row["detail"] and row["info"] == {"connected": False, "optional": True}


def test_the_setup_check_compares_only_s3_and_the_index_and_says_the_manifest_is_not_connected(tmp_path):
    docs = [doc(f"d{i}") for i in range(4)]
    svc = service(tmp_path, docs, [pt(d.document_id, 0) for d in docs])
    report = svc.setup_check()
    ids = {c["id"]: c for c in report["checks"]}
    assert report["manifest_connected"] is False and report["counts"]["manifest_connected"] is False
    assert ids["manifest_rows"]["status"] == "na" and "optional" in ids["manifest_rows"]["detail"].lower()
    assert not {"manifest_ids_unique", "source_vs_manifest", "manifest_vs_source", "manifest_files_exist"} & set(ids)
    assert report["coverage"]["source_to_manifest"] is None and report["coverage"]["manifest_to_source"] is None
    assert ids["index_revision"]["status"] == "pass" and "ready" in report["status"] or report["status"] in ("needs_attention", "ready")
    assert "no manifest is connected" in report["headline"] or "S3 and the index" in report["headline"]


def test_the_setup_check_warns_when_vectors_carry_no_file_hash_because_a_changed_file_cannot_then_be_detected(tmp_path):
    docs = [doc("a"), doc("b")]
    bare = [dataclasses.replace(pt(d.document_id, 0), source_hash=None, present_fields=frozenset({"document_id"})) for d in docs]
    report = service(tmp_path, docs, bare).setup_check()
    check = next(c for c in report["checks"] if c["id"] == "index_revision")
    assert check["status"] == "warn" and "cannot tell that a changed file still has old vectors" in check["detail"]
    assert "source_hash" in check["fix"]


def test_deletions_are_verified_without_a_manifest(tmp_path):
    docs = [doc("a"), doc("b")]
    points = [pt("a", 0), pt("b", 0), pt("b", 1)]
    svc = service(tmp_path, docs, points)
    svc.run_audit()
    svc.connectors.source.docs = [docs[0]]  # b is deleted from S3 ...
    report = svc.verify_deletions()  # ... and its vectors are still there
    [row] = report["documents"]
    assert row["verdict"] == "deletion_mismatch" and row["vectors"] == 2
    assert next(c for c in row["checks"] if c["check"] == "Manifest status")["result"] == "no manifest connected"
    svc.connectors.index.points = [p for p in points if p.document_id != "b"]  # the pipeline cleaned up
    [done] = svc.verify_deletions(documents=[(KEY, "b")], record=False)["documents"]
    assert done["verdict"] == "verified_deleted" and done["recommended_action"].endswith("gone from the source and the index.")


# ------------------------------------------------------------------------------------------------ the workspace settings
def rows(**groups):
    return {k: {"config": v.get("config", {}), "secrets": v.get("secrets", {})} for k, v in groups.items()}


S3 = {"config": {"bucket": "docs"}, "secrets": {"access_key_id": "AK", "secret_access_key": "SK"}}


def hosted(**kw) -> Settings:
    return Settings(_env_file=None, mode="app", allow_private_hosts=True, secret_key="k" * 40, **kw)


def test_an_audit_needs_only_the_source_and_the_vector_index_the_workspace_chose():
    assert required_kinds(None) == ("s3", "qdrant") and required_kinds("qdrant") == ("s3", "qdrant")
    assert required_kinds("pgvector") == ("s3", "pgvector") and required_kinds("PgVector") == ("s3", "pgvector")


def test_a_workspace_with_s3_and_qdrant_gets_connectors_without_a_manifest():
    ws = overlay(hosted(), rows(s3=S3, qdrant={"config": {"url": "https://qdrant.example.com:6333"}}))
    c = _factory(ws)
    assert isinstance(c.manifest, NoManifest) and isinstance(c.index, QdrantIndex) and c.manifest.available is False


def test_a_workspace_that_adds_a_manifest_gets_the_manifest_connector_too():
    ws = overlay(hosted(), rows(s3=S3, qdrant={"config": {"url": "https://q.example.com:6333"}},
                                manifest={"secrets": {"database_url": "postgresql://reader:pw@db.example.com:5432/postgres"}}))
    assert type(_factory(ws).manifest).__name__ == "PostgresManifest"


def test_a_workspace_that_chooses_pgvector_gets_the_pgvector_connector_and_needs_no_qdrant():
    ws = overlay(hosted(), rows(s3=S3, index={"config": {"type": "pgvector"}},
                                pgvector={"config": {"table": "chunks", "schema": "rag"},
                                          "secrets": {"database_url": "postgresql://reader:pw@db.example.com:5432/postgres"}}))
    c = _factory(ws)
    assert isinstance(c.index, PgVectorIndex) and c.index.name == "rag.chunks" and isinstance(c.manifest, NoManifest)


def test_setup_is_not_complete_until_the_chosen_index_is_connected():
    import pytest

    from ragintegrity.connectors.base import SetupIncomplete

    ws = overlay(hosted(), rows(s3=S3, index={"config": {"type": "pgvector"}}, qdrant={"config": {"url": "https://q.example.com:6333"}}))
    with pytest.raises(SetupIncomplete, match="pgvector index") as err:
        _factory(ws)  # Qdrant is configured, but this workspace chose pgvector: Qdrant does not count
    assert "manifest" not in str(err.value).lower()
    with pytest.raises(SetupIncomplete, match="Qdrant index"):
        _factory(overlay(hosted(), rows(s3=S3)))


def test_the_connectors_are_chosen_by_the_environment_in_the_single_user_modes_too():
    s = Settings(_env_file=None, mode="live", s3_bucket="b", pgvector_database_url="postgresql://r:p@db.example.com/x", pgvector_table="t",
                 index_type="pgvector")
    c = build_connectors(s)
    assert isinstance(c.index, PgVectorIndex) and isinstance(c.manifest, NoManifest)
    import pytest

    from ragintegrity.connectors.base import ConnectorError

    with pytest.raises(ConnectorError, match="RAGI_INDEX_TYPE must be qdrant or pgvector"):
        build_connectors(Settings(_env_file=None, mode="live", s3_bucket="b", index_type="pinecone"))


def test_the_settings_api_offers_the_index_choice_and_marks_only_what_an_audit_needs(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        signup(c)
        view = c.get("/api/settings").json()
        assert view["index_type"] == "qdrant" and view["missing"] == ["s3", "qdrant"]
        assert {k["kind"] for k in view["kinds"] if k["required_for_audit"]} == {"s3", "qdrant"}
        r = c.put("/api/settings/index", json={"values": {"type": "pgvector"}})
        assert r.status_code == 200 and r.json()["index_type"] == "pgvector" and r.json()["missing"] == ["s3", "pgvector"]
        assert {k["kind"] for k in r.json()["kinds"] if k["required_for_audit"]} == {"s3", "pgvector"}
        assert c.put("/api/settings/index", json={"values": {"type": "pinecone"}}).status_code == 422


def test_the_pgvector_settings_are_validated_encrypted_and_never_shown_again(tmp_path):
    c, *_ = make(tmp_path, allow_private_hosts=True)  # no DNS lookups in a test; the hosted-mode refusal is the next test
    with c:
        signup(c)
        url = "postgresql://reader:very-secret-pw@db.example.com:5432/postgres?sslmode=require"
        r = c.put("/api/settings/pgvector", json={"values": {"database_url": url, "table": "chunks", "distance": "l2",
                                                             "column_map": '{"document_id": "metadata.doc", "vector": "emb"}'}})
        assert r.status_code == 200 and "very-secret-pw" not in r.text
        group = next(k for k in r.json()["kinds"] if k["kind"] == "pgvector")
        fields = {f["name"]: f for f in group["fields"]}
        assert group["configured"] is True and fields["database_url"]["has_value"] is True and fields["database_url"]["value"] is None
        assert fields["table"]["value"] == "chunks" and fields["distance"]["value"] == "l2"
        for bad in ({"table": "chunks; DROP TABLE users"}, {"schema": "a b"}, {"distance": "manhattan"}, {"column_map": "[1,2]"},
                    {"database_url": "mysql://u:p@db.example.com/x"}):
            assert c.put("/api/settings/pgvector", json={"values": bad}).status_code == 422, bad


def test_the_hosted_app_refuses_a_pgvector_database_on_a_private_network(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        signup(c)
        for url in ("postgresql://u:p@127.0.0.1:5432/db", "postgresql://u:p@10.0.0.5:5432/db", "postgresql://u:p@localhost:5432/db"):
            r = c.put("/api/settings/pgvector", json={"values": {"database_url": url, "table": "chunks"}})
            assert r.status_code == 422 and "p@" not in r.text, url


def test_one_workspaces_pgvector_connection_never_reaches_another(tmp_path):
    from fastapi.testclient import TestClient

    c, app, settings = make(tmp_path, allow_private_hosts=True)
    with c:
        alice, bob = TestClient(c.app), TestClient(c.app)
        signup(alice, "alice@example.com")
        signup(bob, "bob@example.com")
        alice.put("/api/settings/pgvector", json={"values": {"database_url": "postgresql://reader:alice-pw@db.example.com:5432/x", "table": "alice_chunks"}})
        alice.put("/api/settings/index", json={"values": {"type": "pgvector"}})
        theirs = bob.get("/api/settings").json()
        assert theirs["index_type"] == "qdrant" and "alice_chunks" not in bob.get("/api/settings").text
        assert next(k for k in theirs["kinds"] if k["kind"] == "pgvector")["configured"] is False
