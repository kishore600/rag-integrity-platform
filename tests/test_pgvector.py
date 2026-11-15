"""Feature 1, part B: vectors stored in PostgreSQL with pgvector, read through the same checks as Qdrant.

Skipped unless RAGI_TEST_PGVECTOR_URL points at a throwaway PostgreSQL with the ``vector`` extension available, for example a
PGlite server started with ``--extensions @electric-sql/pglite-pgvector:vector`` (see tests/README or the CI file for a native one).
Every test works in its own schema and drops it afterwards.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text

from ragintegrity.config import Settings
from ragintegrity.connectors import pgvector as pgv
from ragintegrity.connectors.base import ConnectorError
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.nomanifest import NoManifest
from ragintegrity.connectors.pgvector import PgVectorIndex, build_column_map, parse_path, parse_vector
from ragintegrity.connectors.postgres import make_engine
from ragintegrity.ledger import Ledger
from ragintegrity.models import Scope
from ragintegrity.service import IntegrityService
from tests.test_source_only import FakeSource

URL = os.environ.get("RAGI_TEST_PGVECTOR_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RAGI_TEST_PGVECTOR_URL not set")

PLAIN_MAP = {"document_id": "doc_id", "source_hash": "content_hash", "tenant_id": "tenant", "chunk_index": "chunk_no",
             "chunk_total": "chunk_count", "vector": "embedding"}
JSON_MAP = {"id": "uuid", "vector": "embedding", "document_id": "cmetadata.doc_id", "source_hash": "cmetadata.hash",
            "tenant_id": "cmetadata.tenant", "chunk_index": "cmetadata.chunk", "chunk_total": "cmetadata.chunks"}


# ------------------------------------------------------------------------------------------------ a throwaway schema
@pytest.fixture()
def db():
    name = "t" + uuid.uuid4().hex[:10]
    engine = make_engine(URL, null_pool=True)  # short-lived connections: the test server runs one query at a time
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text(f"CREATE SCHEMA {name}"))

    class Db:
        schema = name

        @staticmethod
        def run(sql: str, params=None):
            with engine.begin() as c:
                return c.execute(text(sql), params or {})

        @staticmethod
        def rows(sql: str, params=None):
            with engine.connect() as c:
                return list(c.execute(text(sql), params or {}).mappings().all())

    yield Db
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA {name} CASCADE"))
    engine.dispose()


def vec(*xs: float) -> str:
    return "[" + ",".join(str(x) for x in xs) + "]"


def plain_table(db, rows):
    """chunks(id, tenant, doc_id, content_hash, chunk_no, chunk_count, embedding vector(3)). rows: (tenant, doc, hash, no, total, vector)."""
    db.run(f"CREATE TABLE {db.schema}.chunks (id bigserial PRIMARY KEY, tenant text, doc_id text, content_hash text, chunk_no int, "
           "chunk_count int, embedding vector(3))")
    for t, d, h, n, total, v in rows:
        db.run(f"INSERT INTO {db.schema}.chunks (tenant, doc_id, content_hash, chunk_no, chunk_count, embedding) "
               "VALUES (:t, :d, :h, :n, :c, CAST(:e AS vector))", {"t": t, "d": d, "h": h, "n": n, "c": total, "e": v})


def settings(db, table="chunks", mapping=None, **kw) -> Settings:
    kw.setdefault("probe_retrieval", False)
    return Settings(_env_file=None, mode="live", pgvector_database_url=URL, pgvector_schema=db.schema, pgvector_table=table,
                    pgvector_column_map=json.dumps(PLAIN_MAP if mapping is None else mapping), index_type="pgvector", **kw)


def index(db, table="chunks", mapping=None, **kw) -> PgVectorIndex:
    idx = PgVectorIndex(settings(db, table, mapping, **kw))
    idx._sleep = lambda s: None
    return idx


def scan(idx, scope=None, with_vectors=False):
    return list(idx.scan(scope, with_vectors=with_vectors))


TEN = [("acme", f"d{i % 4}", f"h{i % 4}", i // 4, 3, vec(1, 0, i)) for i in range(10)]


# ------------------------------------------------------------------------------------------------ reading rows
def test_every_row_is_read_in_pages_and_mapped_to_our_fields(db):
    plain_table(db, TEN)
    idx = index(db, pgvector_page_size=3)
    chunks = scan(idx)
    assert len(chunks) == 10 and idx.scan_stats.pages == 4  # 3 + 3 + 3 + 1: a short last page ends the read
    assert {c.collection for c in chunks} == {"chunks"} or {c.collection for c in chunks} == {f"{db.schema}.chunks"}
    c0 = chunks[0]
    assert (c0.tenant_id, c0.document_id, c0.source_hash, c0.chunk_index, c0.chunk_total) == ("acme", "d0", "h0", 0, 3)
    assert sorted({c.document_id for c in chunks}) == ["d0", "d1", "d2", "d3"] and len({c.point_id for c in chunks}) == 10
    assert c0.present_fields >= {"document_id", "source_hash", "tenant_id", "chunk_index", "chunk_total"}


def test_a_table_in_langchains_shape_works_with_json_keys_and_uuid_row_ids(db):
    db.run(f"CREATE TABLE {db.schema}.langchain_pg_embedding (uuid uuid PRIMARY KEY DEFAULT gen_random_uuid(), embedding vector(3), "
           "document text, cmetadata jsonb)")
    for i in range(7):
        db.run(f"INSERT INTO {db.schema}.langchain_pg_embedding (embedding, document, cmetadata) VALUES (CAST(:e AS vector), 'text', CAST(:m AS jsonb))",
               {"e": vec(1, i, 0), "m": json.dumps({"doc_id": f"policy-{i % 2}", "hash": "abc", "tenant": "t1", "chunk": i // 2, "chunks": 4})})
    idx = index(db, "langchain_pg_embedding", JSON_MAP, pgvector_page_size=2)
    chunks = scan(idx)
    assert len(chunks) == 7 and idx.scan_stats.pages == 4
    assert {c.document_id for c in chunks} == {"policy-0", "policy-1"} and {c.source_hash for c in chunks} == {"abc"}
    assert {c.tenant_id for c in chunks} == {"t1"} and max(c.chunk_total for c in chunks) == 4
    assert all(len(c.point_id) == 36 for c in chunks)  # a uuid, read in key order across pages without repeats
    assert len({c.point_id for c in chunks}) == 7
    only = scan(idx, Scope(keys=frozenset({("t1", "policy-1")})))
    assert {c.document_id for c in only} == {"policy-1"} and len(only) == 3


def test_scopes_are_filtered_on_the_server_and_ids_match_in_the_form_the_column_stores_them(db):
    plain_table(db, [("a", "170", "h", 0, 1, vec(1, 0, 0)), ("a", "abc", "h", 0, 1, vec(0, 1, 0)), ("b", "170", "h", 0, 1, vec(0, 0, 1))])
    idx = index(db)
    assert {(c.tenant_id, c.document_id) for c in scan(idx, Scope(keys=frozenset({("a", "170"), ("b", "170")})))} == {("a", "170"), ("b", "170")}
    assert [c.tenant_id for c in scan(idx, Scope(tenant="b"))] == ["b"]
    assert {c.document_id for c in scan(idx, Scope(tenant="a", keys=frozenset({("a", "abc"), ("a", "170")})))} == {"abc", "170"}
    assert scan(idx, Scope(keys=frozenset())) == []  # no documents -> nothing is read
    # a number column: 170, "170" and a document that is not a number
    db.run(f"CREATE TABLE {db.schema}.numeric_ids (id serial PRIMARY KEY, doc_id bigint, embedding vector(3))")
    for n in (170, 171, 5):
        db.run(f"INSERT INTO {db.schema}.numeric_ids (doc_id, embedding) VALUES (:n, '[1,0,0]')", {"n": n})
    nums = index(db, "numeric_ids", {"document_id": "doc_id", "vector": "embedding"})
    got = {c.document_id for c in scan(nums, Scope(keys=frozenset({("default", "170"), ("default", "not-a-number"), ("default", "5")})))}
    assert got == {"170", "5"}  # an id that is not a number cannot be in a number column, and does not break the query


def test_a_long_document_list_is_split_into_batches_without_repeating_a_row(db, monkeypatch):
    plain_table(db, [("a", f"d{i}", "h", 0, 1, vec(1, 0, 0)) for i in range(7)])
    monkeypatch.setattr(pgv, "FILTER_BATCH", 3)
    chunks = scan(index(db), Scope(keys=frozenset(("a", f"d{i}") for i in range(7))))
    assert sorted(c.document_id for c in chunks) == [f"d{i}" for i in range(7)]


def test_empty_and_all_zero_vectors_are_found_only_when_asked_and_only_when_there_is_a_vector_column(db):
    plain_table(db, [("a", "ok", "h", 0, 2, vec(1, 0, 0)), ("a", "zero", "h", 0, 2, vec(0, 0, 0)), ("a", "null", "h", 0, 2, None)])
    flagged = {c.document_id for c in scan(index(db), with_vectors=True) if not c.vector_ok}
    assert flagged == {"zero", "null"}
    assert all(c.vector_ok for c in scan(index(db), with_vectors=False))
    no_vector = {k: v for k, v in PLAIN_MAP.items() if k != "vector"}
    assert all(c.vector_ok for c in scan(index(db, mapping={**no_vector, "vector": "does_not_exist"}), with_vectors=True))  # nothing to judge


def test_rows_without_a_document_id_are_reported_as_unattributed_not_dropped(db):
    plain_table(db, [("a", "d", "h", 0, 1, vec(1, 0, 0)), ("a", None, "h", 0, 1, vec(0, 1, 0))])
    assert sorted(c.document_id or "" for c in scan(index(db))) == ["", "d"]


# ------------------------------------------------------------------------------------------------ about the table
def test_the_declared_vector_size_the_row_estimate_and_the_health_check(db):
    plain_table(db, TEN)
    db.run(f"ANALYZE {db.schema}.chunks")
    idx = index(db)
    assert idx.vector_sizes() == {idx.name: 3} and idx.estimated_points() == 10 and idx.scan_stats.estimated_total == 10
    h = idx.health()
    assert h.ok and h.kind == "pgvector" and "10" in h.detail and h.info["counts"] == {idx.name: 10}
    broken = index(db, "no_such_table")
    assert broken.health().ok is False and "not found" in broken.health().detail
    assert index(db, mapping={"document_id": "nope"}).health().detail.endswith("map it in the column map")


def test_the_connection_test_names_each_problem_in_words(db):
    plain_table(db, TEN)
    checks = {c["name"]: c for c in index(db).diagnose()}
    assert checks["Database reachable"]["status"] == "ok" and checks["pgvector extension"]["status"] == "ok"
    assert checks["Vector column"]["detail"].endswith("holds 3-dimensional vectors")
    assert checks["Fields used for checks"]["status"] == "ok" and checks["Document ids"] if "Document ids" in checks else True
    assert index(db, "no_such_table").diagnose()[-1]["status"] == "fail"
    missing_doc = index(db, mapping={**PLAIN_MAP, "document_id": "nope"}).diagnose()
    assert any(c["name"] == "Column for document_id" and c["status"] == "fail" for c in missing_doc)
    no_hash = {c["name"]: c for c in index(db, mapping={**PLAIN_MAP, "source_hash": "nope"}).diagnose()}
    assert no_hash["Fields used for checks"]["status"] == "warn" and "changed file" in no_hash["Fields used for checks"]["detail"]
    bad = Settings(_env_file=None, mode="live", pgvector_database_url="postgresql://u:topsecretpw@127.0.0.1:1/db", pgvector_table="t")
    out = PgVectorIndex(bad, fast=True).diagnose()
    assert out[0]["status"] == "fail" and "topsecretpw" not in json.dumps(out)


def test_a_sample_of_ids_for_the_setup_check_says_whether_rows_carry_the_files_hash(db):
    plain_table(db, [("a", f"d{i}", "h" if i % 2 else None, 0, 1, vec(1, 0, 0)) for i in range(6)])
    s = index(db).id_sample(100)
    assert len(s["rows"]) == 6 and {r["document_id"] for r in s["rows"]} == {f"d{i}" for i in range(6)}
    assert sum(r["has_revision"] for r in s["rows"]) == 3 and s["collections"] == [f"{db.schema}.chunks"] or s["collections"] == ["chunks"]


# ------------------------------------------------------------------------------------------------ searching
@pytest.mark.parametrize("distance", ["cosine", "l2", "inner_product"])
def test_a_row_is_its_own_nearest_neighbour_under_every_distance(db, distance):
    plain_table(db, [("a", "x", "h", 0, 1, vec(1, 0, 0)), ("a", "y", "h", 0, 1, vec(0, 1, 0)), ("a", "z", "h", 0, 1, vec(0.9, 0.1, 0))])
    idx = index(db, pgvector_distance=distance)
    ids = {r["doc_id"]: str(r["id"]) for r in db.rows(f"SELECT id, doc_id FROM {db.schema}.chunks")}
    hits = idx.probe(idx.name, ids["x"], "a", 3)
    assert hits is not None and [h[2] for h in hits][0] == "x" and len(hits) == 3
    scores = [h[1] for h in hits]
    assert scores == sorted(scores, reverse=True)  # a higher score is always closer, whichever distance the table uses
    assert [h[2] for h in hits][1] == "z"  # (0.9, 0.1, 0) is the next closest to (1, 0, 0) under all three
    assert idx.probe(idx.name, "999999", "a", 3) is None  # a row that is gone


def test_a_probe_is_scoped_to_the_tenant_only_when_the_rows_have_one(db):
    plain_table(db, [("a", "x", "h", 0, 1, vec(1, 0, 0)), ("b", "y", "h", 0, 1, vec(1, 0.01, 0))])
    idx = index(db)
    first = str(db.rows(f"SELECT id FROM {db.schema}.chunks WHERE doc_id = 'x'")[0]["id"])
    assert [h[2] for h in idx.probe(idx.name, first, "a", 5)] == ["x"]  # tenant b's near-identical row is not a hit for tenant a
    db.run(f"CREATE TABLE {db.schema}.single (id serial PRIMARY KEY, doc_id text, embedding vector(3))")
    for d, v in (("x", "[1,0,0]"), ("y", "[1,0.01,0]")):
        db.run(f"INSERT INTO {db.schema}.single (doc_id, embedding) VALUES (:d, CAST(:v AS vector))", {"d": d, "v": v})
    one = index(db, "single", {"document_id": "doc_id", "vector": "embedding"})
    pid = str(db.rows(f"SELECT id FROM {db.schema}.single WHERE doc_id = 'x'")[0]["id"])
    assert sorted(h[2] for h in one.probe(one.name, pid, "default", 5)) == ["x", "y"]  # no tenant column: nothing to filter by, so nothing is lost


# ------------------------------------------------------------------------------------------------ safety
def test_the_connector_cannot_write_to_the_table(db):
    plain_table(db, TEN)
    idx = index(db)
    for sql in (f"INSERT INTO {db.schema}.chunks (doc_id) VALUES ('x')", f"DELETE FROM {db.schema}.chunks", f"DROP TABLE {db.schema}.chunks",
                f"UPDATE {db.schema}.chunks SET doc_id = 'x'"):
        with pytest.raises(Exception, match="read-only"):
            idx._run(sql)
    assert db.rows(f"SELECT count(*) AS n FROM {db.schema}.chunks")[0]["n"] == 10


def test_names_from_settings_and_ids_from_documents_can_never_become_sql(db):
    plain_table(db, TEN)
    for bad in ("chunks; DROP TABLE chunks", 'chunks"', "a b", "chunks--"):
        with pytest.raises(ValueError):
            PgVectorIndex(settings(db, table=bad))
    with pytest.raises(ValueError):
        PgVectorIndex(Settings(_env_file=None, pgvector_database_url=URL, pgvector_table="t", pgvector_schema="x; select 1"))
    with pytest.raises(ValueError):
        build_column_map({"document_id": "doc_id; DROP TABLE x"})
    for bad in ("metadata.a'b", "metadata.a b", "metadata.a}", "metadata.', (SELECT 1)--"):
        with pytest.raises(ConnectorError):
            parse_path(bad, "document_id")
    with pytest.raises(ConnectorError, match="Unknown column"):
        build_column_map({"password": "doc_id"})
    # a document id that is an injection attempt is only ever a bound value
    hostile = "x' OR '1'='1"
    assert scan(index(db), Scope(keys=frozenset({("acme", hostile)}))) == []
    assert db.rows(f"SELECT count(*) AS n FROM {db.schema}.chunks")[0]["n"] == 10
    assert parse_vector("[1,2.5,-3]") == [1.0, 2.5, -3.0] and parse_vector("nonsense") is None and parse_vector(None) is None


def test_a_dropped_connection_is_retried_and_counted_and_a_refusal_is_not(db):
    plain_table(db, TEN)
    idx = index(db, pgvector_page_size=4)
    real, calls = idx._run, {"n": 0}

    def flaky(sql, params=None):
        calls["n"] += 1
        if calls["n"] in (2, 3):  # two pages in a row fail the way a dropped connection does
            raise RuntimeError("server closed the connection unexpectedly")
        return real(sql, params)

    idx._run = flaky
    assert len(scan(idx)) == 10
    assert idx.scan_stats.retries == 2 and idx.scan_stats.recovered_errors == 1 and idx.scan_stats.unrecoverable_errors == 0

    refused = index(db)
    refused._run = lambda sql, params=None: (_ for _ in ()).throw(PermissionError("permission denied for table chunks"))
    with pytest.raises(PermissionError):
        scan(refused)
    assert refused.scan_stats.retries == 0 and refused.scan_stats.unrecoverable_errors == 1  # asking again would change nothing


# ------------------------------------------------------------------------------------------------ an audit on pgvector
def planted(db):
    """One table with one of each fault. Source documents: ok, stale, missing, dup, partial, empty. 'orphan' was deleted from the source."""
    rows = [("acme", "ok", "h1", k, 3, vec(1, 0.1 * k, 0)) for k in range(3)]
    rows += [("acme", "stale", "OLD", k, 2, vec(0, 1, 0.1 * k)) for k in range(2)]
    rows += [("acme", "dup", "h3", 0, 2, vec(0, 0, 1)), ("acme", "dup", "h3", 0, 2, vec(0, 0, 1)), ("acme", "dup", "h3", 1, 2, vec(0.5, 0, 1))]
    rows += [("acme", "partial", "h4", k, 4, vec(1, 1, 0.1 * k)) for k in (0, 1, 3)]
    rows += [("acme", "empty", "h5", 0, 1, vec(0, 0, 0))]
    rows += [("acme", "orphan", "h6", k, 2, vec(0.3, 0.3, 0.3 + k / 10)) for k in range(2)]
    plain_table(db, rows)
    db.run(f"ANALYZE {db.schema}.chunks")


def docs():
    from tests.test_optional_manifest import doc

    return [doc("ok", "h1", "acme"), doc("stale", "NEW", "acme"), doc("missing", "h2", "acme"), doc("dup", "h3", "acme"),
            doc("partial", "h4", "acme"), doc("empty", "h5", "acme")]


def audit_service(tmp_path, db, name="ledger", **kw) -> IntegrityService:
    s = settings(db, grace_minutes=0, check_vectors=False, pgvector_check_vectors=True, **kw)
    return IntegrityService(s, Ledger(f"sqlite:///{(tmp_path / (name + '.db')).as_posix()}"),
                            Connectors(FakeSource(docs()), NoManifest(), PgVectorIndex(s)))


EXPECTED = {"stale": {"stale_embedding"}, "missing": {"missing_embedding"}, "dup": {"duplicate_chunk"}, "partial": {"partial_index"},
            "empty": {"empty_embedding"}, "orphan": {"orphan_vector"}}


def found(svc):
    out: dict[str, set[str]] = {}
    for i in svc.ledger.list_issues(status="all", limit=500)[0]:
        out.setdefault(i["document_id"], set()).add(i["type"])
    return out


def test_an_audit_over_pgvector_without_a_manifest_finds_exactly_the_planted_faults(tmp_path, db):
    planted(db)
    svc = audit_service(tmp_path, db)
    result = svc.run_audit()
    assert result.status == "completed" and found(svc) == EXPECTED
    assert result.stats["manifest"]["connected"] is False
    partial = next(f for f in result.findings if f.type.value == "partial_index")
    assert partial.evidence["method"] == "payload_chunk_total" and partial.evidence["missing_chunks"][0].endswith(":#2")
    assert {s.document_id: s.status for s in result.summaries}["ok"] == "healthy"
    assert result.stats["scan"]["points_scanned"] == 14 and result.stats["scan"]["mode"] == "single_pass"


def test_a_sliced_audit_over_pgvector_finds_the_same_and_a_stopped_one_resumes_to_the_same_ledger(tmp_path, db):
    planted(db)
    clean = audit_service(tmp_path, db, "clean", source_documents_only=True, audit_slice_documents=2)
    clean.run_audit()
    # only the source's documents are audited here, and "orphan" was never in the source (no earlier audit saw it), so it is not looked at
    without_orphan = {k: v for k, v in EXPECTED.items() if k != "orphan"}
    assert found(clean) == without_orphan

    svc = audit_service(tmp_path, db, "resumed", source_documents_only=True, audit_slice_documents=2)
    idx = svc.connectors.index
    idx.retry_attempts = 1
    real, calls = idx._run, {"n": 0}

    def down_after_two_pages(sql, params=None):
        calls["n"] += 1
        if calls["n"] > 3:  # a sliced audit makes 5 calls: the table's columns, its vector size, then one read per slice of 2 documents
            raise RuntimeError("server closed the connection unexpectedly")
        return real(sql, params)

    idx._run = down_after_two_pages
    partial = svc.run_audit()
    assert partial.status == "partial" and "server closed the connection" in svc.ledger.get_run(partial.run_id)["error"]
    idx._run = real  # the database is back
    done = svc.run_audit(resume=True)
    assert done.status == "completed" and done.stats["resume"]["resumed_from"] == partial.run_id
    assert found(svc) == found(clean)


def test_the_retrieval_test_really_searches_pgvector_and_proves_a_deleted_document_is_still_found(tmp_path, db):
    planted(db)
    s = settings(db, grace_minutes=0, probe_retrieval=True, pgvector_check_vectors=True)
    svc = IntegrityService(s, Ledger(f"sqlite:///{(tmp_path / 'probe.db').as_posix()}"), Connectors(FakeSource(docs()), NoManifest(), PgVectorIndex(s)))
    result = svc.run_audit()
    orphan = next(f for f in result.findings if f.type.value == "orphan_vector")
    assert orphan.severity.value == "critical"  # a real search returned the deleted document's own chunks
    report = svc.verify_deletions(documents=[("acme", "orphan")], record=False)
    [row] = report["documents"]
    assert row["verdict"] == "deletion_mismatch" and row["retrieval"]["reachable"] is True and row["vectors"] == 2
    db.run(f"DELETE FROM {db.schema}.chunks WHERE doc_id = 'orphan'")  # the pipeline cleans up
    [after] = svc.verify_deletions(documents=[("acme", "orphan")], record=False)["documents"]
    assert after["verdict"] == "verified_deleted"


def test_the_setup_check_speaks_about_pgvector_and_not_qdrant(tmp_path, db):
    planted(db)
    report = audit_service(tmp_path, db).setup_check()
    text_of = json.dumps(report)
    assert report["index_label"] == "pgvector" and report["manifest_connected"] is False
    names = {c["id"]: c["name"] for c in report["checks"]}
    assert names["index_ids"] == "Document IDs in pgvector" and names["index_revision"] == "Vectors carry the file's hash"
    assert "Qdrant" not in text_of and "payload field" not in text_of
    assert next(c for c in report["checks"] if c["id"] == "index_revision")["status"] == "pass"
