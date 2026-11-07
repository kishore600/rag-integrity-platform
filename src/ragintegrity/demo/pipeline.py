"""A deterministic toy ingestion pipeline (parse -> chunk -> embed -> payload).

It exists so the demo world and the reference repair worker produce *consistent* chunk ids, hashes
and vectors. It is deliberately not a real parser or embedding model.
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass
from typing import Any

from ..models import ChunkRow, Fingerprint, sha256_hex

WORDS = (
    "policy escalation customer invoice renewal compliance retention security incident runbook rollback "
    "deployment latency quota billing refund audit access onboarding vendor contract clause liability "
    "encryption backup recovery pricing tier feature release roadmap support ticket severity response "
    "handbook leave benefits expense travel approval budget forecast procurement warranty shipping returns "
    "privacy consent identity token rotation certificate firewall network storage archive deletion "
).split()


def make_text(doc_id: str, version: int) -> str:
    rng = random.Random(f"{doc_id}:{version}")
    target = rng.randint(1500, 3400)
    words: list[str] = []
    length = 0
    while length < target:
        w = rng.choice(WORDS)
        words.append(w)
        length += len(w) + 1
    return " ".join(words)


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    step = max(1, size - max(0, overlap))
    out: list[str] = []
    for i in range(0, len(text), step):
        piece = text[i : i + size]
        if piece.strip():
            out.append(piece)
        if i + size >= len(text):
            break
    return out


def embed(text: str, dim: int, model: str) -> list[float]:
    rng = random.Random(f"{model}:{sha256_hex(text)}")
    vec = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def make_chunk_id(doc_id: str, chunking_version: str, index: int) -> str:
    return f"{doc_id}#{chunking_version}:{index}"


def make_point_id(tenant: str, doc_id: str, chunk_id: str, source_hash: str, model: str) -> str:
    """Deterministic, so a retried upsert overwrites instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant}/{doc_id}/{chunk_id}/{source_hash}/{model}"))


@dataclass
class BuiltPoint:
    point_id: str
    vector: list[float]
    payload: dict[str, Any]


def build_points(
    tenant: str,
    doc_id: str,
    text: str,
    *,
    source_hash: str,
    source_version: str,
    fp: Fingerprint,
    acl_hash: str | None = None,
) -> tuple[list[BuiltPoint], list[ChunkRow]]:
    assert fp.chunk_size and fp.chunking_version and fp.embedding_model and fp.embedding_dim
    points: list[BuiltPoint] = []
    rows: list[ChunkRow] = []
    for i, piece in enumerate(chunk_text(text, fp.chunk_size, fp.chunk_overlap or 0)):
        cid = make_chunk_id(doc_id, fp.chunking_version, i)
        chash = sha256_hex(piece)
        payload = {
            "tenant_id": tenant,
            "document_id": doc_id,
            "chunk_id": cid,
            "chunk_index": i,
            "chunk_hash": chash,
            "source_hash": source_hash,
            "source_version": source_version,
            "acl_hash": acl_hash,
            **fp.to_dict(),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        pid = make_point_id(tenant, doc_id, cid, source_hash, fp.embedding_model)
        points.append(BuiltPoint(pid, embed(piece, fp.embedding_dim, fp.embedding_model), payload))
        rows.append(ChunkRow(tenant, doc_id, cid, i, chash))
    return points, rows
