"""Core data model shared by connectors, the reconciliation engine and the ledger.

The platform never stores document *contents*. Everything here is identifiers,
hashes, versions and counts.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any

DocKey = tuple[str, str]  # (tenant_id, document_id)


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def severity_at_least(sev: str, minimum: str) -> bool:
    return SEVERITY_RANK[sev] >= SEVERITY_RANK[minimum]


def max_severity(values: list[str]) -> str | None:
    return max(values, key=lambda s: SEVERITY_RANK[s]) if values else None


class IssueType(str, Enum):
    MISSING_EMBEDDING = "missing_embedding"  # source doc has no vectors at all
    PARTIAL_INDEX = "partial_index"  # only some expected chunks are indexed
    STALE_EMBEDDING = "stale_embedding"  # source changed, vectors are from an older version
    SUPERSEDED_ACTIVE = "superseded_active"  # old-generation vectors still active next to new ones
    ORPHAN_VECTOR = "orphan_vector"  # vectors whose source document no longer exists
    DUPLICATE_CHUNK = "duplicate_chunk"  # same chunk indexed more than once
    METADATA_INCONSISTENT = "metadata_inconsistent"  # manifest/payload/ACL/version disagree
    PIPELINE_DRIFT = "pipeline_drift"  # indexed with a different parser/chunker/embedding config
    EMPTY_EMBEDDING = "empty_embedding"  # point exists but its vector is missing or all zeros
    TENANT_MISMATCH = "tenant_mismatch"  # vectors tagged with the wrong tenant
    MANIFEST_ORPHAN = "manifest_orphan"  # manifest row for a document that no longer exists


class Action(str, Enum):
    REINDEX_FULL = "reindex_full"
    REINDEX_CHUNKS = "reindex_chunks"
    CLEANUP_VECTORS = "cleanup_vectors"
    FIX_METADATA = "fix_metadata"
    INVESTIGATE = "investigate"


# Issue types whose repair is *removal* of vectors and must wait until replacements are verified.
CLEANUP_TYPES = {
    IssueType.SUPERSEDED_ACTIVE.value,
    IssueType.DUPLICATE_CHUNK.value,
    IssueType.ORPHAN_VECTOR.value,
    IssueType.TENANT_MISMATCH.value,
}


@dataclass(slots=True)
class Fingerprint:
    """Everything that determines how a document was turned into vectors."""

    parser_version: str | None = None
    chunking_version: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    embedding_model: str | None = None
    embedding_model_version: str | None = None
    embedding_dim: int | None = None
    preprocessing: str | None = None

    def to_dict(self, drop_none: bool = True) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None} if drop_none else d

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Fingerprint:
        d = d or {}
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def is_empty(self) -> bool:
        return all(v is None for v in asdict(self).values())

    def key(self) -> str:
        return "|".join(f"{k}={v}" for k, v in sorted(self.to_dict().items()))

    def fill_from(self, other: Fingerprint | None) -> Fingerprint:
        """Return a copy where unknown fields are taken from ``other``."""
        if other is None:
            return self
        merged = {k: (v if v is not None else getattr(other, k)) for k, v in asdict(self).items()}
        return Fingerprint(**merged)

    def conflicts_with(self, target: Fingerprint) -> dict[str, dict[str, Any]]:
        """Fields where both sides know a value and the values differ."""
        out: dict[str, dict[str, Any]] = {}
        for k, tv in asdict(target).items():
            mine = getattr(self, k)
            if tv is not None and mine is not None and str(mine) != str(tv):
                out[k] = {"indexed": mine, "target": tv}
        return out


# Fields of a fingerprint that change the embedding space, so a mismatch is high severity.
EMBEDDING_FIELDS = {"embedding_model", "embedding_model_version", "embedding_dim"}


@dataclass(slots=True)
class SourceDoc:
    tenant_id: str
    document_id: str
    source_uri: str
    source_version: str | None = None
    source_hash: str | None = None  # sha256 hex (or etag when hash_reliable is False)
    hash_reliable: bool = True
    size_bytes: int = 0
    last_modified: str | None = None  # ISO-8601 UTC

    @property
    def key(self) -> DocKey:
        return (self.tenant_id, self.document_id)


@dataclass(slots=True)
class ManifestRow:
    tenant_id: str
    document_id: str
    source_uri: str | None = None
    source_version: str | None = None
    source_hash: str | None = None
    parsed_hash: str | None = None
    fingerprint: Fingerprint = field(default_factory=Fingerprint)
    expected_chunk_count: int | None = None
    indexed_chunk_count: int | None = None
    indexed_version: str | None = None
    processing_status: str | None = None
    last_verified_at: str | None = None
    updated_at: str | None = None
    acl_hash: str | None = None

    @property
    def key(self) -> DocKey:
        return (self.tenant_id, self.document_id)


@dataclass(slots=True)
class ChunkRow:
    tenant_id: str
    document_id: str
    chunk_id: str
    chunk_index: int | None = None
    chunk_hash: str | None = None


@dataclass(slots=True)
class IndexedChunk:
    """One point in the vector index (payload only; vectors are inspected, not copied)."""

    collection: str
    point_id: str
    tenant_id: str | None
    document_id: str | None
    chunk_id: str | None = None
    chunk_index: int | None = None
    chunk_hash: str | None = None
    source_hash: str | None = None
    source_version: str | None = None
    fingerprint: Fingerprint = field(default_factory=Fingerprint)
    acl_hash: str | None = None
    chunk_total: int | None = None  # how many chunks the pipeline cut the document into, when each vector says so
    vector_checked: bool = False
    vector_ok: bool = True  # False = vector missing / empty / all zeros (only if vector_checked)
    present_fields: frozenset[str] = frozenset()  # payload fields that carried a value


@dataclass(slots=True)
class Scope:
    """Restrict an audit to some tenants and/or specific documents."""

    tenant: str | None = None
    keys: frozenset[DocKey] | None = None

    @property
    def is_full(self) -> bool:
        return self.tenant is None and self.keys is None

    def matches(self, key: DocKey) -> bool:
        if self.tenant is not None and key[0] != self.tenant:
            return False
        return self.keys is None or key in self.keys

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.tenant:
            out["tenant"] = self.tenant
        if self.keys is not None:
            out["documents"] = len(self.keys)
        return out


@dataclass(slots=True)
class ConnectionStatus:
    name: str
    kind: str
    ok: bool
    detail: str = ""
    latency_ms: float | None = None
    info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Finding:
    type: IssueType
    severity: Severity
    tenant_id: str
    document_id: str
    collection: str | None
    title: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    action: Action = Action.INVESTIGATE

    @property
    def issue_id(self) -> str:
        raw = f"{self.type.value}|{self.tenant_id}|{self.document_id}|{self.collection or ''}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @property
    def key(self) -> DocKey:
        return (self.tenant_id, self.document_id)


@dataclass(slots=True)
class DocSummary:
    tenant_id: str
    document_id: str
    status: str  # healthy | degraded | broken | pending | orphaned
    issue_types: list[str] = field(default_factory=list)
    worst_severity: str | None = None
    source_present: bool = False
    manifest_present: bool = False
    index_present: bool = False
    source_uri: str | None = None
    source_hash: str | None = None
    source_version: str | None = None
    size_bytes: int = 0
    fingerprint: dict[str, Any] = field(default_factory=dict)
    expected_chunks: int | None = None
    indexed_chunks: int = 0
    manifest_status: str | None = None
    manifest_updated_at: str | None = None
    collections: list[str] = field(default_factory=list)
    indexed_version: str | None = None  # the source version the index actually holds (manifest claim as a fallback)

    @property
    def key(self) -> DocKey:
        return (self.tenant_id, self.document_id)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()
