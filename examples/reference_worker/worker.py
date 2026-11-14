"""Reference repair worker: the receiving end of the RAG Integrity repair webhook.

RAG Integrity itself is read-only. When you approve a repair it POSTs a signed payload here, and *your* code
does the writing. This file shows the contract with a toy pipeline (utf-8 text -> fixed-size chunks ->
hash-based vectors). Replace ``Worker.process_document`` with your real parse/chunk/embed code; keep the rest.

The contract
------------
* Verify ``X-Ragi-Signature`` (HMAC-SHA256 of ``"<X-Ragi-Timestamp>.<raw body>"``) and reject stale timestamps.
* phase ``reindex``: for each item, rebuild the document from the *latest* source and ADD / REPLACE its vectors
  with deterministic point ids (so a retry overwrites instead of duplicating). Never delete in this phase.
* phase ``cleanup``: only now delete the exact point ids you are given, and retire manifest rows of deleted documents.
* Answer 2xx quickly; do the work in the background and POST to ``callback_url`` (same signature scheme) when done.

Run it:  uvicorn examples.reference_worker.worker:app --port 9000   (see docker-compose.yml)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ragintegrity.demo.pipeline import build_points, embed
from ragintegrity.models import Fingerprint, sha256_hex

TOLERANCE_S = 300
MANIFEST_COLS = (
    "tenant_id", "document_id", "source_uri", "source_version", "source_hash", "parsed_hash", "parser_version",
    "chunking_version", "chunk_size", "chunk_overlap", "embedding_model", "embedding_dim", "preprocessing",
    "expected_chunk_count", "indexed_chunk_count", "indexed_version", "processing_status", "acl_hash",
)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str | None, signature: str | None, body: bytes) -> bool:
    try:
        if abs(time.time() - float(timestamp or "")) > TOLERANCE_S:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sign(secret, timestamp or "", body), signature or "")


class Worker:
    def __init__(self, s3: Any, bucket: str, qdrant: Any, manifest_engine: Engine, collection: str = "kb_main",
                 schema: str | None = None, key_prefix: str = "") -> None:
        self.s3, self.bucket, self.qdrant, self.engine = s3, bucket, qdrant, manifest_engine
        self.collection, self.prefix = collection, key_prefix
        self.q = f"{schema}." if schema else ""

    # ------------------------------------------------------------------ phase: reindex (add/replace only)
    def reindex(self, payload: dict[str, Any]) -> int:
        from qdrant_client import models as qm

        target = Fingerprint.from_dict(payload.get("target_fingerprint"))
        done = 0
        for item in payload["items"]:
            tenant, doc = item["tenant_id"], item["document_id"]
            obj = self.s3.get_object(Bucket=self.bucket, Key=f"{self.prefix}{tenant}/{doc}")
            body = obj["Body"].read()
            source_hash = sha256_hex(body)
            text_content = body.decode("utf-8", errors="replace")  # <- your parser goes here
            version = obj.get("VersionId") or obj["ETag"].strip('"')
            points, chunk_rows = build_points(tenant, doc, text_content, source_hash=source_hash, source_version=version,
                                              fp=target, acl_hash=item.get("acl_hash"))
            self.qdrant.upsert(self.collection, [qm.PointStruct(id=p.point_id, vector=p.vector, payload=p.payload) for p in points])
            self._write_manifest(tenant, doc, item.get("source_uri"), version, source_hash, target, len(points), chunk_rows)
            done += 1
        return done

    def _write_manifest(self, tenant: str, doc: str, uri: str | None, version: str, source_hash: str, fp: Fingerprint,
                        n_chunks: int, chunk_rows: list) -> None:
        row = {
            "tenant_id": tenant, "document_id": doc, "source_uri": uri, "source_version": version, "source_hash": source_hash,
            "parsed_hash": sha256_hex("parsed:" + source_hash), "parser_version": fp.parser_version,
            "chunking_version": fp.chunking_version, "chunk_size": fp.chunk_size, "chunk_overlap": fp.chunk_overlap,
            "embedding_model": fp.embedding_model, "embedding_dim": fp.embedding_dim, "preprocessing": fp.preprocessing,
            "expected_chunk_count": n_chunks, "indexed_chunk_count": n_chunks, "indexed_version": version,
            "processing_status": "success", "acl_hash": None,
        }
        cols = ", ".join(MANIFEST_COLS)
        vals = ", ".join(f":{c}" for c in MANIFEST_COLS)
        sets = ", ".join(f"{c} = :{c}" for c in MANIFEST_COLS if c not in ("tenant_id", "document_id"))
        with self.engine.begin() as c:
            # keep the previously recorded ACL hash: this toy pipeline does not compute ACLs
            existing = c.execute(text(f"SELECT acl_hash FROM {self.q}rag_document_manifest WHERE tenant_id=:t AND document_id=:d"),
                                 {"t": tenant, "d": doc}).first()
            row["acl_hash"] = existing[0] if existing else None
            # UPDATE, then INSERT when nothing was there. Not "INSERT ... ON CONFLICT": that needs a unique key on
            # (tenant_id, document_id), and many real manifest tables have none (the practice lab's duplicate-row exercise removes it).
            updated = c.execute(text(f"UPDATE {self.q}rag_document_manifest SET {sets} WHERE tenant_id = :tenant_id AND document_id = :document_id"),
                                row).rowcount
            if not updated:
                c.execute(text(f"INSERT INTO {self.q}rag_document_manifest ({cols}) VALUES ({vals})"), row)
            c.execute(text(f"DELETE FROM {self.q}rag_chunk_manifest WHERE tenant_id=:t AND document_id=:d"), {"t": tenant, "d": doc})
            if chunk_rows:
                c.execute(text(f"INSERT INTO {self.q}rag_chunk_manifest (tenant_id, document_id, chunk_id, chunk_index, chunk_hash) "
                               "VALUES (:t, :d, :c, :i, :h)"),
                          [{"t": r.tenant_id, "d": r.document_id, "c": r.chunk_id, "i": r.chunk_index, "h": r.chunk_hash} for r in chunk_rows])

    # ------------------------------------------------------------------ phase: cleanup (delete exactly what was listed)
    def cleanup(self, payload: dict[str, Any]) -> int:
        from qdrant_client import models as qm

        removed = 0
        for group in payload["cleanup"]:
            ids = list(group["point_ids"])
            for i in range(0, len(ids), 500):
                self.qdrant.delete(group.get("collection") or self.collection,
                                   points_selector=qm.PointIdsList(points=ids[i : i + 500]))
            removed += len(ids)
            tenant, doc = group["tenant_id"], group["document_id"]
            if not self._source_exists(tenant, doc):  # a deleted document: retire its manifest rows too
                with self.engine.begin() as c:
                    c.execute(text(f"DELETE FROM {self.q}rag_chunk_manifest WHERE tenant_id=:t AND document_id=:d"), {"t": tenant, "d": doc})
                    c.execute(text(f"DELETE FROM {self.q}rag_document_manifest WHERE tenant_id=:t AND document_id=:d"), {"t": tenant, "d": doc})
        return removed

    def _source_exists(self, tenant: str, doc: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=f"{self.prefix}{tenant}/{doc}")
            return True
        except Exception:
            return False

    def handle(self, payload: dict[str, Any]) -> int:
        return self.reindex(payload) if payload["phase"] == "reindex" else self.cleanup(payload)


class BillsWorker:
    """The same webhook contract for a different pipeline: the practice lab's "mini bills" (Lab B).

    Your pipeline will not look like the first worker above, and this one shows what changes: the file is found from the plan's
    ``source_uri`` (not rebuilt from tenant and document), the vectors only carry the bill as ``source_id`` and go into their own
    collection, and "indexed" is a true/false column in the pipeline's own table. The rules do not change: add or replace with
    deterministic point ids in the reindex phase, delete only the exact ids you are given in the cleanup phase.
    """

    MODEL, DIM, PIECE = "demo-embed-v2", 16, 40

    def __init__(self, s3: Any, qdrant: Any, manifest_engine: Engine, collection: str = "bill_chunks",
                 table: str = "bill_documents", schema: str | None = None) -> None:
        self.s3, self.qdrant, self.engine, self.collection = s3, qdrant, manifest_engine, collection
        self.table = f"{schema}.{table}" if schema else table

    def reindex(self, payload: dict[str, Any]) -> int:
        from qdrant_client import models as qm

        pg = self.engine.dialect.name == "postgresql"
        done = 0
        for item in payload["items"]:
            doc, uri = item["document_id"], item.get("source_uri") or ""
            where = urlparse(uri)
            if where.scheme != "s3" or not where.netloc:
                raise ValueError(f"document {doc}: the plan has no s3:// source_uri to read the file from (got {uri!r})")
            body = self.s3.get_object(Bucket=where.netloc, Key=where.path.lstrip("/"))["Body"].read()
            content = body.decode("utf-8", errors="replace")  # <- your parser goes here
            pieces = [content[i : i + self.PIECE] for i in range(0, len(content), self.PIECE)] or [""]
            base = int(doc) if doc.isdigit() else int(sha256_hex(doc)[:8], 16)
            points = []
            for i, piece in enumerate(pieces):
                snippet = f"Section {i + 1} of bill {doc}. {piece}"
                points.append(qm.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"bills/{doc}/{i}")),  # deterministic: a retry replaces, never duplicates
                    vector=embed(snippet, self.DIM, self.MODEL),
                    payload={"source_db": "lab", "source_table": "bills", "source_id": doc, "chunk_id": base * 100 + i, "jurisdiction": "NM",
                             "text": snippet, "span": f"{i}:{i}", "modality": "text", "year": 2026, "bill_number": f"B{doc[-4:]}",
                             "chamber": "S", "session_id": 2251}))
            self.qdrant.upsert(self.collection, points)
            now = datetime.now(timezone.utc)
            with self.engine.begin() as c:  # the pipeline's own bookkeeping: mark it indexed and clear the old error
                c.execute(text(f"UPDATE {self.table} SET is_indexed = :idx, indexed_at = :now, last_error = NULL, updated_at = :now "
                               "WHERE external_doc_id = :d"),
                          {"idx": True if pg else "True", "now": now if pg else now.isoformat(), "d": doc})
            done += 1
        return done

    def cleanup(self, payload: dict[str, Any]) -> int:
        from qdrant_client import models as qm

        removed = 0
        for group in payload["cleanup"]:
            ids = list(group["point_ids"])
            for i in range(0, len(ids), 500):
                self.qdrant.delete(group.get("collection") or self.collection, points_selector=qm.PointIdsList(points=ids[i : i + 500]))
            removed += len(ids)
        return removed

    def handle(self, payload: dict[str, Any]) -> int:
        return self.reindex(payload) if payload["phase"] == "reindex" else self.cleanup(payload)


def create_app(worker: Worker | BillsWorker, secret: str, background: bool = True) -> FastAPI:
    app = FastAPI(title="RAG Integrity reference worker")

    def run(payload: dict[str, Any]) -> None:
        worker.handle(payload)
        callback = payload.get("callback_url")
        if callback:  # tell the platform it can verify now
            body = json.dumps({"plan_id": payload["plan_id"], "phase": payload["phase"], "done": True}).encode()
            ts = str(int(time.time()))
            httpx.post(callback, content=body, timeout=30,
                       headers={"X-Ragi-Timestamp": ts, "X-Ragi-Signature": sign(secret, ts, body)})

    @app.post("/ragi-webhook", status_code=202)
    async def webhook(request: Request, tasks: BackgroundTasks) -> dict[str, Any]:
        raw = await request.body()
        if not verify(secret, request.headers.get("x-ragi-timestamp"), request.headers.get("x-ragi-signature"), raw):
            raise HTTPException(401, "bad signature")
        payload = json.loads(raw)
        if background:
            tasks.add_task(run, payload)
            return {"accepted": True, "queued": True}
        return {"accepted": True, "processed": worker.handle(payload)}

    return app


def app_from_env() -> FastAPI:  # pragma: no cover - wiring for docker-compose
    import boto3
    from qdrant_client import QdrantClient
    from sqlalchemy import create_engine

    from ragintegrity.config import normalize_db_url

    worker = Worker(
        s3=boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL"), region_name=os.environ.get("AWS_REGION", "us-east-1")),
        bucket=os.environ["S3_BUCKET"], qdrant=QdrantClient(url=os.environ["QDRANT_URL"]),
        manifest_engine=create_engine(normalize_db_url(os.environ["MANIFEST_DATABASE_URL"])),
        collection=os.environ.get("QDRANT_COLLECTION", "kb_main"), schema=os.environ.get("MANIFEST_SCHEMA", "public"),
    )
    return create_app(worker, os.environ["RAGI_REPAIR_WEBHOOK_SECRET"])


def app_bills_from_env() -> FastAPI:  # pragma: no cover - wiring for docker-compose.lab.yml (Lab B)
    import boto3
    from qdrant_client import QdrantClient
    from sqlalchemy import create_engine

    from ragintegrity.config import normalize_db_url

    worker = BillsWorker(
        s3=boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL"), region_name=os.environ.get("AWS_REGION", "us-east-1")),
        qdrant=QdrantClient(url=os.environ["QDRANT_URL"], check_compatibility=False),
        manifest_engine=create_engine(normalize_db_url(os.environ["MANIFEST_DATABASE_URL"])),
        collection=os.environ.get("QDRANT_COLLECTION", "bill_chunks"), table=os.environ.get("MANIFEST_TABLE", "bill_documents"),
        schema=os.environ.get("MANIFEST_SCHEMA", "public"),
    )
    return create_app(worker, os.environ["RAGI_REPAIR_WEBHOOK_SECRET"])


if os.environ.get("RAGI_WORKER_AUTOSTART"):  # pragma: no cover
    app = app_bills_from_env() if os.environ.get("RAGI_WORKER_KIND") == "bills" else app_from_env()
