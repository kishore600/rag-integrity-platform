"""Every SQL example in docs/guides runs on a real pgvector database and finds exactly the problem it describes.

The SQL is read from the guides themselves, so a guide cannot drift from what is tested. Skipped unless RAGI_TEST_PGVECTOR_URL points at a
throwaway PostgreSQL with the ``vector`` extension available (CI sets it; see tests/test_pgvector.py for running one locally).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

URL = os.environ.get("RAGI_TEST_PGVECTOR_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RAGI_TEST_PGVECTOR_URL not set")

GUIDES = Path(__file__).parent.parent / "docs" / "guides"
DIM = 1536


def sql_blocks(name: str) -> list[str]:
    text = (GUIDES / name).read_text(encoding="utf-8")
    return [b.strip() for b in re.findall(r"```sql\n(.*?)```", text, re.S)]


def guide(prefix: str) -> str:
    return next(p.name for p in GUIDES.glob(f"{prefix}-*.md"))


def vec(*hot: int, zero: bool = False) -> str:
    v = [0.0] * DIM
    if not zero:
        for i in hot:
            v[i] = 1.0
    return "[" + ",".join(str(x) for x in v) + "]"


SOURCES = [  # document_id, sha256, tenant_id
    ("ok.pdf", "h-ok", "acme"),
    ("missing.pdf", "h-missing", "acme"),  # 01: in storage, nothing indexed
    ("stale.pdf", "h-new", "acme"),  # 02: the file changed, the chunks did not
    ("twover.pdf", "h-v2", "acme"),  # 03: old and new chunks both live
    ("partial.pdf", "h-p", "acme"),  # 05: 2 of 3 chunks
    ("dup.pdf", "h-d", "acme"),  # 06: chunk 0 written twice
    ("zero.pdf", "h-z", "acme"),  # 07: a NULL and an all-zero vector
    ("tenant.pdf", "h-t", "globex"),  # 08: chunks tagged with the wrong tenant
]
CHUNKS = [  # document_id, chunk_index, chunk_total, source_hash, tenant_id, embedding
    ("ok.pdf", 0, 2, "h-ok", "acme", vec(1)), ("ok.pdf", 1, 2, "h-ok", "acme", vec(2)),
    ("stale.pdf", 0, 1, "h-old", "acme", vec(3)),
    ("twover.pdf", 0, 2, "h-v1", "acme", vec(4)), ("twover.pdf", 1, 2, "h-v1", "acme", vec(5)),
    ("twover.pdf", 0, 2, "h-v2", "acme", vec(6)), ("twover.pdf", 1, 2, "h-v2", "acme", vec(7)),
    ("partial.pdf", 0, 3, "h-p", "acme", vec(8)), ("partial.pdf", 1, 3, "h-p", "acme", vec(9)),
    ("dup.pdf", 0, 2, "h-d", "acme", vec(10)), ("dup.pdf", 0, 2, "h-d", "acme", vec(10)), ("dup.pdf", 1, 2, "h-d", "acme", vec(11)),
    ("zero.pdf", 0, 3, "h-z", "acme", None), ("zero.pdf", 1, 3, "h-z", "acme", vec(zero=True)), ("zero.pdf", 2, 3, "h-z", "acme", vec(12)),
    ("tenant.pdf", 0, 1, "h-t", "acme", vec(13)),
    ("deleted.pdf", 0, 2, "h-x", "acme", vec(14, 15)), ("deleted.pdf", 1, 2, "h-x", "acme", vec(15, 14)),  # 04: file gone, chunks not
]


@pytest.fixture()
def db():
    import psycopg

    schema = f"guides_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path TO {schema}, public")
        for statement in sql_blocks("README.md")[0].split(";"):  # the layout the guides document
            if statement.strip():
                conn.execute(statement)
        conn.cursor().executemany("INSERT INTO source_files (document_id, sha256, tenant_id) VALUES (%s, %s, %s)", SOURCES)
        conn.cursor().executemany(
            "INSERT INTO chunks (document_id, chunk_index, chunk_total, source_hash, tenant_id, embedding) VALUES (%s, %s, %s, %s, %s, %s::vector)",
            CHUNKS,
        )
        try:
            yield conn
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def rows(conn, sql: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(sql).fetchall()]


def test_every_guide_has_the_sql_this_test_expects():
    assert len(sql_blocks("README.md")) == 1
    expected = {"01": 1, "02": 1, "03": 2, "04": 2, "05": 1, "06": 2, "07": 1, "08": 1}
    for prefix, n in expected.items():
        assert len(sql_blocks(guide(prefix))) == n, guide(prefix)


def test_01_missing_documents(db):
    assert rows(db, sql_blocks(guide("01"))[0]) == [("missing.pdf",)]


def test_02_stale_embeddings(db):
    # twover.pdf still has chunks from its old version, so it is stale too
    assert rows(db, sql_blocks(guide("02"))[0]) == [("stale.pdf",), ("twover.pdf",)]


def test_03_two_versions_and_the_fix(db):
    check, fix = sql_blocks(guide("03"))
    assert rows(db, check) == [("twover.pdf", 2)]
    db.execute(fix)
    assert rows(db, check) == []
    left = rows(db, "SELECT document_id, source_hash FROM chunks WHERE document_id IN ('twover.pdf', 'stale.pdf') ORDER BY 1, 2")
    assert left == [("twover.pdf", "h-v2"), ("twover.pdf", "h-v2")]  # only the current version is left


def test_04_deleted_documents_and_the_search_probe(db):
    check, probe = sql_blocks(guide("04"))
    assert rows(db, check) == [("deleted.pdf", 2)]
    found = rows(db, probe.replace("deleted-doc.pdf", "deleted.pdf"))
    assert len(found) == 5 and found[0][1] == "deleted.pdf"  # its own vector brings it back first: still searchable


def test_05_half_indexed_documents(db):
    assert rows(db, sql_blocks(guide("05"))[0]) == [("partial.pdf", 3, 2)]


def test_06_duplicate_chunks_and_the_fix(db):
    check, fix = sql_blocks(guide("06"))
    assert rows(db, check) == [("dup.pdf", 0, 2), ("twover.pdf", 0, 2), ("twover.pdf", 1, 2)]
    db.execute(fix)
    # the true duplicate is gone; the two versions of twover.pdf are a different problem (guide 03) and are left alone
    assert rows(db, check) == [("twover.pdf", 0, 2), ("twover.pdf", 1, 2)]
    assert rows(db, "SELECT count(*) FROM chunks WHERE document_id = 'dup.pdf'") == [(2,)]


def test_07_empty_and_zero_vectors(db):
    found = rows(db, sql_blocks(guide("07"))[0])
    assert [(d, i) for _id, d, i in found] == [("zero.pdf", 0), ("zero.pdf", 1)]


def test_08_wrong_tenant(db):
    found = rows(db, sql_blocks(guide("08"))[0])
    assert [(d, chunk, source) for _id, d, chunk, source in found] == [("tenant.pdf", "acme", "globex")]
