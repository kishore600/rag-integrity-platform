"""Connector contracts. Connectors are *read-only* views over the customer's infrastructure."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from ..models import (
    ChunkRow,
    ConnectionStatus,
    IndexedChunk,
    ManifestRow,
    Scope,
    SourceDoc,
)


class SourceConnector(Protocol):
    def inventory(self, scope: Scope | None = None) -> Iterator[SourceDoc]: ...

    def health(self) -> ConnectionStatus: ...


class ManifestConnector(Protocol):
    has_chunk_manifest: bool

    def documents(self, scope: Scope | None = None) -> Iterator[ManifestRow]: ...

    def chunks(self, scope: Scope | None = None) -> Iterator[ChunkRow]: ...

    def health(self) -> ConnectionStatus: ...


class IndexConnector(Protocol):
    def collections(self) -> list[str]: ...

    def vector_sizes(self) -> dict[str, int | None]: ...

    def scan(self, scope: Scope | None = None, with_vectors: bool = False) -> Iterator[IndexedChunk]: ...

    def probe(
        self, collection: str, point_id: str, tenant_id: str | None, top_k: int
    ) -> list[tuple[str, float, str | None]] | None:
        """Query the index with the stored vector of ``point_id``.

        Returns ranked ``(point_id, score, document_id)`` hits, or None if the point is gone."""
        ...

    def health(self) -> ConnectionStatus: ...


class ConnectorError(RuntimeError):
    pass
