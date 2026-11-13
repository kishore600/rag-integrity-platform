"""Feature 1, document version integrity: the index must hold the CURRENT revision of every document.

Each test is one situation an engineer meets in production. The first is the example from the feature description:
employee_policy.pdf is v3 in the source, the pipeline reports success, the chunk count is right (24 of 24), and every
chunk still describes v2. Chunk ids alone cannot see that; the revision can.
"""

from __future__ import annotations

import pytest

from ragintegrity.engine.audit import AuditOptions, inspect_document, run_reconciliation
from ragintegrity.models import ChunkRow, Fingerprint, IndexedChunk, ManifestRow, SourceDoc
from tests.test_source_only import FakeManifest, FakeSource

DOC = "employee_policy.pdf"
V2, V3 = "2" * 64, "3" * 64


def source(version="v3", sha=V3) -> SourceDoc:
    return SourceDoc("default", DOC, f"s3://b/{DOC}", source_version=version, source_hash=sha, size_bytes=10)


def manifest_row(n=24, status="success", version="v3", sha=V3) -> ManifestRow:
    return ManifestRow("default", DOC, source_uri=f"s3://b/{DOC}", processing_status=status, source_hash=sha, indexed_version=version,
                       expected_chunk_count=n, indexed_chunk_count=n)


def chunk_rows(n, prefix="c", hashed=True) -> list[ChunkRow]:
    return [ChunkRow("default", DOC, f"{prefix}{i}", i, f"h{i:03d}" if hashed else None) for i in range(n)]


def point(i, *, sha=V3, ver="v3", chash=None, cid=None, tag="p", fp=None, idx=None) -> IndexedChunk:
    return IndexedChunk("c", f"{tag}-{i}", "default", DOC, chunk_id=cid or f"c{i}", chunk_index=i if idx is None else idx,
                        chunk_hash=chash, source_hash=sha, source_version=ver, fingerprint=fp or Fingerprint(),
                        present_fields=frozenset({"document_id"}))


class ChunkManifest(FakeManifest):
    has_chunk_manifest = True

    def __init__(self, rows, chunks):
        super().__init__(rows)
        self._chunks = list(chunks)

    def chunks(self, scope=None):
        return iter(self._chunks)


class Idx:
    def __init__(self, points):
        self.points = list(points)

    def collections(self):
        return ["c"]

    def vector_sizes(self):
        return {"c": 3}

    def scan(self, scope=None, with_vectors=False):
        return iter(p for p in self.points if scope is None or scope.is_full or scope.matches((p.tenant_id, p.document_id)))

    def probe(self, *a, **k):
        return None


def audit(points, *, src=None, row=None, chunks=None, target=None):
    src = src if src is not None else source()
    man = ChunkManifest([row if row is not None else manifest_row()], chunks) if chunks is not None else FakeManifest(
        [row if row is not None else manifest_row()])
    opts = AuditOptions(target=target, probe=False, required_fields=["document_id"])
    return run_reconciliation(FakeSource([src]), man, Idx(points), opts), (FakeSource([src]), man, Idx(points), opts)


def types(result):
    return sorted(f.type.value for f in result.findings)


def table(parts):
    src, man, idx, opts = parts
    return inspect_document(src, man, idx, opts, "default", DOC)["version_check"]


def row_of(vc, prop):
    return next(r for r in vc["rows"] if r["property"] == prop)


# ------------------------------------------------------------------------------------- the example from the feature description
def test_24_chunks_exist_and_the_count_is_right_but_they_belong_to_an_outdated_revision():
    points = [point(i, sha=V2, ver="v2") for i in range(24)]
    result, parts = audit(points, chunks=chunk_rows(24))
    assert types(result) == ["stale_embedding"]
    [f] = result.findings
    assert f.severity.value == "high" and f.evidence["indexed_versions"] == ["v2"] and f.evidence["pipeline_reported_success"] is True
    assert f.evidence["outdated_points"] == 24 and f.evidence["removal_count"] == 24

    vc = table(parts)
    assert vc["verdict"] == "version_mismatch" and vc["title"] == "Version mismatch"
    assert "24 chunk(s) exist in the index (24 expected), but they belong to an outdated revision" in vc["explanation"]
    assert (row_of(vc, "Source version")["expected"], row_of(vc, "Source version")["actual"], row_of(vc, "Source version")["status"]) == (
        "v3", "v2", "mismatch")
    assert row_of(vc, "Source hash")["status"] == "mismatch"
    count = row_of(vc, "Chunk count (any revision)")
    assert (count["expected"], count["actual"], count["status"]) == (24, 24, "match")  # the trap: the count alone looks fine
    current = row_of(vc, "Chunks of the current revision")
    assert (current["expected"], current["actual"], current["status"]) == (24, 0, "mismatch")
    assert "0 of 24 expected found in the current revision" in row_of(vc, "Chunk IDs")["actual"]
    assert vc["points_by_revision"] == {"current": 0, "older_revision": 24, "older_config": 0, "revision_unknown": 0}


def test_a_healthy_document_is_in_sync_row_by_row():
    points = [point(i, chash=f"h{i:03d}") for i in range(24)]
    result, parts = audit(points, chunks=chunk_rows(24))
    assert result.findings == []
    vc = table(parts)
    assert vc["verdict"] == "in_sync" and vc["explanation"] == "The index holds the current revision of the document."
    assert {r["status"] for r in vc["rows"]} == {"match"}
    assert row_of(vc, "Chunk hashes")["actual"] == "24 of 24 chunks match"


# ------------------------------------------------------------------------------------- a new revision next to an old one
def test_the_same_chunk_ids_in_two_revisions_flag_exactly_the_old_points():
    new = [point(i, tag="new") for i in range(24)]
    old = [point(i, sha=V2, ver="v2", tag="old") for i in range(12)]  # an older worker wrote c0..c11 again, under the same chunk ids
    result, parts = audit(new + old, chunks=chunk_rows(24))
    assert types(result) == ["superseded_active"]
    [f] = result.findings
    assert sorted(f.evidence["removal_points"]["c"]) == sorted(p.point_id for p in old) and f.evidence["removal_count"] == 12
    vc = table(parts)
    assert vc["verdict"] == "partly_outdated" and "12 vectors from an older revision" in vc["explanation"]
    assert row_of(vc, "Chunk IDs")["status"] == "match" and row_of(vc, "Source version")["status"] == "partial"


def test_re_indexing_in_place_under_the_same_point_ids_leaves_nothing_behind():
    points = [point(i, chash=f"h{i:03d}") for i in range(24)]  # the new revision overwrote the old points
    result, _ = audit(points, chunks=chunk_rows(24))
    assert result.findings == [] and [s.status for s in result.summaries] == ["healthy"]


# ------------------------------------------------------------------------------------- the document got shorter
def test_the_old_tail_of_a_shorter_document_is_found_when_the_payload_knows_the_revision():
    points = [point(i, tag="new") for i in range(20)] + [point(i, sha=V2, ver="v2", tag="tail") for i in range(20, 24)]
    result, _ = audit(points, row=manifest_row(20), chunks=chunk_rows(20))
    assert types(result) == ["superseded_active"]
    assert result.findings[0].evidence["removal_count"] == 4


def test_the_old_tail_is_found_even_when_the_payload_says_nothing_about_the_revision():
    points = [point(i, sha=None, ver=None, tag="p") for i in range(24)]  # no revision metadata at all
    result, parts = audit(points, row=manifest_row(20, sha=None, version=None), chunks=chunk_rows(20, hashed=False))
    [f] = result.findings
    assert f.type.value == "superseded_active" and f.title == "Chunks the current version no longer has are still active"
    assert f.evidence["unexpected_chunk_count"] == 4 and f.evidence["expected_chunks"] == 20 and f.evidence["method"] == "chunk_manifest"
    assert sorted(f.evidence["removal_points"]["c"]) == [f"p-{i}" for i in range(20, 24)] and f.action.value == "cleanup_vectors"
    vc = table(parts)
    assert "4 not in the current version" in row_of(vc, "Chunk IDs")["actual"]


def test_the_old_tail_is_found_from_the_expected_chunk_count_when_there_is_no_chunk_manifest():
    points = [point(i, sha=None, ver=None) for i in range(24)]
    result, _ = audit(points, row=manifest_row(20, sha=None, version=None), src=source(None, None))
    [f] = result.findings
    assert f.type.value == "superseded_active" and f.evidence["method"] == "expected_chunk_count"
    assert f.evidence["unexpected_chunk_count"] == 4
    exact = audit(points[:20], row=manifest_row(20, sha=None, version=None), src=source(None, None))[0]
    assert exact.findings == []  # exactly as many chunks as expected: nothing left over


def test_old_revision_and_left_over_chunks_in_one_document_are_one_issue_not_two():
    points = ([point(i, tag="new") for i in range(20)]
              + [point(i, sha=V2, ver="v2", tag="old") for i in range(5)]
              + [point(i, sha=None, ver=None, tag="tail") for i in range(20, 24)])
    result, _ = audit(points, row=manifest_row(20), chunks=chunk_rows(20))
    [f] = result.findings
    assert f.type.value == "superseded_active"
    assert f.evidence["removal_count"] == 9 and f.evidence["unexpected_chunk_count"] == 4
    assert "4 more chunk(s) are not part of the current version" in f.detail
    assert len({x.issue_id for x in result.findings}) == len(result.findings)


# ------------------------------------------------------------------------------------- chunk hashes: the revision of the text itself
def test_when_the_document_revision_is_unknown_a_different_chunk_hash_is_the_evidence_it_is_stale():
    points = [point(i, sha=None, ver=None, chash=f"old{i:03d}") for i in range(24)]
    result, parts = audit(points, row=manifest_row(24, sha=None, version=None), chunks=chunk_rows(24))
    assert types(result) == ["stale_embedding"]
    ev = result.findings[0].evidence
    assert ev["stale_by"] == "chunk_hash" and ev["chunk_hash_examples"][0] == {"chunk_id": "c0", "expected": "h000", "indexed": "old000"}
    assert table(parts)["verdict"] == "version_mismatch"


def test_when_the_document_hash_says_current_a_different_chunk_hash_is_a_metadata_problem_not_staleness():
    points = [point(i, chash=f"x{i:03d}") for i in range(24)]
    result, parts = audit(points, chunks=chunk_rows(24))
    [f] = result.findings
    assert f.type.value == "metadata_inconsistent" and f.severity.value == "medium"
    [problem] = f.evidence["problems"]
    assert problem["code"] == "chunk_hash_mismatch" and "24 of 24 chunks carry a different chunk hash" in problem["message"]
    assert row_of(table(parts), "Chunk hashes")["status"] == "mismatch"


def test_chunk_hashes_that_match_are_silent():
    result, _ = audit([point(i, chash=f"h{i:03d}") for i in range(24)], chunks=chunk_rows(24))
    assert result.findings == []


# ------------------------------------------------------------------------------------- the same hash written differently
@pytest.mark.parametrize("written", [V3.upper(), f"sha256:{V3}", f"SHA256:{V3.upper()}", f' "{V3}" ', f"sha-256={V3}"])
def test_a_hash_is_the_same_hash_however_it_is_spelled(written):
    points = [point(i, sha=written) for i in range(24)]
    result, parts = audit(points, row=manifest_row(24, sha=written), chunks=chunk_rows(24))
    assert result.findings == []  # not stale, and the manifest does not lag
    assert row_of(table(parts), "Source hash")["status"] == "match"


def test_chunk_hashes_are_compared_by_value_too():
    points = [point(i, chash=f"SHA256:{f'h{i:03d}'.upper()}") for i in range(24)]
    assert audit(points, chunks=chunk_rows(24))[0].findings == []


# ------------------------------------------------------------------------------------- the pipeline configuration changed
OLD_CFG = Fingerprint(chunking_version="v1", chunk_size=1000, embedding_model="embed-a")
NEW_CFG = Fingerprint(chunking_version="v2", chunk_size=512, embedding_model="embed-a")


def test_a_changed_chunking_configuration_marks_every_old_chunk_as_built_the_old_way():
    points = [point(i, fp=OLD_CFG) for i in range(24)]
    result, parts = audit(points, chunks=chunk_rows(24), target=NEW_CFG)
    [f] = result.findings
    assert f.type.value == "pipeline_drift" and f.severity.value == "medium"  # the embedding space did not change
    assert set(f.evidence["differences"]) == {"chunking_version", "chunk_size"} and f.action.value == "reindex_full"
    vc = table(parts)
    assert vc["verdict"] == "config_changed" and "chunking_version" in vc["explanation"]
    size = row_of(vc, "Chunk size")
    assert (size["expected"], size["actual"], size["status"]) == (512, "1000", "mismatch")


def test_a_changed_embedding_model_is_a_high_severity_drift():
    fp = Fingerprint(embedding_model="embed-a", embedding_model_version="1")
    target = Fingerprint(embedding_model="embed-a", embedding_model_version="2")
    result, _ = audit([point(i, fp=fp) for i in range(6)], row=manifest_row(6), chunks=chunk_rows(6), target=target)
    assert [(f.type.value, f.severity.value) for f in result.findings] == [("pipeline_drift", "high")]


def test_half_way_through_a_re_chunking_the_old_chunks_are_reported_as_superseded_vectors():
    new = [point(i, fp=NEW_CFG, tag="new") for i in range(10)]
    old = [point(i, fp=OLD_CFG, tag="old", cid=f"old{i}") for i in range(24)]
    result, parts = audit(new + old, row=manifest_row(10), chunks=chunk_rows(10), target=NEW_CFG)
    [f] = result.findings
    assert f.type.value == "superseded_active" and f.evidence["outdated_config_points"] == 24
    assert sorted(f.evidence["removal_points"]["c"]) == sorted(p.point_id for p in old)
    assert table(parts)["verdict"] == "partly_outdated"


def test_chunks_of_one_document_built_with_different_settings_are_reported_without_any_target():
    points = [point(i, fp=Fingerprint(chunk_size=500 if i % 2 else 1000)) for i in range(8)]
    result, parts = audit(points, row=manifest_row(8), chunks=chunk_rows(8))
    [f] = result.findings
    assert f.type.value == "pipeline_drift" and f.evidence["varying_fields"] == ["chunk_size"]
    assert row_of(table(parts), "Chunk size")["status"] == "mismatch"


# ------------------------------------------------------------------------------------- what cannot be known, and what is gone
def test_without_any_revision_information_the_check_says_so_instead_of_guessing():
    points = [point(i, sha=None, ver=None) for i in range(24)]
    result, parts = audit(points, row=manifest_row(24, sha=None, version=None), src=source(None, None), chunks=chunk_rows(24, hashed=False))
    assert result.findings == []
    vc = table(parts)
    assert vc["verdict"] == "unknown_revision" and "cannot be verified" in vc["explanation"]


def test_a_document_without_vectors_and_a_document_without_a_source_have_their_own_verdicts():
    _, parts = audit([], chunks=chunk_rows(24))
    assert table(parts)["verdict"] == "not_indexed"
    src, man, idx, opts = parts
    gone = inspect_document(FakeSource([]), man, Idx([point(i) for i in range(3)]), opts, "default", DOC)["version_check"]
    assert gone["verdict"] == "source_missing" and gone["rows"] == []
