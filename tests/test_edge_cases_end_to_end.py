"""The three features end to end on REAL services: S3 over HTTP (moto), a real PostgreSQL (manifest AND ledger), a real Qdrant.

Skipped unless all three are available:
    RAGI_TEST_PG_URL=postgresql://postgres:postgres@127.0.0.1:5499/postgres
    RAGI_TEST_QDRANT_URL=http://127.0.0.1:6333  (RAGI_TEST_QDRANT_KEY=... if the server enforces a key)
    RAGI_TEST_S3_ENDPOINT=http://127.0.0.1:5556

Each test is one situation that could arrive in production, run through the same code the hosted product runs.
"""

from __future__ import annotations

import hashlib
import os
import uuid

import boto3
import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sqlalchemy import create_engine, text

from ragintegrity.config import Settings, normalize_db_url
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.ledger import Ledger
from ragintegrity.service import IntegrityService

PG, QURL, QKEY, S3EP = (os.environ.get(k) for k in ("RAGI_TEST_PG_URL", "RAGI_TEST_QDRANT_URL", "RAGI_TEST_QDRANT_KEY", "RAGI_TEST_S3_ENDPOINT"))
pytestmark = pytest.mark.skipif(not (PG and QURL and S3EP), reason="needs RAGI_TEST_PG_URL, RAGI_TEST_QDRANT_URL and RAGI_TEST_S3_ENDPOINT")

DOCS = [f"policy-{i:02d}" for i in range(12)]
CHUNKS = 3


def sha(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def body(doc: str, version: int = 1) -> str:
    return f"{doc}: the text of version {version}"


def chunk_hash(doc: str, k: int) -> str:
    return sha(f"{doc}:{k}")


class FlakyClient:
    """The real Qdrant client behind a connection that misbehaves on a schedule: errors are raised in place of real answers."""

    def __init__(self, inner, errors=None, after=None, forever=None):
        self.inner, self.errors, self.after, self.forever, self.calls = inner, list(errors or []), after, forever, 0

    def scroll(self, **kw):
        n = self.calls
        self.calls += 1
        if self.forever is not None and self.after is not None and n >= self.after:
            raise self.forever
        if n < len(self.errors) and self.errors[n] is not None:
            raise self.errors[n]
        return self.inner.scroll(**kw)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class Http(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f"HTTP {status}")
        self.status_code, self.headers = status, headers or {}


class Stack:
    """A small RAG system on real infrastructure: 12 policy documents in a bucket, a manifest table, a chunk table, a collection."""

    def __init__(self) -> None:
        tag = uuid.uuid4().hex[:8]
        self.bucket, self.manifest_t, self.chunk_t, self.coll = f"e2e-{tag}", f"e2e_manifest_{tag}", f"e2e_chunks_{tag}", f"e2e_coll_{tag}"
        self.s3 = boto3.client("s3", endpoint_url=S3EP, aws_access_key_id="test-access-key", aws_secret_access_key="test-secret-key",
                               region_name="us-east-1")
        self.s3.create_bucket(Bucket=self.bucket)
        self.pg = create_engine(normalize_db_url(PG), connect_args={"prepare_threshold": None})
        self.q = QdrantClient(url=QURL, api_key=QKEY, timeout=30)
        with self.pg.begin() as c:
            c.execute(text(f"CREATE TABLE public.{self.manifest_t} (document_id text, source_uri text, source_hash text, "
                           "processing_status text, expected_chunk_count int, indexed_chunk_count int)"))
            c.execute(text(f"CREATE TABLE public.{self.chunk_t} (document_id text, chunk_id text, chunk_index int, chunk_hash text)"))
        self.q.create_collection(self.coll, vectors_config=qm.VectorParams(size=16, distance=qm.Distance.COSINE))
        for n, doc in enumerate(DOCS):
            self.put(doc, 1)
            self.index(doc, 1, n)
        self._ids = {doc: [1000 * (n + 1) + k for k in range(CHUNKS)] for n, doc in enumerate(DOCS)}

    # ---- the pieces of a document
    def put(self, doc: str, version: int) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=f"docs/{doc}.pdf", Body=body(doc, version).encode())

    def index(self, doc: str, version: int, n: int | None = None) -> None:
        """What a pipeline writes when it processes a document: vectors, a manifest row and its chunk rows."""
        n = DOCS.index(doc) if n is None else n
        base = 1000 * (n + 1)
        direction = [1.0 if i == n else 0.0 for i in range(16)]  # one direction per document; the chunks differ slightly
        points = [qm.PointStruct(id=base + k, vector=[*direction[:15], 0.01 * k], payload={
            "document_id": doc, "chunk_id": f"{doc}#{k}", "chunk_index": k, "chunk_hash": chunk_hash(doc, k),
            "source_hash": sha(body(doc, version))}) for k in range(CHUNKS)]
        self.q.upsert(self.coll, points=points, wait=True)
        with self.pg.begin() as c:
            c.execute(text(f"DELETE FROM public.{self.manifest_t} WHERE document_id = :d"), {"d": doc})
            c.execute(text(f"DELETE FROM public.{self.chunk_t} WHERE document_id = :d"), {"d": doc})
            c.execute(text(f"INSERT INTO public.{self.manifest_t} VALUES (:d, :u, :h, 'success', :n, :n)"),
                      {"d": doc, "u": f"s3://{self.bucket}/docs/{doc}.pdf", "h": sha(body(doc, version)), "n": CHUNKS})
            for k in range(CHUNKS):
                c.execute(text(f"INSERT INTO public.{self.chunk_t} VALUES (:d, :c, :i, :h)"),
                          {"d": doc, "c": f"{doc}#{k}", "i": k, "h": chunk_hash(doc, k)})

    def sql(self, statement: str, **params) -> None:
        with self.pg.begin() as c:
            c.execute(text(statement.format(m=self.manifest_t, c=self.chunk_t)), params)

    def drop_vectors(self, doc: str, keep: int = 0) -> None:
        self.q.delete(self.coll, points_selector=qm.PointIdsList(points=self._ids[doc][keep:]), wait=True)

    # ---- the application on top of it
    def settings(self, **kw) -> Settings:
        return Settings(
            _env_file=None, mode="live", database_url=PG, s3_bucket=self.bucket, s3_endpoint_url=S3EP, s3_region="us-east-1",
            s3_access_key_id="test-access-key", s3_secret_access_key="test-secret-key", s3_prefix="docs/",
            s3_key_pattern=r"^(?P<document_id>[^/]+)\.pdf$", s3_hash_mode="compute", manifest_database_url=PG,
            manifest_table=self.manifest_t, manifest_chunk_table=self.chunk_t, qdrant_url=QURL, qdrant_api_key=QKEY,
            qdrant_collections=self.coll, source_documents_only=True, audit_slice_documents=4,
            grace_minutes=0, **kw)  # (a document changed seconds ago would otherwise be 'pending': the grace period)

    def service(self, client=None, **kw) -> IntegrityService:
        s = self.settings(**kw)
        index = QdrantIndex(s, client=client)
        index._sleep = lambda secs: None
        ledger = Ledger(PG)
        ledger.init()
        ledger.reset()
        return IntegrityService(s, ledger, Connectors(S3Source(s), PostgresManifest(s), index))

    def close(self) -> None:
        for fn in (lambda: self.q.delete_collection(self.coll), self._drop_tables, self._empty_bucket):
            try:
                fn()
            except Exception:
                pass

    def _drop_tables(self) -> None:
        with self.pg.begin() as c:
            c.execute(text(f"DROP TABLE IF EXISTS public.{self.manifest_t}"))
            c.execute(text(f"DROP TABLE IF EXISTS public.{self.chunk_t}"))

    def _empty_bucket(self) -> None:
        for o in self.s3.list_objects_v2(Bucket=self.bucket).get("Contents", []):
            self.s3.delete_object(Bucket=self.bucket, Key=o["Key"])
        self.s3.delete_bucket(Bucket=self.bucket)


@pytest.fixture()
def stack():
    s = Stack()
    yield s
    s.close()


def issues(svc, status="open"):
    return sorted((i["document_id"], i["type"]) for i in svc.ledger.list_issues(status=status, limit=500)[0])


def ledger_state(svc):
    return ({i["id"]: (i["document_id"], i["type"], i["status"]) for i in svc.ledger.list_issues(status="all", limit=500)[0]},
            {(d["tenant_id"], d["document_id"]): d["status"] for d in svc.ledger.list_documents(limit=500)[0]})


# ------------------------------------------------------------------------------------- feature 1: versions
def test_f1_a_document_changed_in_s3_is_stale_until_it_is_indexed_again(stack):
    svc = stack.service()
    clean = svc.run_audit()
    assert clean.status == "completed" and issues(svc) == [] and clean.stats["health_score"] == 100.0

    stack.put("policy-05", 2)  # the employee policy is updated in S3; the pipeline has not run yet
    svc.run_audit()
    assert issues(svc) == [("policy-05", "stale_embedding")]
    live = svc.inspect("default", "policy-05")["version_check"]
    assert live["verdict"] == "version_mismatch" and "outdated revision" in live["explanation"]
    assert {r["property"]: r["status"] for r in live["rows"]}["Source hash"] == "mismatch"

    stack.index("policy-05", 2)  # the pipeline catches up
    svc.run_audit()
    assert issues(svc) == [] and issues(svc, "resolved") == [("policy-05", "stale_embedding")]
    assert svc.inspect("default", "policy-05")["version_check"]["verdict"] == "in_sync"


def test_f1_a_shorter_document_leaves_a_tail_and_a_changed_chunk_hash_is_noticed(stack):
    svc = stack.service()
    # policy-02 got shorter: the pipeline recorded 2 chunks but the old third chunk is still in the index
    stack.sql("DELETE FROM public.{c} WHERE document_id = 'policy-02' AND chunk_index = 2")
    stack.sql("UPDATE public.{m} SET expected_chunk_count = 2, indexed_chunk_count = 2 WHERE document_id = 'policy-02'")
    # policy-04: the manifest recorded a different chunk hash than the one the index holds
    stack.sql("UPDATE public.{c} SET chunk_hash = 'something-else' WHERE document_id = 'policy-04' AND chunk_index = 0")
    svc.run_audit()
    found = dict(issues(svc))
    assert found == {"policy-02": "superseded_active", "policy-04": "metadata_inconsistent"}
    tail = next(i for i in svc.ledger.list_issues(status="open", type="superseded_active")[0] if i["document_id"] == "policy-02")
    assert tail["evidence"]["unexpected_chunk_count"] == 1 and tail["evidence"]["removal_count"] == 1
    meta = next(i for i in svc.ledger.list_issues(status="open", type="metadata_inconsistent")[0] if i["document_id"] == "policy-04")
    assert [p["code"] for p in meta["evidence"]["problems"]] == ["chunk_hash_mismatch"]


# ------------------------------------------------------------------------------------- feature 4: deletion
def test_f4_a_confidential_document_deleted_from_s3_is_found_proved_searchable_and_verified_after_cleanup(stack):
    svc = stack.service()
    assert svc.run_audit().status == "completed" and issues(svc) == []  # the ledger now knows every document was in the source

    stack.s3.delete_object(Bucket=stack.bucket, Key="docs/policy-07.pdf")  # deleted from S3; its vectors and manifest row stay
    audit = svc.run_audit()
    assert issues(svc) == [("policy-07", "orphan_vector")]  # found although only the source's documents are audited
    assert audit.stats["deletion_check"] == {"documents_checked": 1, "with_remaining_vectors": 1, "verified_gone": 0}

    report = svc.verify_deletions()
    [doc] = report["documents"]
    assert doc["verdict"] == "deletion_mismatch" and doc["vectors"] == CHUNKS and doc["manifest_status"] == "success"
    assert doc["retrieval"]["reachable"] is True and doc["retrieval"]["best_rank"] == 1 and doc["retrieval"]["returned_chunks"] == CHUNKS
    assert [i["severity"] for i in svc.ledger.list_issues(status="open")[0]] == ["critical"]  # the real search proved it

    stack.drop_vectors("policy-07")  # the approved cleanup runs in the customer's pipeline
    after = svc.verify_deletions()
    assert after["documents"][0]["verdict"] == "manifest_not_updated" and after["documents"][0]["vectors"] == 0
    stack.sql("UPDATE public.{m} SET processing_status = 'deleted' WHERE document_id = 'policy-07'")
    final = svc.verify_deletions()
    assert final["documents"][0]["verdict"] == "verified_deleted" and issues(svc) == []


# ------------------------------------------------------------------------------------- feature 2: scan reliability
def test_f2_a_misbehaving_cluster_does_not_change_the_answer(stack):
    stack.drop_vectors("policy-03")  # one real fault so there is something to find
    healthy = stack.service()
    expected = healthy.run_audit()
    assert issues(healthy) == [("policy-03", "missing_embedding")]

    errors = [None, TimeoutError("read timed out"), Http(429, {"Retry-After": "1"}), Http(503), None, Http(502)]
    shaky = stack.service(client=FlakyClient(stack.q, errors))
    got = shaky.run_audit()
    scan = got.stats["scan"]
    assert got.status == "completed" and issues(shaky) == [("policy-03", "missing_embedding")]
    assert scan["retries"] == 4 and scan["recovered_errors"] == 2 and scan["rate_limited"] == 1 and scan["unrecoverable_errors"] == 0
    assert got.stats["health_score"] == expected.stats["health_score"] and ledger_state(shaky) == ledger_state(healthy)


def test_f2_a_scan_interrupted_by_a_dead_cluster_is_partial_provisional_and_resumable_to_the_same_result(stack):
    stack.drop_vectors("policy-03")
    stack.drop_vectors("policy-10", keep=1)  # a partial index in the LAST slice
    reference = stack.service()
    reference.run_audit()
    wanted = ledger_state(reference)
    assert dict(issues(reference)) == {"policy-03": "missing_embedding", "policy-10": "partial_index"}

    down = FlakyClient(stack.q, after=1, forever=Http(503))  # the first slice is read, then the node stays overloaded
    svc = stack.service(client=down)
    partial = svc.run_audit()
    scan = partial.stats["scan"]
    assert partial.status == "partial" and scan["slices_done"] == 1 and scan["documents_done"] == 4 and scan["percent"] == 33.3
    assert scan["provisional"] is True and scan["unrecoverable_errors"] == 1
    assert issues(svc) == [("policy-03", "missing_embedding")]  # only the finished slice is reported
    assert ("default", "policy-10") not in ledger_state(svc)[1]  # nothing at all is claimed about the documents not read
    assert svc.overview()["resumable_audit"]["documents_done"] == 4

    healed = stack.service.__func__  # (the same service object is reused below with a healthy client)
    svc.connectors.index = QdrantIndex(svc.settings, client=stack.q)  # the cluster is back
    done = svc.run_audit(resume=True)
    assert done.status == "completed" and done.stats["resume"]["resumed_from"] == partial.run_id
    assert done.stats["documents_total"] == 12 and done.stats["scan"]["resumed_from"] == partial.run_id
    assert ledger_state(svc) == wanted and healed is not None  # exactly what an audit that was never interrupted records, on real Postgres


def test_f2_a_deleted_document_between_the_stop_and_the_resume_is_cleaned_up_on_real_postgres(stack):
    stack.drop_vectors("policy-09", keep=1)  # partial index, so the ledger holds an open issue for it
    svc = stack.service()
    svc.run_audit()
    assert ("policy-09", "partial_index") in issues(svc)

    stack.drop_vectors("policy-09")  # now it is deleted everywhere
    stack.s3.delete_object(Bucket=stack.bucket, Key="docs/policy-09.pdf")
    stack.sql("DELETE FROM public.{m} WHERE document_id = 'policy-09'")
    stack.sql("DELETE FROM public.{c} WHERE document_id = 'policy-09'")
    svc.connectors.index = QdrantIndex(svc.settings, client=FlakyClient(stack.q, after=1, forever=Http(503)))
    svc.connectors.index._sleep = lambda s: None
    assert svc.run_audit().status == "partial"
    assert ("policy-09", "partial_index") in issues(svc)  # an incomplete audit proves nothing, so it closes nothing

    svc.connectors.index = QdrantIndex(svc.settings, client=stack.q)
    assert svc.run_audit(resume=True).status == "completed"
    assert ("policy-09", "partial_index") not in issues(svc) and ("default", "policy-09") not in ledger_state(svc)[1]
