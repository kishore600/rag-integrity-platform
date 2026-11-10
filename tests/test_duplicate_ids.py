"""Two files (or two manifest rows) with the same document ID used to hide each other without a word.

``{doc.key: doc for doc in docs}`` keeps the last one, so a key pattern that gave two different files the same ID made one
of them vanish from the audit with nothing to say so. The audit still follows one item per ID (results are unchanged),
but it now counts the duplicates and warns, with examples, in plain words.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import create_engine, text

from ragintegrity.config import Settings
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.engine.coverage import PER_ID_LOCATIONS, Unique, id_warnings
from ragintegrity.models import ManifestRow, SourceDoc
from tests.test_source_only import FakeIndex, FakeManifest, FakeSource


def src(doc, uri, tenant="default"):
    return SourceDoc(tenant, doc, uri, source_hash="h", size_bytes=1)


def row(doc, uri=None, status="success", tenant="default"):
    return ManifestRow(tenant, doc, source_uri=uri, processing_status=status)


def audit(source, manifest, **kw):
    return run_reconciliation(FakeSource(source), FakeManifest(manifest), FakeIndex(), AuditOptions(probe=False, **kw))


# ------------------------------------------------------------------------------------- the tracker
def test_the_tracker_keeps_the_last_item_and_counts_the_rest():
    u = Unique(lambda x: x)
    for key, item in ((("t", "a"), "a1"), (("t", "b"), "b1"), (("t", "a"), "a2"), (("t", "a"), "a3")):
        u.add(key, item)
    assert u.items == {("t", "a"): "a3", ("t", "b"): "b1"}  # results are exactly what they were before
    assert u.duplicate_ids == 1 and u.extra_copies == 2
    assert u.examples() == [{"tenant_id": "t", "document_id": "a", "copies": 3, "found_in": ["a1", "a2", "a3"]}]


def test_the_tracker_stays_small_however_many_duplicates_there_are():
    u = Unique(lambda x: x)
    for i in range(500):
        for copy in range(8):
            u.add(("t", str(i)), f"{i}-{copy}")
    assert u.duplicate_ids == 500 and u.extra_copies == 500 * 7  # all counted ...
    assert len(u.where) <= 200 and all(len(v) <= PER_ID_LOCATIONS for v in u.where.values())  # ... few remembered


def test_restricting_to_some_ids_drops_the_duplicates_of_the_others_too():
    u = Unique(lambda x: x)
    for key in (("t", "a"), ("t", "a"), ("t", "b"), ("t", "b")):
        u.add(key, "x")
    assert u.restrict(lambda k: k[1] == "a") == {("t", "a"): "x"} and u.duplicate_ids == 1


def test_no_duplicates_means_no_warnings():
    u = Unique(lambda x: x)
    u.add(("t", "a"), "x")
    assert id_warnings(u, u, 0) == [] and id_warnings(None, None, 0) == []


# ------------------------------------------------------------------------------------- inside an audit
def test_two_files_with_one_id_are_reported_with_where_they_are():
    r = audit([src("42", "s3://b/bills/a/42.pdf"), src("42", "s3://b/bills/b/42.pdf"), src("7", "s3://b/bills/7.pdf")], [])
    [w] = r.stats["warnings"]
    assert w["code"] == "duplicate_source_ids" and w["severity"] == "warning" and w["count"] == 1
    assert w["examples"] == [{"tenant_id": "default", "document_id": "42", "copies": 2,
                              "found_in": ["s3://b/bills/a/42.pdf", "s3://b/bills/b/42.pdf"]}]
    assert "42" in w["detail"] and "s3://b/bills/a/42.pdf and s3://b/bills/b/42.pdf" in w["detail"] and "key pattern" in w["fix"]
    assert len(r.summaries) == 2  # still one document per ID: the audit did not change shape


def test_two_manifest_rows_with_one_id_are_reported_with_their_status():
    r = audit([src("42", "s3://b/42.pdf")], [row("42", "s3://b/42.pdf", "failed"), row("42", "s3://b/42-v2.pdf", "success")])
    [w] = r.stats["warnings"]
    assert w["code"] == "duplicate_manifest_ids" and w["examples"][0]["copies"] == 2
    assert w["examples"][0]["found_in"] == ["s3://b/42.pdf (status: failed)", "s3://b/42-v2.pdf (status: success)"]
    assert "unique" in w["fix"]


def test_a_manifest_that_cannot_say_which_column_has_the_ids_still_warns_plainly():
    r = audit([src("42", "u")], [row("42"), row("42")])
    assert r.stats["warnings"][0]["examples"][0]["found_in"] == ["a manifest row (status: success)"] * 2


def test_rows_without_an_id_are_counted_and_named():
    manifest = FakeManifest([row("1")])
    manifest.empty_ids = 3
    r = run_reconciliation(FakeSource([src("1", "u")]), manifest, FakeIndex(),
                           AuditOptions(probe=False, names={"manifest_document_id": "external_doc_id"}))
    [w] = r.stats["warnings"]
    assert w["code"] == "empty_manifest_ids" and w["count"] == 3 and "external_doc_id" in w["detail"]


def test_manifest_duplicates_for_documents_outside_the_source_are_not_a_problem_when_only_the_source_counts():
    docs, rows = [src("1", "u1")], [row("1"), row("2"), row("2")]  # document 2 is not in S3 and is ignored
    assert audit(docs, rows, source_only=True).stats["warnings"] == []
    assert audit(docs, rows).stats["warnings"][0]["examples"][0]["document_id"] == "2"


def test_a_clean_audit_has_an_empty_warning_list():
    assert audit([src("1", "u1")], [row("1")]).stats["warnings"] == []


def test_duplicates_are_stored_with_the_run_and_served_by_the_api(tmp_path):
    from fastapi.testclient import TestClient

    from ragintegrity.api.app import create_app
    from ragintegrity.connectors.factory import Connectors
    from ragintegrity.ledger import Ledger
    from ragintegrity.service import IntegrityService

    settings = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{tmp_path / 'dup.db'}",
                        manifest_column_map='{"document_id": "doc"}', s3_key_pattern=r"^(?P<document_id>[^/]+)\.pdf$")
    c = Connectors(FakeSource([src("42", "s3://b/a/42.pdf"), src("42", "s3://b/b/42.pdf")]), FakeManifest([row("42")]), FakeIndex())
    svc = IntegrityService(settings, Ledger(settings.database_url), c)
    with TestClient(create_app(svc, settings)) as client:
        run_id = client.post("/api/audits", json={"wait": True}).json()["run_id"]
        [w] = client.get(f"/api/audits/{run_id}").json()["stats"]["warnings"]
        assert w["code"] == "duplicate_source_ids" and w["examples"][0]["found_in"] == ["s3://b/a/42.pdf", "s3://b/b/42.pdf"]
        # the manifest column the user mapped is named in the message, not the internal name
        assert svc.id_names()["manifest_document_id"] == "doc"
        assert client.get("/api/overview").json()["latest_full_run"]["stats"]["warnings"] == [w]


# ------------------------------------------------------------------------------------- through real connectors
@pytest.fixture()
def bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        for key in ("2023/42.pdf", "2024/42.pdf", "2024/7.pdf"):
            s3.put_object(Bucket="docs", Key=key, Body=b"%PDF")
        yield s3


def test_a_key_pattern_that_gives_two_files_one_id_is_caught_with_real_s3(bucket):
    source = S3Source(Settings(_env_file=None, s3_bucket="docs", s3_region="us-east-1", s3_hash_mode="etag",
                               s3_key_pattern=r"^[0-9]+/(?P<document_id>[0-9]+)\.pdf$"))
    r = run_reconciliation(source, FakeManifest([]), FakeIndex(), AuditOptions(probe=False))
    [w] = r.stats["warnings"]
    assert w["code"] == "duplicate_source_ids" and w["examples"][0]["document_id"] == "42"
    assert w["examples"][0]["found_in"] == ["s3://docs/2023/42.pdf", "s3://docs/2024/42.pdf"]


def test_duplicate_and_empty_manifest_ids_are_caught_with_a_real_table(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE manifest (document_id TEXT, source_uri TEXT, processing_status TEXT)"))
        c.execute(text("INSERT INTO manifest VALUES ('42', 's3://docs/a', 'success'), ('42', 's3://docs/b', 'failed'), "
                       "(NULL, 's3://docs/c', 'success'), ('', 's3://docs/d', 'success'), ('7', 's3://docs/e', 'success')"))
    manifest = PostgresManifest(Settings(_env_file=None, manifest_table="manifest"), engine)
    r = run_reconciliation(FakeSource([]), manifest, FakeIndex(), AuditOptions(probe=False))
    assert sorted(w["code"] for w in r.stats["warnings"]) == ["duplicate_manifest_ids", "empty_manifest_ids"]
    assert {w["code"]: w["count"] for w in r.stats["warnings"]} == {"duplicate_manifest_ids": 1, "empty_manifest_ids": 2}
