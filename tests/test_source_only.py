"""'Only audit documents found in the source (S3)': a shared index or manifest holds more than the bucket covers.

The S3 key pattern defines the corpus; everything else in the manifest and the index is ignored, and only the
matching points are read from the vector index.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from ragintegrity.config import Settings
from ragintegrity.connectors.qdrant import FILTER_BATCH, QdrantIndex, _explain_qdrant
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.demo.world import DemoIndex
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.engine.reconcile import SUCCESS_STATUSES
from ragintegrity.models import ConnectionStatus, IssueType, ManifestRow, Scope, SourceDoc
from tests.test_service import make_service

NOISE = {IssueType.ORPHAN_VECTOR.value, IssueType.MANIFEST_ORPHAN.value, IssueType.TENANT_MISMATCH.value}


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _types_by_doc(result, keep):
    out = defaultdict(set)
    for f in result.findings:
        if f.key in keep and f.type.value not in NOISE:
            out[f.key].add(f.type.value)
    return dict(out)


# ------------------------------------------------------------------------------------- the engine
def test_findings_for_source_documents_are_unchanged_and_orphan_noise_disappears(world, connectors, opts):
    full = run_reconciliation(*connectors, opts)
    only = run_reconciliation(*connectors, dataclasses.replace(opts, source_only=True))

    assert _types_by_doc(only, world.sources) == _types_by_doc(full, world.sources)
    assert not [f for f in only.findings if f.type.value in NOISE]
    assert [f for f in full.findings if f.type.value in NOISE], "the demo world must contain orphans for this test to mean anything"
    assert only.stats["source_documents_only"] is True and "source_documents_only" not in full.stats


class SpyIndex:
    """Wraps an index and remembers the scope each scan was asked for."""

    def __init__(self, inner):
        self.inner, self.scopes = inner, []

    def scan(self, scope=None, with_vectors=False) -> Iterator:
        self.scopes.append(scope)
        yield from self.inner.scan(scope, with_vectors)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_the_index_is_read_only_for_the_documents_in_the_source(world, connectors, opts):
    source, manifest, index = connectors
    spy = SpyIndex(index)
    run_reconciliation(source, manifest, spy, dataclasses.replace(opts, source_only=True, probe=False))
    [scope] = spy.scopes
    assert scope.keys == frozenset(world.sources) and scope.tenant is None

    spy_full = SpyIndex(DemoIndex(world))
    run_reconciliation(source, manifest, spy_full, dataclasses.replace(opts, probe=False))
    assert spy_full.scopes == [None]


class FakeSource:
    def __init__(self, docs=()):
        self.docs = list(docs)

    def inventory(self, scope=None):
        yield from self.docs

    def health(self):
        return ConnectionStatus("fake", "source", True)


class FakeManifest:
    has_chunk_manifest = False

    def __init__(self, rows=()):
        self.rows = list(rows)

    def documents(self, scope=None):
        yield from self.rows

    def chunks(self, scope=None):
        return iter(())

    def health(self):
        return ConnectionStatus("fake", "manifest", True)


class FakeIndex:
    def __init__(self):
        self.scans = 0

    def collections(self):
        return ["c"]

    def vector_sizes(self):
        return {"c": 3}

    def scan(self, scope=None, with_vectors=False):
        self.scans += 1
        return iter(())

    def probe(self, *a, **k):
        return None

    def health(self):
        return ConnectionStatus("fake", "index", True)


def test_an_empty_source_reads_nothing_from_the_index():
    index = FakeIndex()
    r = run_reconciliation(FakeSource(), FakeManifest([ManifestRow("default", "x", processing_status="success")]), index,
                           AuditOptions(source_only=True, probe=False))
    assert index.scans == 0 and r.findings == []  # the manifest-only row is out of scope, not a finding


def test_a_boolean_is_indexed_column_counts_as_the_pipeline_claiming_success():
    assert "true" in SUCCESS_STATUSES
    src = FakeSource([SourceDoc("default", "2329961", "s3://b/bills/2329961/2329961.pdf", size_bytes=10)])
    man = FakeManifest([ManifestRow("default", "2329961", processing_status="True")])  # is_indexed = true, mapped as the status
    r = run_reconciliation(src, man, FakeIndex(), AuditOptions(probe=False, source_only=True))
    [f] = r.findings
    assert f.type == IssueType.MISSING_EMBEDDING and f.severity.value == "critical"
    assert f.evidence["pipeline_reported_success"] is True


def test_service_wiring_and_a_full_audit(tmp_path):
    svc = make_service(tmp_path, source_documents_only=True)
    svc.bootstrap()
    assert svc.options().source_only is True
    result = svc.run_audit()
    assert result.stats["source_documents_only"] is True
    assert not [f for f in result.findings if f.type.value in NOISE]


def test_the_option_is_off_by_default(tmp_path):
    assert make_service(tmp_path).options().source_only is False


# ------------------------------------------------------------------------------------- S3 layout bills/<bill>/<file>.pdf
@pytest.fixture()
def bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        for key in ("bills/2329961/2329961.pdf", "bills/2331101/2331101.pdf", "bills/2089324/3327179.pdf", "bills/536091/219443.pdf"):
            s3.put_object(Bucket="docs", Key=key, Body=b"%PDF")
        yield s3


SAME_NUMBER = r"^(?P<document_id>[^/]+)/(?P=document_id)\.pdf$"  # folder name == file name: the 'prefiled' documents


def s3_source(**kw) -> S3Source:
    return S3Source(settings(s3_bucket="docs", s3_region="us-east-1", s3_prefix="bills/", s3_hash_mode="etag",
                             s3_key_pattern=SAME_NUMBER, **kw))


def test_the_key_pattern_selects_only_files_named_like_their_folder(bucket):
    assert {d.key for d in s3_source().inventory()} == {("default", "2329961"), ("default", "2331101")}


def test_a_scoped_run_finds_documents_even_though_the_key_cannot_be_rebuilt(bucket):
    """bills/<id>/<id>.pdf cannot be rebuilt from the document id; guessing 'bills/<id>' would report every file as deleted."""
    src = s3_source()
    got = {d.key for d in src.inventory(Scope(keys=frozenset({("default", "2329961"), ("default", "999")})))}
    assert got == {("default", "2329961")}
    assert src._addressable(frozenset({("default", "2329961")})) is False


def test_plain_layouts_still_use_exact_key_lookups(bucket):
    bucket.put_object(Bucket="docs", Key="acme/one.md", Body=b"1")
    plain = S3Source(settings(s3_bucket="docs", s3_region="us-east-1", s3_hash_mode="etag"))
    assert plain._addressable(frozenset({("acme", "one.md")})) is True
    assert {d.key for d in plain.inventory(Scope(keys=frozenset({("acme", "one.md")})))} == {("acme", "one.md")}


# ------------------------------------------------------------------------------------- Qdrant filters
class FakeQdrantClient:
    def __init__(self):
        self.calls = []

    def get_collections(self):  # pragma: no cover - collections are configured explicitly
        raise AssertionError("not needed")

    def scroll(self, **kw):
        self.calls.append(kw)
        return [], None


def qdrant(**kw):
    client = FakeQdrantClient()
    return QdrantIndex(settings(qdrant_collections="bill_chunks", qdrant_payload_map='{"document_id": "source_id"}', **kw),
                       client=client), client


def test_a_long_document_list_is_split_into_server_side_filters():
    idx, client = qdrant()
    ids = [str(i) for i in range(2 * FILTER_BATCH + 1)]
    assert list(idx.scan(Scope(keys=frozenset(("default", i) for i in ids)))) == []
    assert len(client.calls) == 3
    seen = []
    for call in client.calls:
        cond = call["scroll_filter"].must[0]
        assert cond.key == "source_id"  # the payload map is honoured
        assert len(cond.match.any) <= FILTER_BATCH
        seen += cond.match.any
    assert sorted(seen) == sorted(ids)


def test_no_documents_means_no_requests_and_a_tenant_is_added_to_every_filter():
    idx, client = qdrant()
    assert list(idx.scan(Scope(keys=frozenset()))) == [] and client.calls == []
    idx, client = qdrant()
    list(idx.scan(Scope(tenant="acme", keys=frozenset({("acme", "d1")}))))
    [call] = client.calls
    assert [c.key for c in call["scroll_filter"].must] == ["tenant_id", "source_id"]


def test_a_full_scan_has_no_filter():
    idx, client = qdrant()
    list(idx.scan(None))
    assert client.calls[0]["scroll_filter"] is None


def test_strict_mode_index_errors_get_an_actionable_message():
    msg = _explain_qdrant(RuntimeError('Index required but not found for "source_id" of one of the following types: [keyword]'))
    assert "payload index" in msg and "Only audit documents found in the source" in msg
