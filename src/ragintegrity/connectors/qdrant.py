"""Read-only Qdrant vector inventory.

Uses ``scroll`` (payload only; vectors only when asked) so memory stays flat regardless of
collection size, and ``retrieve`` + ``query_points`` for retrieval probes. Nothing is ever written
or deleted by this connector.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from ..config import Settings
from ..models import ConnectionStatus, IndexedChunk, Scope
from .base import ConnectorError
from .payload import build_payload_map, payload_to_chunk

FILTER_DOCS_LIMIT = 1000


def _coerce_id(point_id: str) -> Any:
    return int(point_id) if point_id.isdigit() else point_id


class QdrantIndex:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.s = settings
        self.pmap = build_payload_map(settings.payload_map)
        self.vector_name = settings.qdrant_vector_name
        if client is None:
            if not settings.qdrant_url:
                raise ConnectorError("RAGI_QDRANT_URL is not set")
            from qdrant_client import QdrantClient

            client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=60)
        self.client = client
        self._names = settings.collections

    # --------------------------------------------------------------------------------- meta
    def collections(self) -> list[str]:
        if self._names:
            return list(self._names)
        return sorted(c.name for c in self.client.get_collections().collections)

    def vector_sizes(self) -> dict[str, int | None]:
        sizes: dict[str, int | None] = {}
        for name in self.collections():
            try:
                vectors = self.client.get_collection(name).config.params.vectors
                if isinstance(vectors, dict):
                    v = vectors.get(self.vector_name) if self.vector_name else next(iter(vectors.values()), None)
                else:
                    v = vectors
                sizes[name] = getattr(v, "size", None)
            except Exception:
                sizes[name] = None
        return sizes

    # --------------------------------------------------------------------------------- scan
    def _top_level(self, path: str) -> str:
        return path.split(".")[0]

    def _filter(self, scope: Scope | None) -> Any:
        if scope is None or scope.is_full:
            return None
        from qdrant_client import models as qm

        must: list[Any] = []
        if scope.tenant:
            must.append(qm.FieldCondition(key=self.pmap["tenant_id"], match=qm.MatchValue(value=scope.tenant)))
        if scope.keys is not None and len(scope.keys) <= FILTER_DOCS_LIMIT:
            docs = sorted({d for _, d in scope.keys})
            must.append(qm.FieldCondition(key=self.pmap["document_id"], match=qm.MatchAny(any=docs)))
        return qm.Filter(must=must) if must else None

    def scan(self, scope: Scope | None = None, with_vectors: bool = False) -> Iterator[IndexedChunk]:
        include = sorted({self._top_level(p) for p in self.pmap.values()})
        flt = self._filter(scope)
        vectors_arg: Any = [self.vector_name] if (with_vectors and self.vector_name) else with_vectors
        for coll in self.collections():
            offset = None
            while True:
                points, offset = self.client.scroll(
                    collection_name=coll, scroll_filter=flt, limit=self.s.qdrant_page_size, offset=offset,
                    with_payload=include, with_vectors=vectors_arg,
                )
                for p in points:
                    chunk = payload_to_chunk(
                        coll, p.id, p.payload, self.pmap, vector=getattr(p, "vector", None),
                        check_vector=with_vectors, vector_name=self.vector_name,
                    )
                    if scope is not None and not scope.is_full and chunk.document_id:
                        key = (chunk.tenant_id or self.s.default_tenant, chunk.document_id)
                        if not scope.matches(key):
                            continue
                    yield chunk
                if offset is None:
                    break

    # --------------------------------------------------------------------------------- probe
    def probe(
        self, collection: str, point_id: str, tenant_id: str | None, top_k: int
    ) -> list[tuple[str, float, str | None]] | None:
        recs = self.client.retrieve(collection_name=collection, ids=[_coerce_id(point_id)], with_vectors=True,
                                    with_payload=False)
        if not recs or recs[0].vector is None:
            return None
        vec = recs[0].vector
        if isinstance(vec, dict):
            vec = vec.get(self.vector_name) if self.vector_name else next(iter(vec.values()), None)
        if not vec:
            return None
        flt = None
        if tenant_id is not None:
            from qdrant_client import models as qm

            flt = qm.Filter(must=[qm.FieldCondition(key=self.pmap["tenant_id"], match=qm.MatchValue(value=tenant_id))])
        res = self.client.query_points(
            collection_name=collection, query=vec, using=self.vector_name, limit=top_k, query_filter=flt,
            with_payload=[self._top_level(self.pmap["document_id"])],
        )
        out: list[tuple[str, float, str | None]] = []
        for p in res.points:
            doc = (p.payload or {}).get(self.pmap["document_id"]) if "." not in self.pmap["document_id"] else None
            out.append((str(p.id), float(p.score), doc))
        return out

    # --------------------------------------------------------------------------------- health
    def health(self) -> ConnectionStatus:
        t0 = time.perf_counter()
        try:
            existing = {c.name for c in self.client.get_collections().collections}
            wanted = self.collections()
            missing = [c for c in wanted if c not in existing]
            counts = {c: self.client.count(collection_name=c, exact=False).count for c in wanted if c in existing}
            ms = (time.perf_counter() - t0) * 1000
            if missing:
                return ConnectionStatus("Vector index (Qdrant)", "qdrant", False,
                                        f"collection(s) not found: {', '.join(missing)}", ms, {"counts": counts})
            return ConnectionStatus("Vector index (Qdrant)", "qdrant", True,
                                    f"{len(wanted)} collection(s), ~{sum(counts.values())} points", ms, {"counts": counts})
        except Exception as exc:
            return ConnectionStatus("Vector index (Qdrant)", "qdrant", False, f"{type(exc).__name__}: {str(exc)[:200]}")
