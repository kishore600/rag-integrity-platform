"""Connector contracts. Connectors are *read-only* views over the customer's infrastructure."""

from __future__ import annotations

import time
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


class AuditTimeout(RuntimeError):
    """The audit used up its time budget. Raised with a message that says where, so a run never just disappears."""


def check_deadline(deadline: float | None, what: str, detail: str = "") -> None:
    """Stop with a clear message once the time budget (a ``time.monotonic()`` value) is spent."""
    if deadline is not None and time.monotonic() > deadline:
        raise AuditTimeout(
            f"The audit ran out of time while reading {what}{detail}. This corpus is too large to audit in one go here: "
            "audit one tenant at a time, narrow the source (for example the S3 key prefix), or run `ragi audit` on a machine "
            "without a request time limit.")


class UpstreamError(ConnectorError):
    """A connection to the user's own infrastructure (S3, their database, Qdrant) failed; the message is safe to show."""


class SetupIncomplete(ConnectorError):
    """A required connection has not been configured yet (a 409 for the user, not a server fault)."""
