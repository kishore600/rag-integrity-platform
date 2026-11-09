"""Large buckets and slow indexes: look files up instead of listing, stop with a clear message, show how far a run got."""

from __future__ import annotations

import time
from datetime import timedelta

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import update

from ragintegrity.config import Settings
from ragintegrity.connectors.base import AuditTimeout, ConnectionStatus
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.engine.audit import AuditOptions, collect, run_reconciliation
from ragintegrity.ledger import STALE_RUN_SECONDS, utcnow
from ragintegrity.models import IssueType, ManifestRow, Scope
from tests.test_service import make_service

SAME_NUMBER = r"^(?P<document_id>[^/]+)/(?P=document_id)\.pdf$"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.fixture()
def bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        for key in ("bills/1/1.pdf", "bills/2/2.pdf", "bills/3/9.pdf", "bills/4/readme.txt"):
            s3.put_object(Bucket="docs", Key=key, Body=b"%PDF")
        yield s3


def source(**kw) -> S3Source:
    return S3Source(settings(s3_bucket="docs", s3_region="us-east-1", s3_prefix="bills/", s3_key_pattern=SAME_NUMBER, **kw))


# ------------------------------------------------------------------------------------- looking files up from the manifest
def test_uris_in_every_s3_address_style_name_the_same_key():
    src = source()
    for uri in ("s3://docs/bills/1/1.pdf",
                "https://docs.s3.us-west-1.amazonaws.com/bills/1/1.pdf",
                "https://s3.us-west-1.amazonaws.com/docs/bills/1/1.pdf",
                "https://docs.s3.amazonaws.com/bills%2F1/1.pdf".replace("%2F", "/")):
        assert src.key_from_uri(uri) == "bills/1/1.pdf", uri
    for other in (None, "", "s3://another-bucket/bills/1/1.pdf", "https://another.s3.amazonaws.com/bills/1/1.pdf",
                  "https://example.com/bills/1/1.pdf", "not a uri", "s3://docs/"):
        assert src.key_from_uri(other) is None, other


def test_lookup_reads_only_the_named_files_that_match_the_pattern_and_exist(bucket):
    src = source(s3_hash_mode="etag")
    docs = list(src.lookup([
        "s3://docs/bills/1/1.pdf",
        "https://docs.s3.us-east-1.amazonaws.com/bills/2/2.pdf",
        "https://s3.us-east-1.amazonaws.com/docs/bills/1/1.pdf",  # the same file again
        "s3://docs/bills/3/9.pdf",  # exists, but folder != file name: outside the corpus
        "s3://docs/bills/5/5.pdf",  # matches the pattern but is not in the bucket
        "s3://elsewhere/bills/1/1.pdf",  # another bucket
        None,
    ]))
    assert {d.key for d in docs} == {("default", "1"), ("default", "2")}
    assert all(d.source_uri.startswith("s3://docs/bills/") and d.size_bytes == 4 for d in docs)


def test_listing_is_never_used_when_the_manifest_names_the_files(bucket):
    class NoListing(S3Source):
        def inventory(self, scope=None):  # pragma: no cover - failing is the point
            raise AssertionError("the bucket must not be listed")

    src = NoListing(settings(s3_bucket="docs", s3_region="us-east-1", s3_prefix="bills/", s3_key_pattern=SAME_NUMBER,
                             s3_hash_mode="etag"))

    class Manifest:
        has_chunk_manifest = False

        def documents(self, scope=None):
            yield ManifestRow("default", "1", source_uri="s3://docs/bills/1/1.pdf", processing_status="True")
            yield ManifestRow("default", "2", source_uri="s3://docs/bills/2/2.pdf", processing_status="True")
            yield ManifestRow("default", "99", source_uri="s3://docs/bills/99/99.pdf", processing_status="True")  # file gone

        def chunks(self, scope=None):
            return iter(())

        def health(self):
            return ConnectionStatus("m", "manifest", True)

    class Index:
        def collections(self):
            return ["c"]

        def vector_sizes(self):
            return {"c": 3}

        def scan(self, scope=None, with_vectors=False):
            return iter(())

        def probe(self, *a, **k):
            return None

        def health(self):
            return ConnectionStatus("i", "index", True)

    opts = AuditOptions(lookup_from_manifest=True, source_only=True, probe=False)
    result = run_reconciliation(src, Manifest(), Index(), opts)
    found = {f.key: f for f in result.findings}
    assert set(found) == {("default", "1"), ("default", "2")}  # the manifest row whose file is gone is out of scope
    assert all(f.type == IssueType.MISSING_EMBEDDING and f.severity.value == "critical" for f in found.values())


def test_without_the_option_the_bucket_is_still_listed(bucket):
    seen = []

    class Spy(S3Source):
        def lookup(self, uris):  # pragma: no cover
            seen.append("lookup")
            return iter(())

    src = Spy(settings(s3_bucket="docs", s3_region="us-east-1", s3_prefix="bills/", s3_key_pattern=SAME_NUMBER, s3_hash_mode="etag"))

    class Manifest:
        has_chunk_manifest = False

        def documents(self, scope=None):
            return iter(())

    c = collect(src, Manifest(), type("I", (), {"scan": lambda self, scope=None, with_vectors=False: iter(())})(),
                AuditOptions(lookup_from_manifest=False))
    assert seen == [] and set(c.source) == {("default", "1"), ("default", "2")}


# ------------------------------------------------------------------------------------- the time budget
def test_listing_a_large_bucket_stops_with_a_clear_message_when_time_is_up(bucket):
    src = source(s3_hash_mode="etag")
    src.deadline = time.monotonic() - 1
    with pytest.raises(AuditTimeout) as exc:
        list(src.inventory())
    assert "source bucket" in str(exc.value) and "listed" in str(exc.value) and "ragi audit" in str(exc.value)


def test_a_slow_index_scan_stops_at_the_next_page_when_time_is_up():
    class Client:
        def __init__(self):
            self.calls = 0

        def scroll(self, **kw):
            self.calls += 1
            return [], "next"  # an endless collection with no matching points on these pages

    client = Client()
    idx = QdrantIndex(settings(qdrant_collections="c"), client=client)
    idx.deadline = time.monotonic() - 1
    with pytest.raises(AuditTimeout) as exc:
        list(idx.scan(None))
    assert "vector index" in str(exc.value) and client.calls == 0  # it never even sends another request


def test_collect_hands_the_deadline_to_connectors_that_page():
    class Src:
        deadline = "unset"

        def inventory(self, scope=None):
            return iter(())

    class Man:
        has_chunk_manifest = False

        def documents(self, scope=None):
            return iter(())

    class Idx:
        deadline = "unset"

        def scan(self, scope=None, with_vectors=False):
            return iter(())

    s, i = Src(), Idx()
    collect(s, Man(), i, AuditOptions(deadline=123.0))
    assert s.deadline == 123.0 and i.deadline == 123.0


# ------------------------------------------------------------------------------------- progress and abandoned runs
def test_progress_notes_follow_the_phases(world, connectors, opts):
    notes = []
    run_reconciliation(*connectors, AuditOptions(**{**opts.__dict__, "progress": lambda phase, **info: notes.append((phase, info))}))
    phases = [p for p, _ in notes]
    assert phases == ["listing the source documents (S3)", "reading the processing manifest",
                      "reading the vector index (Qdrant)", "comparing the three lists"]
    assert all("elapsed_seconds" in info for _, info in notes)
    assert notes[-1][1]["source_documents"] == len(world.sources)


def test_a_failing_progress_callback_never_breaks_the_audit(world, connectors, opts):
    def broken(phase, **info):
        raise RuntimeError("database unavailable")

    result = run_reconciliation(*connectors, AuditOptions(**{**opts.__dict__, "progress": broken}))
    assert result.findings


def test_progress_is_stored_and_an_abandoned_run_says_where_it_stopped(tmp_path):
    svc = make_service(tmp_path)
    svc.ledger.init()
    run_id = svc.ledger.start_run("full", "api", None)
    svc.ledger.set_progress(run_id, "reading the vector index (Qdrant)", elapsed_seconds=41.2, source_documents=82)
    assert svc.ledger.get_run(run_id)["stats"]["progress"]["source_documents"] == 82

    runs = svc.ledger.t["audit_runs"]
    with svc.ledger.engine.begin() as c:
        c.execute(update(runs).where(runs.c.id == run_id).values(started_at=utcnow() - timedelta(seconds=STALE_RUN_SECONDS + 5)))
    assert svc.audit_running is False
    run = svc.ledger.get_run(run_id)
    assert run["status"] == "failed" and "last step: reading the vector index (Qdrant), 41.2 s in" in run["error"]


def test_progress_updates_only_touch_running_audits(tmp_path):
    svc = make_service(tmp_path)
    svc.ledger.init()
    run_id = svc.ledger.start_run("full", "api", None)
    svc.ledger.finish_run(run_id, "completed", {"documents_total": 3})
    svc.ledger.set_progress(run_id, "late note")
    assert svc.ledger.get_run(run_id)["stats"] == {"documents_total": 3}


def test_a_hosted_run_is_presumed_dead_soon_after_its_time_budget(tmp_path):
    (tmp_path / "hosted").mkdir()
    hosted = make_service(tmp_path / "hosted", max_audit_seconds=270)
    assert hosted._stale_after() == 360  # the budget plus 90 s, not the 15 minutes used for long-lived servers
    local = make_service(tmp_path)
    assert local._stale_after() == STALE_RUN_SECONDS
    assert local.options().progress is None  # no run, no progress sink


def test_the_hosted_time_budget_applies_on_vercel(monkeypatch):
    from ragintegrity.config import HOSTED_AUDIT_SECONDS

    monkeypatch.setenv("VERCEL", "1")
    assert settings().audit_seconds_limit == HOSTED_AUDIT_SECONDS == 270
    assert settings(max_audit_seconds=45).audit_seconds_limit == 45  # an explicit limit wins


def test_a_one_document_check_looks_its_file_up_instead_of_listing_the_bucket(bucket):
    """'Re-audit document' and the isolation drill must stay fast on a huge bucket: the manifest names the file."""

    class NoListing(S3Source):
        def inventory(self, scope=None):  # pragma: no cover - failing is the point
            raise AssertionError("the bucket must not be listed")

    class Manifest:
        has_chunk_manifest = False

        def documents(self, scope=None):
            for doc in ("1", "2"):
                row = ManifestRow("default", doc, source_uri=f"s3://docs/bills/{doc}/{doc}.pdf", processing_status="True")
                if scope is None or scope.matches(row.key):
                    yield row

    class Index:
        def scan(self, scope=None, with_vectors=False):
            return iter(())

    src = NoListing(settings(s3_bucket="docs", s3_region="us-east-1", s3_prefix="bills/", s3_key_pattern=SAME_NUMBER,
                             s3_hash_mode="etag"))
    one = collect(src, Manifest(), Index(), AuditOptions(lookup_from_manifest=True), Scope(keys=frozenset({("default", "2")})))
    assert set(one.source) == {("default", "2")} and set(one.manifest) == {("default", "2")}
    both = collect(src, Manifest(), Index(), AuditOptions(lookup_from_manifest=True))
    assert set(both.source) == {("default", "1"), ("default", "2")}


def test_tenant_scoped_runs_still_list_the_bucket(bucket):
    """Only a full audit looks files up from the manifest; a tenant-scoped inventory keeps using the listing."""
    src = source(s3_hash_mode="etag")
    assert {d.key for d in src.inventory(Scope(tenant="default"))} == {("default", "1"), ("default", "2")}
