from __future__ import annotations

import base64
import hashlib

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import create_engine, text

from ragintegrity.config import Settings
from ragintegrity.connectors.base import ConnectorError
from ragintegrity.connectors.payload import build_payload_map, payload_to_chunk, vector_is_usable
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.models import Scope


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# ------------------------------------------------------------------------------------- S3
@pytest.fixture()
def bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="docs")
        yield s3


def test_s3_inventory_uses_sha256_metadata_and_parses_tenant(bucket):
    sha = hashlib.sha256(b"hello").hexdigest()
    bucket.put_object(Bucket="docs", Key="acme/policies/leave.md", Body=b"hello", Metadata={"sha256": sha})
    bucket.put_object(Bucket="docs", Key="globex/runbook.md", Body=b"x")  # no metadata -> falls back to ETag
    bucket.put_object(Bucket="docs", Key="acme/folder/", Body=b"")  # folder marker is ignored
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1"))
    docs = {d.key: d for d in src.inventory()}
    assert set(docs) == {("acme", "policies/leave.md"), ("globex", "runbook.md")}
    d = docs[("acme", "policies/leave.md")]
    assert d.source_hash == sha and d.hash_reliable and d.source_uri == "s3://docs/acme/policies/leave.md"
    assert docs[("globex", "runbook.md")].source_hash == hashlib.md5(b"x").hexdigest()


def test_s3_compute_mode_hashes_content_without_metadata(bucket):
    bucket.put_object(Bucket="docs", Key="acme/a.txt", Body=b"payload")
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1", s3_hash_mode="compute"))
    [d] = list(src.inventory())
    assert d.source_hash == hashlib.sha256(b"payload").hexdigest()


def test_s3_native_sha256_checksum(bucket):
    """S3's additional SHA-256 checksum arrives base64 encoded on HEAD. (moto does not emulate checksums,
    so the HEAD response is stubbed here; the decoding is what we are testing.)"""
    digest = hashlib.sha256(b"checksummed").digest()
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1"), client=bucket)
    head = {"ChecksumSHA256": base64.b64encode(digest).decode(), "Metadata": {}}
    doc = src._doc("acme/c.txt", {"ETag": '"abc"', "Size": 11}, head)
    assert doc.source_hash == digest.hex() and doc.hash_reliable


def test_s3_multipart_etag_is_flagged_unreliable(bucket):
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1", s3_hash_mode="etag"), client=bucket)
    doc = src._doc("acme/big.bin", {"ETag": '"abc123-4"', "Size": 5}, None)
    assert doc.source_hash == "abc123-4" and doc.hash_reliable is False


def test_s3_scoped_inventory_by_tenant_and_by_document(bucket):
    for t in ("acme", "globex"):
        bucket.put_object(Bucket="docs", Key=f"{t}/one.md", Body=b"1", Metadata={"sha256": "a"})
        bucket.put_object(Bucket="docs", Key=f"{t}/two.md", Body=b"2", Metadata={"sha256": "b"})
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1"))
    assert {d.key for d in src.inventory(Scope(tenant="acme"))} == {("acme", "one.md"), ("acme", "two.md")}
    got = {d.key for d in src.inventory(Scope(keys=frozenset({("globex", "two.md"), ("globex", "gone.md")})))}
    assert got == {("globex", "two.md")}  # missing objects are simply absent


def test_s3_single_tenant_pattern(bucket):
    bucket.put_object(Bucket="docs", Key="kb/guide.md", Body=b"1", Metadata={"sha256": "a"})
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1", s3_prefix="kb/",
                            s3_key_pattern=r"^(?P<document_id>.+)$", s3_default_tenant="solo"))
    assert [d.key for d in src.inventory()] == [("solo", "guide.md")]


def test_s3_health_reports_missing_bucket(bucket):
    status = S3Source(settings(s3_bucket="nope", s3_region="us-east-1")).health()
    assert not status.ok and "NoSuchBucket" in status.detail


def test_s3_connection_errors_are_explained_plainly():
    from botocore.exceptions import EndpointConnectionError, NoCredentialsError

    from ragintegrity.connectors.s3 import _explain_s3

    assert "Could not connect" in _explain_s3(EndpointConnectionError(endpoint_url="http://x:1/bucket?secret=1"))
    assert "http://x" not in _explain_s3(EndpointConnectionError(endpoint_url="http://x:1/bucket?secret=1"))
    assert "access key" in _explain_s3(NoCredentialsError())


def test_s3_diagnostics_use_a_fast_client(bucket):
    src = S3Source(settings(s3_bucket="docs", s3_region="us-east-1"), fast=True)
    cfg = src.client.meta.config
    assert cfg.retries["total_max_attempts"] == 1 and cfg.connect_timeout == 4  # one attempt, no retries
    normal = S3Source(settings(s3_bucket="docs", s3_region="us-east-1")).client.meta.config
    assert normal.retries["total_max_attempts"] == 4 and normal.connect_timeout == 10


def test_s3_requires_bucket():
    with pytest.raises(ConnectorError):
        S3Source(settings())


# ------------------------------------------------------------------------------------- manifest (SQLite stands in for Postgres)
@pytest.fixture()
def manifest_engine():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE rag_document_manifest (
            tenant_id TEXT, document_id TEXT, source_hash TEXT, source_version TEXT, processing_status TEXT,
            expected_chunk_count INT, indexed_chunk_count INT, embedding_model TEXT, embedding_dim INT,
            updated_at TEXT, acl_hash TEXT)"""))
        c.execute(text("""CREATE TABLE rag_chunk_manifest (
            tenant_id TEXT, document_id TEXT, chunk_id TEXT, chunk_index INT, chunk_hash TEXT)"""))
        rows = [("acme", "a.md", "h1", "v1", "success", 2, 2, "m1", 16, "2026-01-01T00:00:00", "acl1"),
                ("acme", "b.md", "h2", "v2", "failed", None, None, None, None, None, None),
                ("globex", "a.md", "h3", "v3", "success", 1, 1, "m1", 16, None, None)]
        for r in rows:
            c.execute(text("INSERT INTO rag_document_manifest VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i,:j,:k)"),
                      dict(zip("abcdefghijk", r, strict=True)))
        for cid in ("a.md#0", "a.md#1"):
            c.execute(text("INSERT INTO rag_chunk_manifest VALUES ('acme','a.md',:c,:i,'x')"),
                      {"c": cid, "i": int(cid[-1])})
    return eng


def test_manifest_reads_rows_and_tolerates_missing_columns(manifest_engine):
    m = PostgresManifest(settings(manifest_chunk_table="rag_chunk_manifest"), engine=manifest_engine)
    rows = {r.key: r for r in m.documents()}
    assert set(rows) == {("acme", "a.md"), ("acme", "b.md"), ("globex", "a.md")}
    a = rows[("acme", "a.md")]
    assert a.fingerprint.embedding_model == "m1" and a.fingerprint.embedding_dim == 16
    assert a.expected_chunk_count == 2 and a.acl_hash == "acl1"
    assert rows[("acme", "b.md")].processing_status == "failed"
    assert {c.chunk_id for c in m.chunks()} == {"a.md#0", "a.md#1"}


def test_manifest_scope_filters_exact_pairs(manifest_engine):
    m = PostgresManifest(settings(), engine=manifest_engine)
    got = [r.key for r in m.documents(Scope(keys=frozenset({("acme", "a.md")})))]
    assert got == [("acme", "a.md")]  # globex/a.md shares the doc id but is a different tenant
    assert {r.tenant_id for r in m.documents(Scope(tenant="globex"))} == {"globex"}


def test_manifest_column_map_and_health(manifest_engine):
    with manifest_engine.begin() as c:
        c.execute(text("ALTER TABLE rag_document_manifest RENAME COLUMN document_id TO doc_ref"))
    m = PostgresManifest(settings(manifest_column_map='{"document_id": "doc_ref"}'), engine=manifest_engine)
    assert len(list(m.documents())) == 3
    h = m.health()
    assert h.ok and "parser_version" in h.info["missing"]


def test_manifest_rejects_unsafe_identifiers(manifest_engine):
    with pytest.raises(ValueError):
        PostgresManifest(settings(manifest_table="x; DROP TABLE y"), engine=manifest_engine)
    with pytest.raises(ValueError):
        PostgresManifest(settings(manifest_column_map='{"document_id": "a\\" OR 1=1 --"}'), engine=manifest_engine)


# ------------------------------------------------------------------------------------- Qdrant (local in-memory mode)
@pytest.fixture()
def qdrant():
    from qdrant_client import QdrantClient, models

    client = QdrantClient(":memory:")
    client.create_collection("kb", vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE))
    pts = [
        models.PointStruct(id=1, vector=[1, 0, 0, 0], payload={"tenant_id": "acme", "document_id": "a.md", "chunk_id": "a#0", "chunk_index": 0, "source_hash": "h1", "embedding_model": "m1"}),
        models.PointStruct(id=2, vector=[0, 1, 0, 0], payload={"tenant_id": "acme", "document_id": "a.md", "chunk_id": "a#1", "chunk_index": 1, "source_hash": "h1", "embedding_model": "m1"}),
        models.PointStruct(id=3, vector=[0, 0, 0, 0], payload={"tenant_id": "acme", "document_id": "b.md", "chunk_id": "b#0", "chunk_index": 0, "source_hash": "h2"}),
        models.PointStruct(id=4, vector=[1, 0.1, 0, 0], payload={"tenant_id": "globex", "document_id": "a.md", "chunk_id": "a#0", "chunk_index": 0, "source_hash": "h9"}),
        models.PointStruct(id=5, vector=[0, 0, 1, 0], payload={"note": "no document id"}),
    ]
    client.upsert("kb", pts)
    return client


def test_qdrant_scan_maps_payload_and_flags_empty_vectors(qdrant):
    idx = QdrantIndex(settings(qdrant_collections="kb"), client=qdrant)
    chunks = {c.point_id: c for c in idx.scan(with_vectors=True)}
    assert len(chunks) == 5
    assert chunks["1"].document_id == "a.md" and chunks["1"].fingerprint.embedding_model == "m1"
    assert chunks["3"].vector_checked and not chunks["3"].vector_ok  # all-zero vector
    assert chunks["1"].vector_ok
    assert chunks["5"].document_id is None
    assert "source_hash" in chunks["1"].present_fields and "source_hash" not in chunks["5"].present_fields
    assert idx.vector_sizes() == {"kb": 4}


def test_qdrant_scan_scoped_by_tenant_and_documents(qdrant):
    idx = QdrantIndex(settings(qdrant_collections="kb"), client=qdrant)
    assert {c.point_id for c in idx.scan(Scope(tenant="globex"))} == {"4"}
    got = {c.point_id for c in idx.scan(Scope(keys=frozenset({("acme", "a.md")})))}
    assert got == {"1", "2"}  # same doc id under globex is excluded


def test_qdrant_probe_respects_tenant_filter(qdrant):
    idx = QdrantIndex(settings(qdrant_collections="kb"), client=qdrant)
    hits = idx.probe("kb", "1", "acme", 5)
    assert hits[0][0] == "1" and hits[0][2] == "a.md"
    assert "4" not in {h[0] for h in hits}  # globex vector must never surface for an acme query
    assert idx.probe("kb", "999", "acme", 5) is None


def test_qdrant_payload_map_override(qdrant):
    from qdrant_client import models

    qdrant.upsert("kb", [models.PointStruct(id=9, vector=[0, 0, 0, 1], payload={"tenant": "t", "doc": {"id": "nested.md"}})])
    idx = QdrantIndex(settings(qdrant_collections="kb", qdrant_payload_map='{"tenant_id": "tenant", "document_id": "doc.id"}'), client=qdrant)
    got = {c.point_id: c for c in idx.scan()}
    assert got["9"].document_id == "nested.md" and got["9"].tenant_id == "t"


def test_payload_helpers():
    assert vector_is_usable([0.1, 0]) and not vector_is_usable([0, 0]) and not vector_is_usable(None)
    assert vector_is_usable({"dense": [1.0]}, "dense") and not vector_is_usable({"dense": [0.0]}, "dense")
    with pytest.raises(ValueError):
        build_payload_map({"nope": "x"})
    c = payload_to_chunk("c", 1, {"document_id": "d", "chunk_index": "3"}, build_payload_map(None))
    assert c.chunk_index == 3 and c.tenant_id is None
