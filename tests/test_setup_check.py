"""The setup and coverage check: do S3, the manifest and Qdrant call the same documents by the same ID?

Most of these tests judge hand-made facts (so every verdict, number and hint is pinned down), then a few read real
S3 (moto), a real table and a real Qdrant server to prove the look is cheap, read-only and bounded.
"""

from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sqlalchemy import create_engine, text

from ragintegrity.config import Settings
from ragintegrity.connectors.base import AuditTimeout, ConnectorError
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.engine import coverage
from ragintegrity.engine.coverage import SetupFacts, Unique, build_setup_report, collect_setup_facts, to_text
from ragintegrity.models import ManifestRow
from tests.test_app_mode import make, signup
from tests.test_service import make_service


# ------------------------------------------------------------------------------------- building facts by hand
def facts(src=None, man=None, index=None, *, found=None, asked=None, tenant="default", **kw) -> SetupFacts:
    """``src``/``man``: document ids (strings) on each side. ``index``: ids as the index stores them (numbers allowed).
    ``found``: of the ``asked`` S3 documents, the ones that have pieces in the index."""
    f = SetupFacts(**kw)
    if src is not None:
        f.source = Unique(lambda key: key)
        for d in src:
            f.source.add((tenant, d), f"bills/{d}.pdf")
        f.source_objects = len(src) + f.source_ignored
    if man is not None:
        f.manifest = Unique(lambda r: r.source_uri or "row")
        for d in man:
            f.manifest.add((tenant, d), ManifestRow(tenant, d, source_uri=f"s3://b/bills/{d}.pdf"))
        f.manifest_rows = len(man)
    if index is not None:
        f.index_rows = [{"document_id": d, "tenant_id": None} for d in index]
        f.index_approx_points = 3_900_000
    if asked is not None:
        f.lookup_index_asked_keys = [(tenant, d) for d in asked]
        f.lookup_index_asked = len(asked)
        f.lookup_index_found = {(tenant, d) for d in (found or [])}
    return f


def check(report, cid):
    return next(c for c in report["checks"] if c["id"] == cid)


def ids(n, prefix=""):
    return [f"{prefix}{1000 + i}" for i in range(n)]


def aligned(n=50):
    return facts(ids(n), ids(n), ids(n), asked=ids(n), found=ids(n))


# ------------------------------------------------------------------------------------- the verdicts
def test_when_everything_lines_up_the_check_says_ready():
    r = build_setup_report(aligned())
    assert r["status"] == "ready" and r["headline"].startswith("Ready") and r["next_steps"] == []
    assert {c["status"] for c in r["checks"]} == {"pass"}
    assert r["coverage"]["source_to_manifest"] == {"matched": 50, "of": 50, "percent": 100}
    assert r["coverage"]["source_to_index"]["percent"] == 100
    assert r["counts"]["source_documents"] == 50 and r["counts"]["index_points_approx"] == 3_900_000
    assert r["ids_at_a_glance"]["source"] == ["1000", "1001", "1002", "1003", "1004"]


def test_ids_with_an_extra_prefix_fail_and_say_what_to_do():
    r = build_setup_report(facts(ids(50), ids(50, "bill-"), ids(50, "bill-"), asked=ids(50), found=[]))
    c = check(r, "source_vs_manifest")
    assert r["status"] == "not_ready" and c["status"] == "fail" and c["numbers"] == {"matched": 0, "of": 50}
    assert c["examples"][0].startswith("in S3 only: '1000'") and "in the manifest only: 'bill-1000'" in c["examples"][1]
    assert "extra prefix or suffix" in c["hint"] and "'1000' and manifest 'bill-1000'" in c["hint"] and "clean-up rule" in c["hint"]
    assert "key pattern" in c["fix"] and c["fix"] in r["next_steps"]
    assert r["headline"].startswith("Not ready yet") and "Start with 'S3 against the manifest'" in r["headline"]


def test_ids_that_differ_only_by_leading_zeros_or_case_are_pointed_out_but_not_guessed():
    r = build_setup_report(facts(["0170", "0171", "ABC"], ["170", "171", "abc"]))
    c = check(r, "source_vs_manifest")
    assert c["status"] == "fail" and "same document written differently" in c["hint"] and "'0170' and manifest '170'" in c["hint"]
    assert "compares IDs exactly" in c["hint"]  # it does not silently match them


def test_most_documents_matching_passes_some_warns_and_hardly_any_fails():
    n = 100
    for matched, verdict in ((97, "pass"), (80, "pass"), (79, "warn"), (20, "warn"), (19, "fail"), (0, "fail")):
        c = check(build_setup_report(facts(ids(n), ids(n)[:matched] + ids(n - matched, "x"))), "source_vs_manifest")
        assert c["status"] == verdict, (matched, c["status"])  # the gaps in a pass are what the audit reports one by one
    assert "80 of 100 (80%)" in check(build_setup_report(facts(ids(n), ids(n)[:80] + ids(20, "x"))), "source_vs_manifest")["detail"]


def test_a_manifest_that_covers_more_than_the_bucket_is_a_warning_not_a_failure_and_source_only_silences_it():
    f = facts(ids(10), ids(10) + ids(90, "x"))
    r = build_setup_report(f)
    c = check(r, "manifest_vs_source")
    assert c["status"] == "warn" and "Only audit documents found in the source" in c["fix"] and "10 of 100" in c["detail"]
    f.source_only = True
    assert check(build_setup_report(f), "manifest_vs_source")["status"] == "pass"


def test_the_same_ids_under_different_tenant_names_are_called_out_as_the_cause():
    f = facts(ids(30), ids(30), ids(30))
    f.index_rows = [{"document_id": d, "tenant_id": "acme"} for d in ids(30)]  # the index writes tenant 'acme', the others 'default'
    r = build_setup_report(f)
    c = check(r, "tenant_labels")
    assert c["status"] == "fail" and "'acme'" in c["detail"] and "'default'" in c["detail"]
    assert "same document IDs exist" in c["hint"] and "tenant" in c["fix"].lower()


def test_an_index_sample_that_shows_only_some_of_the_tenants_is_fine():
    f = SetupFacts()
    f.source, f.manifest = Unique(lambda k: k), Unique(lambda r: "r")
    for t in ("acme", "globex", "initech"):
        for d in ids(5):
            f.source.add((t, d), "k")
            f.manifest.add((t, d), ManifestRow(t, d))
    f.index_rows = [{"document_id": d, "tenant_id": "acme"} for d in ids(5)]  # a sample may not reach every tenant
    assert check(build_setup_report(f), "tenant_labels")["status"] == "pass"


# ------------------------------------------------------------------------------------- each system on its own
def test_a_bucket_that_cannot_be_read_is_reported_and_the_rest_still_runs():
    f = facts(None, ids(5), ids(5), source_error="Access denied: the key needs s3:ListBucket.")
    r = build_setup_report(f)
    assert check(r, "source_files")["status"] == "fail" and "s3:ListBucket" in check(r, "source_files")["detail"]
    assert check(r, "manifest_rows")["status"] == "pass" and check(r, "index_ids")["status"] == "pass"
    assert r["status"] == "not_ready" and r["coverage"]["source_to_manifest"] is None


def test_an_empty_prefix_and_a_pattern_that_matches_nothing_are_told_apart():
    empty = build_setup_report(facts(None, None, None))
    assert check(empty, "source_files")["status"] == "fail" and "No files were found" in check(empty, "source_files")["detail"]
    f = facts([], ids(3))
    f.source_objects, f.source_ignored, f.ignored_examples = 20, 20, ["bills/readme.txt", "bills/x/y.pdf"]
    f.names = {"key_pattern": r"^(?P<document_id>\d+)\.pdf$"}
    c = check(build_setup_report(f), "source_files")
    assert c["status"] == "fail" and "none of their names match the key pattern" in c["detail"]
    assert c["examples"] == ["bills/readme.txt", "bills/x/y.pdf"] and "(?P<document_id>" in c["hint"]


def test_files_that_do_not_match_the_pattern_are_skipped_quietly_unless_it_misses_most_of_them():
    some = facts(ids(100), ids(100))
    some.source_objects, some.source_ignored = 150, 50  # a third: a pattern that selects some files (the bills layout) is normal
    c = check(build_setup_report(some), "source_files")
    assert c["status"] == "pass" and "50 file(s) do not match" in c["detail"] and "meant to select only some" in c["detail"]
    most = facts(ids(100), ids(100))
    most.source_objects, most.source_ignored = 250, 150
    c = check(build_setup_report(most), "source_files")
    assert c["status"] == "warn" and "Most files do not match" in c["fix"]


def test_the_manifest_problems_are_each_named():
    assert check(build_setup_report(facts(manifest_error="Authentication failed")), "manifest_rows")["status"] == "fail"
    empty = facts(ids(3), [])
    assert "no rows" in check(build_setup_report(empty), "manifest_rows")["detail"]
    blank = facts(ids(3), [], manifest_empty_ids=4)
    blank.manifest_rows = 4
    assert "empty document ID" in check(build_setup_report(blank), "manifest_rows")["detail"]
    some = facts(ids(10), ids(10), manifest_empty_ids=2)
    c = check(build_setup_report(some), "manifest_rows")
    assert c["status"] == "warn" and "2 row(s) have no document ID" in c["detail"]


def test_duplicate_ids_warn_when_few_and_fail_when_many():
    few = facts(ids(100), ids(100))
    few.source.add(("default", "1001"), "other/1001.pdf")  # 1 of 100 ids is on two files
    c = check(build_setup_report(few), "source_ids_unique")
    assert c["status"] == "warn" and "'1001' is bills/1001.pdf and other/1001.pdf" in c["detail"]
    many = facts(ids(10), ids(10))
    for d in ids(10)[:3]:
        many.source.add(("default", d), f"copy/{d}.pdf")
    assert check(build_setup_report(many), "source_ids_unique")["status"] == "fail"
    man = facts(ids(100), ids(100))
    man.manifest.add(("default", "1000"), ManifestRow("default", "1000", source_uri="s3://b/again"))
    mc = check(build_setup_report(man), "manifest_ids_unique")
    assert mc["status"] == "warn" and "'1000' has 2" in mc["detail"] and mc["examples"] == ["1000 (2 rows)"]
    assert check(build_setup_report(aligned()), "source_ids_unique")["status"] == "pass"


def test_the_index_checks_name_the_payload_field_and_how_ids_are_stored():
    named = {"payload_document_id": "source_id"}
    nothing = build_setup_report(facts(ids(3), ids(3), [None, None, ""], names=named))
    c = check(nothing, "index_ids")
    assert c["status"] == "fail" and "'source_id'" in c["detail"] and "payload map" in c["fix"]
    assert "empty" in check(build_setup_report(facts(ids(3), ids(3), [])), "index_ids")["detail"]
    assert check(build_setup_report(facts(ids(3), ids(3), index=None, index_error="Qdrant rejected the API key")), "index_ids")["status"] == "fail"

    numbers = check(build_setup_report(facts(ids(5), ids(5), [int(d) for d in ids(5)])), "index_ids")
    assert numbers["status"] == "pass" and "5 stored as numbers" in numbers["detail"] and "treated as the same ID" in numbers["detail"]

    decimals = check(build_setup_report(facts(ids(5), ids(5), [float(d) for d in ids(5)], source_only=True)), "index_ids")
    assert decimals["status"] == "warn" and "2329961.0" in decimals["detail"] and "cannot filter" in decimals["detail"]

    mixed = check(build_setup_report(facts(ids(4), ids(4), [1000, 1001, "1002", "1003"])), "index_ids")
    assert mixed["status"] == "warn" and "two writers" in mixed["detail"]

    partial = check(build_setup_report(facts(ids(4), ids(4), ids(3) + [None] * 3)), "index_ids")
    assert partial["status"] == "warn" and "no 'document_id'" in partial["fix"]


def test_s3_documents_that_have_no_pieces_under_their_id_fail_with_both_id_styles_shown():
    r = build_setup_report(facts(ids(40), ids(40), ids(40, "bill-"), asked=ids(40), found=[]))
    c = check(r, "source_vs_index")
    assert c["status"] == "fail" and c["numbers"] == {"matched": 0, "of": 40}
    assert c["examples"][0].startswith("not found in Qdrant: '1000'") and "IDs Qdrant uses: 'bill-1000'" in c["examples"][1]
    assert "extra prefix or suffix" in c["hint"]
    assert check(build_setup_report(aligned()), "source_vs_index")["status"] == "pass"
    for found, verdict in ((34, "pass"), (30, "warn"), (8, "warn"), (7, "fail")):  # 80% and up: the IDs line up, a few are not indexed yet
        r = build_setup_report(facts(ids(40), ids(40), ids(40), asked=ids(40), found=ids(40)[:found]))
        assert check(r, "source_vs_index")["status"] == verdict, found
    few_missing = check(build_setup_report(facts(ids(40), ids(40), ids(40), asked=ids(40), found=ids(40)[:30])), "source_vs_index")
    assert "may not be indexed yet" in few_missing["fix"] and "Most S3 documents" not in few_missing["fix"]


def test_a_lookup_that_could_not_finish_is_a_warning_with_a_way_forward():
    f = facts(ids(10), ids(10), ids(10), asked=ids(10), found=[], lookup_index_error="Qdrant timed out.")
    c = check(build_setup_report(f), "source_vs_index")
    assert c["status"] == "warn" and "timed out" in c["detail"] and "keyword index" in c["fix"]


def test_an_index_full_of_other_sources_is_explained_and_source_only_silences_it():
    f = facts(ids(10), ids(10), ids(10) + ids(90, "z"))
    c = check(build_setup_report(f), "index_vs_source")
    assert c["status"] == "warn" and "10 of 100" in c["detail"] and "Only audit documents found in the source" in c["fix"]
    assert "about 3,900,000 points" in c["detail"] and c["examples"][0].startswith("not in S3 or the manifest: 'z1000'")
    f.source_only = True
    quiet = check(build_setup_report(f), "index_vs_source")
    assert quiet["status"] == "pass" and "is on, so they are ignored" in quiet["detail"]


def test_lookup_mode_checks_a_sample_of_the_manifests_files_and_warns_about_the_blind_spot():
    f = facts(None, ids(10), ids(10), lookup_mode=True, lookup_asked=10, lookup_found=10)
    r = build_setup_report(f)
    assert check(r, "source_files")["status"] == "na" and check(r, "manifest_files_exist")["status"] == "pass"
    assert check(r, "lookup_blind_spot")["status"] == "warn" and "never got a manifest row" in check(r, "lookup_blind_spot")["detail"]
    f.lookup_found, f.lookup_missing = 1, ["bills/gone.pdf"]
    gone = check(build_setup_report(f), "manifest_files_exist")
    assert gone["status"] == "fail" and gone["examples"] == ["bills/gone.pdf"]
    f.lookup_asked = 0
    f.manifest_without_uri = 10
    nouri = check(build_setup_report(f), "manifest_files_exist")
    assert nouri["status"] == "fail" and "source URI" in nouri["fix"] and "10 manifest row(s) have no source address" in nouri["hint"]


def test_a_cut_short_listing_says_so():
    f = aligned()
    f.source_truncated, f.manifest_truncated, f.index_random = True, True, False
    limits = build_setup_report(f)["limits"]
    assert len(limits) == 3 and f"{coverage.MAX_SOURCE_OBJECTS:,}" in limits[0] and "first points" in limits[2]
    partial = facts(ids(100), ids(60), source_truncated=True)
    assert "were cut short" in check(build_setup_report(partial), "source_vs_manifest")["detail"]


def test_a_few_unmatched_documents_make_the_headline_say_almost_ready():
    r = build_setup_report(facts(ids(100), ids(100)[:60], ids(100)))
    assert r["status"] == "needs_attention" and r["headline"].startswith("Almost ready")
    assert r["next_steps"] and all(isinstance(s, str) for s in r["next_steps"])


def test_the_text_version_lists_every_check_with_its_fix():
    out = to_text(build_setup_report(facts(ids(10), ids(10, "bill-"), ids(10, "bill-"), asked=ids(10), found=[])))
    assert out.startswith("Not ready yet") and "[FAIL] S3 against the manifest" in out and "fix :" in out and "note:" in out


# ------------------------------------------------------------------------------------- reading real systems
class SpyS3:
    """Records which S3 operations are used: the check must only list and HEAD, never download."""

    def __init__(self, inner):
        self.inner, self.used = inner, set()

    def __getattr__(self, name):
        self.used.add(name)
        return getattr(self.inner, name)


@pytest.fixture()
def bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        for i in range(1005):  # more than one page of 1,000
            s3.put_object(Bucket="docs", Key=f"bills/{1000 + i}.pdf", Body=b"%PDF")
        s3.put_object(Bucket="docs", Key="bills/readme.txt", Body=b"hi")
        s3.put_object(Bucket="docs", Key="bills/folder/", Body=b"")
        yield s3


def s3_settings(**kw):
    return Settings(_env_file=None, s3_bucket="docs", s3_region="us-east-1", s3_prefix="bills/", s3_hash_mode="compute",
                    s3_key_pattern=r"^(?P<document_id>[0-9]+)\.pdf$", **kw)


def manifest_table(tmp_path, ids_):
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE manifest (document_id TEXT, source_uri TEXT, processing_status TEXT)"))
        for d in ids_:
            c.execute(text("INSERT INTO manifest VALUES (:d, :u, 'success')"), {"d": d, "u": f"s3://docs/bills/{d}.pdf"})
    return PostgresManifest(Settings(_env_file=None, manifest_table="manifest"), engine)


class IdSampleIndex:
    """An index that can sample: ids exactly as stored."""

    def __init__(self, stored, per_doc=2):
        self.stored, self.per_doc = stored, per_doc
        self.deadline = None
        self.scopes = []

    def id_sample(self, limit):
        return {"rows": [{"document_id": d, "tenant_id": None} for d in self.stored][:limit], "random": True,
                "approx_points": len(self.stored) * self.per_doc, "collections": ["c"]}

    def scan(self, scope=None, with_vectors=False):
        from ragintegrity.models import IndexedChunk

        self.scopes.append(scope)
        want = {k[1] for k in scope.keys} if scope and scope.keys else None
        for d in self.stored:
            if want is None or str(d) in want:
                yield IndexedChunk("c", f"p{d}", None, str(d))


def test_the_look_lists_names_only_and_never_downloads_or_hashes(bucket, tmp_path):
    spy = SpyS3(bucket)
    source = S3Source(s3_settings(), client=spy)
    stored = [1000 + i for i in range(1005)]
    f = collect_setup_facts(source, manifest_table(tmp_path, [str(d) for d in stored]), IdSampleIndex(stored), None)
    r = build_setup_report(f)
    assert spy.used == {"get_paginator"}  # (hash mode is 'compute' here: an audit would download every file)
    assert f.source_objects == 1006 and f.source_ignored == 1 and f.ignored_examples == ["bills/readme.txt"]  # folder marker not counted
    assert len(f.source.items) == 1005 and r["counts"]["source_documents"] == 1005
    assert r["status"] == "ready", [(c["id"], c["status"], c["detail"]) for c in r["checks"] if c["status"] != "pass"]
    assert check(r, "index_ids")["status"] == "pass" and "stored as numbers" in check(r, "index_ids")["detail"]


def test_the_index_is_asked_about_a_sample_of_documents_not_all_of_them(bucket, tmp_path):
    stored = [1000 + i for i in range(1005)]
    idx = IdSampleIndex(stored)
    collect_setup_facts(S3Source(s3_settings(), client=bucket), manifest_table(tmp_path, [str(d) for d in stored]), idx, None)
    [scope] = idx.scopes
    assert len(scope.keys) == coverage.INDEX_LOOKUP_DOCS and {k[1] for k in scope.keys} <= {str(d) for d in stored}


def test_lookup_mode_heads_only_the_files_the_manifest_names(bucket, tmp_path):
    spy = SpyS3(bucket)
    ids_ = [str(1000 + i) for i in range(30)] + ["9999"]  # 9999 has a manifest row but no file
    f = collect_setup_facts(S3Source(s3_settings(), client=spy), manifest_table(tmp_path, ids_), IdSampleIndex(ids_), None,
                            lookup_mode=True)
    assert spy.used == {"head_object"} and (f.lookup_asked, f.lookup_found) == (31, 30)
    assert f.lookup_missing == ["bills/9999.pdf"]
    r = build_setup_report(f)
    assert check(r, "manifest_files_exist")["status"] == "pass" and check(r, "lookup_blind_spot")["status"] == "warn"


def test_a_system_that_fails_is_a_result_and_the_others_are_still_read(bucket, tmp_path):
    class Broken:
        has_chunk_manifest = False

        def documents(self, scope=None):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    f = collect_setup_facts(S3Source(s3_settings(), client=bucket), Broken(), IdSampleIndex([1000]), None,
                            explain=lambda e: f"explained: {e}")
    assert f.manifest_error == "explained: boom" and f.source_error is None and f.index_error is None
    assert check(build_setup_report(f), "manifest_rows")["detail"] == "Could not read the manifest: explained: boom"


def test_running_out_of_time_is_said_in_the_checks_own_words(bucket, tmp_path):
    class Slow:
        has_chunk_manifest = False

        def documents(self, scope=None):
            raise AuditTimeout("The audit ran out of time while reading the processing manifest.")
            yield  # pragma: no cover

    f = collect_setup_facts(S3Source(s3_settings(), client=bucket), Slow(), IdSampleIndex([1000]), None)
    assert "ran out of time" in f.manifest_error


def test_a_huge_bucket_is_cut_short_and_says_so(bucket, tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "MAX_SOURCE_OBJECTS", 50)
    monkeypatch.setattr(coverage, "MAX_MANIFEST_ROWS", 20)
    f = collect_setup_facts(S3Source(s3_settings(), client=bucket), manifest_table(tmp_path, [str(1000 + i) for i in range(30)]),
                            IdSampleIndex([1000]), None)
    assert f.source_truncated and f.source_objects == 50 and f.manifest_truncated and f.manifest_rows == 20
    assert len(build_setup_report(f)["limits"]) == 2


# ------------------------------------------------------------------------------------- the real Qdrant server
URL, KEY = os.environ.get("RAGI_TEST_QDRANT_URL"), os.environ.get("RAGI_TEST_QDRANT_KEY")


@pytest.fixture()
def small_bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        for i in range(60):
            s3.put_object(Bucket="docs", Key=f"bills/{1000 + i}.pdf", Body=b"%PDF")
        yield s3


@pytest.mark.skipif(not URL, reason="RAGI_TEST_QDRANT_URL not set")
@pytest.mark.parametrize("stored_as, expected", [("number", "ready"), ("text", "ready"), ("prefixed", "not_ready")])
def test_a_whole_check_against_real_s3_a_real_table_and_a_real_qdrant(small_bucket, tmp_path, stored_as, expected):
    client = QdrantClient(url=URL, api_key=KEY, timeout=30)
    name = "ragi_test_setup_check"
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(name, vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    stored = [1000 + i for i in range(60)]
    value = {"number": lambda d: d, "text": str, "prefixed": lambda d: f"bill-{d}"}[stored_as]
    try:
        client.upsert(name, wait=True, points=[qm.PointStruct(id=i + 1, vector=[1, 0, 0], payload={"source_id": value(d)})
                                              for i, d in enumerate(stored)])
        index = QdrantIndex(Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY, qdrant_collections=name,
                                     qdrant_payload_map='{"document_id": "source_id"}'))
        f = collect_setup_facts(S3Source(s3_settings(), client=small_bucket), manifest_table(tmp_path, [str(d) for d in stored]), index,
                                None, names={"payload_document_id": "source_id"})
        r = build_setup_report(f)
        assert r["status"] == expected, [(c["id"], c["status"], c["detail"]) for c in r["checks"] if c["status"] != "pass"]
        assert r["counts"]["index_points_sampled"] == 60 and r["counts"]["index_points_approx"] == 60
        if stored_as == "number":
            assert "60 stored as numbers" in check(r, "index_ids")["detail"]
            assert check(r, "source_vs_index")["numbers"] == {"matched": 60, "of": 60}  # the real number filter found them all
        if stored_as == "prefixed":
            assert check(r, "source_vs_index")["status"] == "fail" and "'bill-1000'" in check(r, "source_vs_index")["examples"][1]
    finally:
        client.delete_collection(name)


# ------------------------------------------------------------------------------------- service and API
def test_the_service_checks_the_demo_world(tmp_path):
    svc = make_service(tmp_path)
    r = svc.setup_check()
    assert r["status"] in ("ready", "needs_attention") and r["counts"]["source_documents"] > 100
    assert {c["id"] for c in r["checks"]} >= {"source_files", "manifest_rows", "source_vs_manifest", "index_ids", "source_vs_index"}
    assert svc.ledger.list_runs() == []  # a check is not an audit: nothing is stored


def test_a_service_whose_connections_are_not_set_up_answers_with_a_not_ready_report(tmp_path):
    svc = make_service(tmp_path)

    def refuse(_):
        raise ConnectorError("RAGI_S3_BUCKET is not set")

    svc._connectors, svc._connector_factory = None, refuse
    r = svc.setup_check()
    assert r["status"] == "not_ready" and r["checks"][0]["id"] == "connections" and "S3_BUCKET" in r["checks"][0]["detail"]
    assert "Settings" in r["next_steps"][0]


def test_a_target_that_the_server_refuses_to_connect_to_is_a_result_too(tmp_path):
    from ragintegrity.security import UnsafeTarget

    svc = make_service(tmp_path)

    def refuse(_):
        raise UnsafeTarget("10.0.0.5 is a private or reserved address; only public hosts are allowed.")

    svc._connectors, svc._connector_factory = None, refuse
    r = svc.setup_check()
    assert r["status"] == "not_ready" and "private or reserved address" in r["checks"][0]["detail"]


def test_settings_that_cannot_be_read_do_not_break_the_names_used_in_messages(tmp_path):
    svc = make_service(tmp_path, qdrant_payload_map="{not json")
    assert svc.id_names()["payload_document_id"] == "document_id"  # falls back; the connector reports the real problem


def test_the_api_runs_the_check_in_demo_mode(tmp_path):
    from tests.test_api import make_client

    client, svc = make_client(tmp_path)
    with client:
        r = client.post("/api/setup-check")
        assert r.status_code == 200 and r.json()["status"] in ("ready", "needs_attention") and r.json()["checks"]


def test_the_app_needs_a_session_and_limits_how_often_it_is_run(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        assert c.post("/api/setup-check").status_code == 401
        signup(c)
        first = c.post("/api/setup-check")  # nothing connected yet: a result, not an error
        assert first.status_code == 200 and first.json()["status"] == "not_ready" and first.json()["checks"][0]["id"] == "connections"
        codes = [c.post("/api/setup-check").status_code for _ in range(20)]
        assert codes[:19] == [200] * 19 and codes[19] == 429  # 20 per 10 minutes per workspace


def test_one_workspace_cannot_use_up_anothers_checks(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        signup(c, "a@example.com")
        for _ in range(20):
            c.post("/api/setup-check")
        assert c.post("/api/setup-check").status_code == 429
    c2, *_ = make(tmp_path)  # a second sign-in on the same database: a different workspace has its own allowance
    with c2:
        signup(c2, "b@example.com")
        assert c2.post("/api/setup-check").status_code == 200
