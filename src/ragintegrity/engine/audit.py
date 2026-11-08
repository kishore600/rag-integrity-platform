"""Glue: pull the three inventories through read-only connectors, then reconcile."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

from ..connectors.base import (  # noqa: F401  (AuditTimeout is re-exported: the API maps it to a 504)
    AuditTimeout,
    IndexConnector,
    ManifestConnector,
    SourceConnector,
    check_deadline,
)
from ..models import ChunkRow, DocKey, Fingerprint, ManifestRow, Scope, SourceDoc
from .index_state import AggContext, IndexAggregator
from .reconcile import (
    ReconcileConfig,
    ReconcileResult,
    derive_required_fields,
    reconcile,
    refresh_after_escalation,
)
from .retrieval import probe_findings

T = TypeVar("T")


@dataclass
class AuditOptions:
    target: Fingerprint | None = None
    default_tenant: str = "default"
    required_fields: list[str] = field(default_factory=list)
    known_tenants: set[str] = field(default_factory=set)  # tenants seen in earlier runs (keeps scoped runs consistent)
    grace_minutes: int = 0
    check_vectors: bool = False
    source_only: bool = False  # the source inventory defines the corpus: ignore manifest rows / vectors for anything else
    lookup_from_manifest: bool = False  # find source files from the manifest's source URIs instead of listing the bucket
    probe: bool = True
    probe_max: int = 25
    probe_top_k: int = 10
    now: datetime | None = None
    deadline: float | None = None  # time.monotonic() value after which the audit stops
    progress: Callable[..., None] | None = None  # progress(phase, elapsed_seconds=..., **counts): where the audit is right now


def _guard(items: Iterable[T], deadline: float | None, what: str) -> Iterator[T]:
    """Pass items through, but give up with a clear message once the time budget is spent."""
    for i, item in enumerate(items):
        if i % 200 == 0:
            check_deadline(deadline, what, f" (after {i:,} items)")
        yield item


def _note(opts: AuditOptions, t0: float, phase: str, **info: Any) -> None:
    """Report progress. Best effort: it must never break an audit."""
    if opts.progress is None:
        return
    try:
        opts.progress(phase, elapsed_seconds=round(time.monotonic() - t0, 1), **info)
    except Exception:  # a failed progress write is not worth losing the audit for
        pass


@dataclass
class Collected:
    source: dict[DocKey, SourceDoc]
    manifest: dict[DocKey, ManifestRow]
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None
    agg: IndexAggregator
    required: list[str]
    started: float = 0.0  # time.monotonic() when collecting began (for progress notes)


def collect(
    source: SourceConnector, manifest: ManifestConnector, index: IndexConnector, opts: AuditOptions,
    scope: Scope | None = None,
) -> Collected:
    dl = opts.deadline
    t0 = time.monotonic()
    for connector in (source, manifest, index):  # connectors that page through data check the budget between pages
        if hasattr(connector, "deadline"):
            connector.deadline = dl
    lookup = getattr(source, "lookup", None)
    if opts.lookup_from_manifest and lookup is not None and (scope is None or scope.keys is None):
        # large buckets: read exactly the files the manifest names (one HEAD each) instead of listing everything
        _note(opts, t0, "reading the processing manifest")
        man = {r.key: r for r in _guard(manifest.documents(scope), dl, "the processing manifest")}
        _note(opts, t0, "looking up the files the manifest names (S3)", manifest_rows=len(man))
        src = {d.key: d for d in _guard(lookup(r.source_uri for r in man.values()), dl, "the source bucket")}
    else:
        _note(opts, t0, "listing the source documents (S3)")
        src = {d.key: d for d in _guard(source.inventory(scope), dl, "the source bucket")}  # first: the index scan classifies against it
        _note(opts, t0, "reading the processing manifest", source_documents=len(src))
        man = {r.key: r for r in _guard(manifest.documents(scope), dl, "the processing manifest")}
    scan_scope, scan_nothing = scope, False
    if opts.source_only:
        man = {k: r for k, r in man.items() if k in src}
        if scope is None or scope.keys is None:
            if src:  # read only the points of known documents (server-side filter) instead of the whole collection
                scan_scope = Scope(tenant=scope.tenant if scope else None, keys=frozenset(src))
            else:
                scan_nothing = True
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None = None
    if manifest.has_chunk_manifest:
        chunk_rows = defaultdict(dict)
        for c in _guard(manifest.chunks(scope), dl, "the chunk manifest"):
            if opts.source_only and (c.tenant_id, c.document_id) not in src:
                continue
            chunk_rows[(c.tenant_id, c.document_id)][c.chunk_id] = c
    required = derive_required_fields(opts.required_fields, {k[0] for k in src} | opts.known_tenants)
    ctx = AggContext(source=src, manifest=man, target=opts.target, default_tenant=opts.default_tenant,
                     required_fields=required)
    agg = IndexAggregator(ctx)
    if not scan_nothing:
        _note(opts, t0, "reading the vector index (Qdrant)", source_documents=len(src), manifest_rows=len(man))
        agg.add_all(_guard(index.scan(scan_scope, with_vectors=opts.check_vectors), dl, "the vector index"))
    return Collected(src, man, chunk_rows, agg, required, started=t0)


def _config(index: IndexConnector, opts: AuditOptions, required: list[str]) -> ReconcileConfig:
    return ReconcileConfig(target=opts.target, grace_minutes=opts.grace_minutes,
                           now=opts.now or datetime.now(timezone.utc), vector_sizes=index.vector_sizes(),
                           required_fields=required)


def run_reconciliation(
    source: SourceConnector,
    manifest: ManifestConnector,
    index: IndexConnector,
    opts: AuditOptions,
    scope: Scope | None = None,
) -> ReconcileResult:
    c = collect(source, manifest, index, opts, scope)
    _note(opts, c.started, "comparing the three lists", source_documents=len(c.source), manifest_rows=len(c.manifest))
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, opts, c.required), scope)
    result.stats["required_payload_fields"] = c.required
    if opts.source_only:
        result.stats["source_documents_only"] = True
    if opts.probe and result.findings:
        result.stats["retrieval_probes"] = probe_findings(
            index, result.findings, top_k=opts.probe_top_k, max_probes=opts.probe_max)
        refresh_after_escalation(result)  # probes can escalate severities
    return result


def inspect_document(
    source: SourceConnector, manifest: ManifestConnector, index: IndexConnector, opts: AuditOptions,
    tenant: str, document_id: str,
) -> dict[str, Any]:
    """A live, three-way view of one document: what the source, the manifest and the index each say."""
    key = (tenant, document_id)
    scope = Scope(keys=frozenset({key}))
    c = collect(source, manifest, index, opts, scope)
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, opts, c.required), scope)
    s, m, st = c.source.get(key), c.manifest.get(key), c.agg.states.get(key)

    chunks: list[dict[str, Any]] = []
    if st:
        for (coll, ck, cls), slot in st.slots.items():
            chunks.append({"collection": coll, "chunk_id": ck, "chunk_index": slot.index, "class": cls,
                           "copies": len(slot.ids), "point_ids": slot.ids[:3]})
        chunks.sort(key=lambda r: (r["class"], r["chunk_index"] if r["chunk_index"] is not None else -1, r["chunk_id"]))
    expected = sorted((c.chunk_rows or {}).get(key, {}).values(), key=lambda r: (r.chunk_index is None, r.chunk_index))
    return {
        "tenant_id": tenant, "document_id": document_id,
        "source": asdict(s) if s else None,
        "manifest": ({**{k: v for k, v in asdict(m).items() if k != "fingerprint"}, "fingerprint": m.fingerprint.to_dict()}
                     if m else None),
        "expected_chunks": [asdict(r) for r in expected[:500]],
        "index": {
            "points": st.point_count if st else 0,
            "by_class": dict(st.classes) if st else {},
            "collections": sorted(st.collections) if st else [],
            "fingerprints": [st.fp_objs[k].to_dict() | {"points": n} for k, n in st.fp_all.items()] if st else [],
            "chunks": chunks[:500], "chunks_truncated": len(chunks) > 500,
        },
        "findings": [{"id": f.issue_id, "type": f.type.value, "severity": f.severity.value, "title": f.title,
                      "detail": f.detail, "action": f.action.value} for f in result.findings],
        "status": result.summaries[0].status if result.summaries else "unknown",
    }
