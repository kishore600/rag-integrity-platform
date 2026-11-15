"""Connector contracts. Connectors are *read-only* views over the customer's infrastructure."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
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


@dataclass
class ScanStats:
    """What a scan of the vector index went through. Shared between the engine (which counts points) and the connector
    (which counts pages and what it had to retry), so a result can say how reliable the scan was."""

    points: int = 0  # points read
    pages: int = 0  # requests that returned a page
    retries: int = 0  # requests repeated after a failure that can pass (timeout, rate limit, 5xx)
    recovered_errors: int = 0  # requests that failed at least once and then succeeded
    unrecoverable_errors: int = 0  # requests that gave up (retries used up, or an error that retrying cannot fix)
    rate_limited: int = 0  # of the retries, how many were because the server said "slow down" (HTTP 429)
    waited_seconds: float = 0.0  # time spent waiting between retries
    estimated_total: int | None = None  # the index's own (approximate) point count, for a percentage

    def snapshot(self) -> dict:
        return {"points_scanned": self.points, "pages": self.pages, "retries": self.retries,
                "recovered_errors": self.recovered_errors, "unrecoverable_errors": self.unrecoverable_errors,
                "rate_limited": self.rate_limited, "waited_seconds": round(self.waited_seconds, 1),
                "estimated_total": self.estimated_total}


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
