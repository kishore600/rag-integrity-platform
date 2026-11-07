"""Mapping between a vector-store payload and our canonical ``IndexedChunk``."""

from __future__ import annotations

from typing import Any

from ..models import Fingerprint, IndexedChunk

CANONICAL_FIELDS = (
    "tenant_id", "document_id", "chunk_id", "chunk_index", "chunk_hash", "source_hash", "source_version",
    "parser_version", "chunking_version", "chunk_size", "chunk_overlap", "embedding_model",
    "embedding_model_version", "embedding_dim", "preprocessing", "acl_hash",
)
DEFAULT_PAYLOAD_MAP = {f: f for f in CANONICAL_FIELDS}


def build_payload_map(overrides: dict[str, str] | None) -> dict[str, str]:
    pmap = dict(DEFAULT_PAYLOAD_MAP)
    for k, v in (overrides or {}).items():
        if k not in pmap:
            raise ValueError(f"Unknown payload field {k!r}; valid fields: {', '.join(CANONICAL_FIELDS)}")
        pmap[k] = v
    return pmap


def _dig(payload: dict[str, Any], path: str) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _s(v: Any) -> str | None:
    return None if v is None or v == "" else str(v)


def _i(v: Any) -> int | None:
    try:
        return None if v is None or v == "" else int(v)
    except (TypeError, ValueError):
        return None


def vector_is_usable(vector: Any, vector_name: str | None = None) -> bool:
    if isinstance(vector, dict):
        vector = vector.get(vector_name) if vector_name else next(iter(vector.values()), None)
    if not vector:
        return False
    try:
        return any(abs(float(x)) > 0 for x in vector)
    except (TypeError, ValueError):  # sparse / multi-vector shapes we don't introspect
        return True


def payload_to_chunk(
    collection: str,
    point_id: Any,
    payload: dict[str, Any] | None,
    pmap: dict[str, str],
    *,
    vector: Any = None,
    check_vector: bool = False,
    vector_name: str | None = None,
) -> IndexedChunk:
    payload = payload or {}
    raw = {name: _dig(payload, path) for name, path in pmap.items()}
    present = frozenset(name for name, v in raw.items() if v is not None and v != "")
    fp = Fingerprint(
        parser_version=_s(raw["parser_version"]),
        chunking_version=_s(raw["chunking_version"]),
        chunk_size=_i(raw["chunk_size"]),
        chunk_overlap=_i(raw["chunk_overlap"]),
        embedding_model=_s(raw["embedding_model"]),
        embedding_model_version=_s(raw["embedding_model_version"]),
        embedding_dim=_i(raw["embedding_dim"]),
        preprocessing=_s(raw["preprocessing"]),
    )
    return IndexedChunk(
        collection=collection,
        point_id=str(point_id),
        tenant_id=_s(raw["tenant_id"]),
        document_id=_s(raw["document_id"]),
        chunk_id=_s(raw["chunk_id"]),
        chunk_index=_i(raw["chunk_index"]),
        chunk_hash=_s(raw["chunk_hash"]),
        source_hash=_s(raw["source_hash"]),
        source_version=_s(raw["source_version"]),
        fingerprint=fp,
        acl_hash=_s(raw["acl_hash"]),
        vector_checked=check_vector,
        vector_ok=vector_is_usable(vector, vector_name) if check_vector else True,
        present_fields=present,
    )
