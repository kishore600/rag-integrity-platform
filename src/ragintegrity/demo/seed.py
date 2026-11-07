"""Write a ``DemoWorld`` into real S3 / PostgreSQL / Qdrant so the *live* connectors can be tried end to end.

Used by ``scripts/seed_live.py`` (docker-compose stack) and by the live-mode integration test. This is the
only code in the project that writes to those systems, and only to demo infrastructure.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .pipeline import make_text
from .world import COLLECTION, TARGET_FP, DemoWorld

MANIFEST_COLUMNS = (
    "tenant_id", "document_id", "source_uri", "source_version", "source_hash", "parsed_hash", "parser_version",
    "chunking_version", "chunk_size", "chunk_overlap", "embedding_model", "embedding_model_version", "embedding_dim",
    "preprocessing", "expected_chunk_count", "indexed_chunk_count", "indexed_version", "processing_status",
    "last_verified_at", "updated_at", "acl_hash",
)


def seed_s3(client: Any, bucket: str, world: DemoWorld, prefix: str = "") -> int:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)
    n = 0
    for (tenant, doc), src in world.sources.items():
        body = make_text(doc, world.versions[(tenant, doc)]).encode()
        client.put_object(Bucket=bucket, Key=f"{prefix}{tenant}/{doc}", Body=body, Metadata={"sha256": src.source_hash or ""})
        n += 1
    return n


def seed_manifest(engine: Engine, world: DemoWorld, schema: str | None = None) -> int:
    q = f"{schema}." if schema else ""
    ts = "timestamptz" if engine.dialect.name == "postgresql" else "text"
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {q}rag_chunk_manifest"))
        c.execute(text(f"DROP TABLE IF EXISTS {q}rag_document_manifest"))
        c.execute(text(f"""CREATE TABLE {q}rag_document_manifest (
            tenant_id text NOT NULL, document_id text NOT NULL, source_uri text, source_version text, source_hash text,
            parsed_hash text, parser_version text, chunking_version text, chunk_size integer, chunk_overlap integer,
            embedding_model text, embedding_model_version text, embedding_dim integer, preprocessing text,
            expected_chunk_count integer, indexed_chunk_count integer, indexed_version text, processing_status text,
            last_verified_at {ts}, updated_at {ts}, acl_hash text, PRIMARY KEY (tenant_id, document_id))"""))
        c.execute(text(f"""CREATE TABLE {q}rag_chunk_manifest (
            tenant_id text NOT NULL, document_id text NOT NULL, chunk_id text NOT NULL, chunk_index integer,
            chunk_hash text, PRIMARY KEY (tenant_id, document_id, chunk_id))"""))
        rows = []
        for m in world.manifest.values():
            fp = m.fingerprint
            rows.append({
                "tenant_id": m.tenant_id, "document_id": m.document_id, "source_uri": m.source_uri,
                "source_version": m.source_version, "source_hash": m.source_hash, "parsed_hash": m.parsed_hash,
                "parser_version": fp.parser_version, "chunking_version": fp.chunking_version, "chunk_size": fp.chunk_size,
                "chunk_overlap": fp.chunk_overlap, "embedding_model": fp.embedding_model,
                "embedding_model_version": fp.embedding_model_version, "embedding_dim": fp.embedding_dim,
                "preprocessing": fp.preprocessing, "expected_chunk_count": m.expected_chunk_count,
                "indexed_chunk_count": m.indexed_chunk_count, "indexed_version": m.indexed_version,
                "processing_status": m.processing_status, "last_verified_at": m.last_verified_at, "updated_at": m.updated_at,
                "acl_hash": m.acl_hash,
            })
        if rows:
            cols = ", ".join(MANIFEST_COLUMNS)
            vals = ", ".join(f":{k}" for k in MANIFEST_COLUMNS)
            c.execute(text(f"INSERT INTO {q}rag_document_manifest ({cols}) VALUES ({vals})"), rows)
        chunk_rows = [{"t": r.tenant_id, "d": r.document_id, "c": r.chunk_id, "i": r.chunk_index, "h": r.chunk_hash}
                      for by in world.chunk_manifest.values() for r in by.values()]
        if chunk_rows:
            c.execute(text(f"INSERT INTO {q}rag_chunk_manifest VALUES (:t, :d, :c, :i, :h)"), chunk_rows)
    return len(rows)


def seed_qdrant(client: Any, world: DemoWorld, collection: str = COLLECTION) -> int:
    from qdrant_client import models as qm

    existing = {c.name for c in client.get_collections().collections}
    if collection in existing:
        client.delete_collection(collection)
    client.create_collection(collection, vectors_config=qm.VectorParams(size=TARGET_FP.embedding_dim or 16, distance=qm.Distance.COSINE))
    points = [qm.PointStruct(id=pid, vector=sp.vector, payload=sp.payload) for pid, sp in world.points.items()]
    for i in range(0, len(points), 256):
        client.upsert(collection, points[i : i + 256])
    return len(points)
