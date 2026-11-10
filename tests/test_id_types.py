"""Numbers versus text: 2329961, 2329961.0 and "2329961" are the same document.

A manifest column can be a bigint, a payload can hold a number, and a file name is always text. Before this, a number
in one system and the same number written as text in another looked like two different documents: Qdrant filters on
text ids found nothing in an index that stored numbers, so every document looked unindexed (a false alarm), and a decimal
(2329961.0) never matched anything.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sqlalchemy import create_engine, text

from ragintegrity.config import Settings
from ragintegrity.connectors.payload import build_payload_map, payload_to_chunk
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.ids import id_kind, loose_id, normalize_id, number_form
from ragintegrity.models import IssueType, ManifestRow, Scope, SourceDoc
from tests.test_source_only import FakeManifest, FakeSource


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# ------------------------------------------------------------------------------------- the helpers
@pytest.mark.parametrize("raw, expected", [
    (2329961, "2329961"), ("2329961", "2329961"), (2329961.0, "2329961"), (Decimal("2329961.00"), "2329961"),
    (0, "0"), (-7, "-7"), (1e15, "1000000000000000"),
    (12.5, "12.5"), (Decimal("12.50"), "12.50"), (float("nan"), "nan"), (float("inf"), "inf"),
    ("0170", "0170"), (" 170 ", " 170 "), ("abc", "abc"), (True, "True"), (None, None),
])
def test_normalize_id_writes_every_whole_number_the_same_way(raw, expected):
    assert normalize_id(raw) == expected


@pytest.mark.parametrize("text_id, number", [
    ("170", 170), ("0", 0), ("-5", -5), ("2329961", 2329961),
    ("0170", None), (" 170", None), ("170.0", None), ("+5", None), ("1e3", None), ("-0", None), ("", None), ("abc", None),
    ("1" * 19, None),  # would not fit in a 64-bit integer: kept as text
])
def test_a_number_form_exists_only_for_ids_written_exactly_as_a_number(text_id, number):
    assert number_form(text_id) == number


def test_id_kind_tells_how_an_id_is_stored():
    assert [id_kind(v) for v in (170, 170.0, Decimal("1"), "170", "bill-170", True, None)] == \
        ["integer", "decimal", "decimal", "digits", "text", "other", "other"]


def test_loose_ids_ignore_case_spaces_and_leading_zeros_only():
    assert loose_id(" 0170 ") == loose_id("170") and loose_id("ABC") == loose_id("abc")
    assert loose_id("bill-170") != loose_id("170")


# ------------------------------------------------------------------------------------- Qdrant payloads
def test_a_payload_number_becomes_the_same_id_as_the_text(tmp_path):
    pmap = build_payload_map({"document_id": "source_id", "tenant_id": "org", "chunk_id": "n"})
    for raw in (2329961, 2329961.0, "2329961"):
        c = payload_to_chunk("c", 1, {"source_id": raw, "org": 7.0, "n": 3}, pmap)
        assert (c.document_id, c.tenant_id, c.chunk_id) == ("2329961", "7", "3")
    assert payload_to_chunk("c", 1, {"source_id": ""}, pmap).document_id is None  # blank stays missing


# ------------------------------------------------------------------------------------- the manifest
@pytest.fixture()
def table(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE manifest (doc INTEGER, tenant REAL, uri TEXT, status TEXT)"))
        c.execute(text("INSERT INTO manifest VALUES (2329961, 7.0, 's3://b/1', 'success'), (2331101, 7.0, 's3://b/2', 'success'), "
                       "(NULL, 7.0, 's3://b/3', 'success')"))
    return engine


def manifest(engine) -> PostgresManifest:
    return PostgresManifest(settings(manifest_table="manifest",
                                     manifest_column_map='{"document_id": "doc", "tenant_id": "tenant", "source_uri": "uri", "processing_status": "status"}'),
                            engine)


def test_a_number_column_gives_text_ids_and_rows_without_an_id_are_counted_not_called_none(table):
    m = manifest(table)
    rows = list(m.documents())
    assert sorted(r.key for r in rows) == [("7", "2329961"), ("7", "2331101")]  # 7.0 -> "7", NULL id skipped, no "None" document
    assert m.empty_ids == 1


def test_a_scoped_read_matches_text_ids_against_a_number_column(table):
    rows = list(manifest(table).documents(Scope(keys=frozenset({("7", "2329961"), ("7", "999")}))))
    assert [r.key for r in rows] == [("7", "2329961")]


# ------------------------------------------------------------------------------------- Qdrant filters
class FakeClient:
    """Records scroll calls; can be told to refuse a filter that has a number branch (as a strict server might)."""

    def __init__(self, refuse_numbers=False, error=None):
        self.calls, self.refuse_numbers, self.error = [], refuse_numbers, error

    def scroll(self, **kw):
        self.calls.append(kw)
        flt = kw["scroll_filter"]
        if self.error is not None:
            raise self.error
        if self.refuse_numbers and flt is not None and any(isinstance(c, qm.Filter) for c in flt.must):
            raise _Rejected("Bad request: Index required but not found")
        return [], None


class _Rejected(Exception):
    status_code = 400


def index(client) -> QdrantIndex:
    return QdrantIndex(settings(qdrant_collections="c", qdrant_payload_map='{"document_id": "source_id"}'), client=client)


def _as_text_and_numbers(flt):
    [cond] = flt.must
    text_cond, number_cond = cond.should
    return list(text_cond.match.any), list(number_cond.match.any)


def test_a_filter_on_digit_ids_matches_both_the_text_and_the_number(world=None):
    client = FakeClient()
    list(index(client).scan(Scope(keys=frozenset({("default", "170"), ("default", "2329961")}))))
    assert _as_text_and_numbers(client.calls[0]["scroll_filter"]) == (["170", "2329961"], [170, 2329961])


def test_ids_that_are_not_plain_numbers_get_no_number_branch():
    client = FakeClient()
    list(index(client).scan(Scope(keys=frozenset({("default", "0170"), ("default", "bill-170")}))))
    [cond] = client.calls[0]["scroll_filter"].must
    assert isinstance(cond, qm.FieldCondition) and cond.match.any == ["0170", "bill-170"]


def test_a_numeric_tenant_name_is_matched_both_ways_too():
    client = FakeClient()
    list(index(client).scan(Scope(tenant="42")))
    [cond] = client.calls[0]["scroll_filter"].must
    assert [c.match.value for c in cond.should] == ["42", 42]


def test_a_server_that_refuses_the_number_form_falls_back_to_text_only_for_the_rest_of_the_scan():
    client = FakeClient(refuse_numbers=True)
    list(index(client).scan(Scope(keys=frozenset({("default", "170")}))))
    assert len(client.calls) == 2  # the refused attempt, then the retry
    retry = client.calls[1]["scroll_filter"].must[0]
    assert isinstance(retry, qm.FieldCondition) and retry.match.any == ["170"]


def test_a_failure_that_is_not_a_refusal_is_not_retried():
    client = FakeClient(error=TimeoutError("timed out"))
    with pytest.raises(TimeoutError):
        list(index(client).scan(Scope(keys=frozenset({("default", "170")}))))
    assert len(client.calls) == 1


def test_a_refusal_that_also_hits_the_text_only_filter_is_raised_unchanged():
    client = FakeClient(error=_Rejected("Bad request: Index required but not found"))
    with pytest.raises(_Rejected):
        list(index(client).scan(Scope(keys=frozenset({("default", "170")}))))
    assert len(client.calls) == 2


# ------------------------------------------------------------------------------------- a whole audit
class ChunkIndex:
    """An index whose payloads are read through the real payload mapping (numbers stay numbers in the payload)."""

    def __init__(self, payloads):
        pmap = build_payload_map({"document_id": "source_id"})
        self.chunks = [payload_to_chunk("c", i, p, pmap) for i, p in enumerate(payloads)]

    def collections(self):
        return ["c"]

    def vector_sizes(self):
        return {"c": 3}

    def scan(self, scope=None, with_vectors=False):
        return iter(self.chunks)

    def probe(self, *a, **k):
        return None


def test_documents_whose_ids_are_numbers_in_the_index_and_the_database_are_healthy_not_missing():
    sha = "a" * 64
    src = FakeSource([SourceDoc("default", "2329961", "s3://b/bills/2329961/2329961.pdf", source_hash=sha, size_bytes=10)])
    man = FakeManifest([ManifestRow("default", normalize_id(2329961.0), processing_status="success", source_hash=sha,
                                    expected_chunk_count=2, indexed_chunk_count=2)])
    idx = ChunkIndex([{"source_id": 2329961, "source_hash": sha, "chunk_index": i, "chunk_id": f"c{i}"} for i in range(2)])
    result = run_reconciliation(src, man, idx, AuditOptions(probe=False, required_fields=["document_id"]))
    bad = [f for f in result.findings if f.type in (IssueType.MISSING_EMBEDDING, IssueType.ORPHAN_VECTOR, IssueType.MANIFEST_ORPHAN)]
    assert bad == [], [(f.type.value, f.document_id) for f in bad]
    assert [s.status for s in result.summaries] == ["healthy"]


# ------------------------------------------------------------------------------------- a real Qdrant server
URL, KEY = os.environ.get("RAGI_TEST_QDRANT_URL"), os.environ.get("RAGI_TEST_QDRANT_KEY")


@pytest.mark.skipif(not URL, reason="RAGI_TEST_QDRANT_URL not set")
def test_a_real_server_finds_documents_whether_it_stores_their_ids_as_numbers_or_text():
    client = QdrantClient(url=URL, api_key=KEY, timeout=30)
    name = "ragi_test_id_types"
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(name, vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    try:
        client.upsert(name, wait=True, points=[
            qm.PointStruct(id=1, vector=[1, 0, 0], payload={"source_id": 2329961}),       # a number
            qm.PointStruct(id=2, vector=[0, 1, 0], payload={"source_id": "2331101"}),     # text
            qm.PointStruct(id=3, vector=[0, 0, 1], payload={"source_id": "bill-7"}),      # text that is not a number
            qm.PointStruct(id=4, vector=[1, 1, 0], payload={"source_id": 999}),           # a document that is not asked for
        ])
        idx = QdrantIndex(settings(qdrant_url=URL, qdrant_api_key=KEY, qdrant_collections=name,
                                   qdrant_payload_map='{"document_id": "source_id"}'))
        asked = Scope(keys=frozenset({("default", "2329961"), ("default", "2331101"), ("default", "bill-7")}))
        assert sorted(c.document_id for c in idx.scan(asked)) == ["2329961", "2331101", "bill-7"]
        sample = idx.id_sample(10)
        assert sorted(str(r["document_id"]) for r in sample["rows"]) == ["2329961", "2331101", "999", "bill-7"]
        assert {type(r["document_id"]) for r in sample["rows"]} == {int, str}  # the sample keeps the stored type
    finally:
        client.delete_collection(name)


# ------------------------------------------------------------------------------------- a real Postgres
PG_URL = os.environ.get("RAGI_TEST_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="RAGI_TEST_PG_URL not set")
@pytest.mark.parametrize("column_type", ["BIGINT", "NUMERIC(12,2)", "DOUBLE PRECISION", "TEXT"])
def test_a_real_postgres_id_column_of_any_type_gives_the_same_text_ids_and_scoped_reads_work(column_type):
    from ragintegrity.config import normalize_db_url

    engine = create_engine(normalize_db_url(PG_URL), connect_args={"prepare_threshold": None})
    value = {"BIGINT": "2329961", "NUMERIC(12,2)": "2329961.00", "DOUBLE PRECISION": "2329961.0", "TEXT": "'2329961'"}[column_type]
    other = {"BIGINT": "2331101", "NUMERIC(12,2)": "2331101.00", "DOUBLE PRECISION": "2331101.0", "TEXT": "'2331101'"}[column_type]
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS public.ragi_test_numeric_ids"))
        c.execute(text(f"CREATE TABLE public.ragi_test_numeric_ids (external_doc_id {column_type}, s3_url TEXT)"))
        c.execute(text(f"INSERT INTO public.ragi_test_numeric_ids VALUES ({value}, 'a'), ({other}, 'b'), (NULL, 'c')"))
    try:
        m = PostgresManifest(settings(manifest_table="ragi_test_numeric_ids", manifest_schema="public",
                                      manifest_column_map='{"document_id": "external_doc_id", "source_uri": "s3_url"}'), engine)
        assert sorted(r.document_id for r in m.documents()) == ["2329961", "2331101"] and m.empty_ids == 1
        one = list(m.documents(Scope(keys=frozenset({("default", "2329961"), ("default", "nope")}))))
        assert [(r.document_id, r.source_uri) for r in one] == [("2329961", "a")]  # a text parameter against a number column
    finally:
        with engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS public.ragi_test_numeric_ids"))
        engine.dispose()


def test_a_scoped_read_never_compares_a_non_number_with_a_number_column(table):
    m = manifest(table)
    rows = list(m.documents(Scope(tenant="7", keys=frozenset({("7", "2331101"), ("7", "bill-9")}))))
    assert [r.document_id for r in rows] == ["2331101"]
    assert list(m.documents(Scope(keys=frozenset({("7", "bill-9")})))) == []  # nothing that could be a number was asked for
    assert list(m.documents(Scope(tenant="acme"))) == []  # a tenant name that is not a number cannot be in a number column
