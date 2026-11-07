"""Glue: pull the three inventories through read-only connectors, then reconcile."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..connectors.base import IndexConnector, ManifestConnector, SourceConnector
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


@dataclass
class AuditOptions:
    target: Fingerprint | None = None
    default_tenant: str = "default"
    required_fields: list[str] = field(default_factory=list)
    known_tenants: set[str] = field(default_factory=set)  # tenants seen in earlier runs (keeps scoped runs consistent)
    grace_minutes: int = 0
    check_vectors: bool = False
    probe: bool = True
    probe_max: int = 25
    probe_top_k: int = 10
    now: datetime | None = None


@dataclass
class Collected:
    source: dict[DocKey, SourceDoc]
    manifest: dict[DocKey, ManifestRow]
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None
    agg: IndexAggregator
    required: list[str]


def collect(
    source: SourceConnector, manifest: ManifestConnector, index: IndexConnector, opts: AuditOptions,
    scope: Scope | None = None,
) -> Collected:
    src = {d.key: d for d in source.inventory(scope)}  # the source inventory first: the index scan classifies against it
    man = {r.key: r for r in manifest.documents(scope)}
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None = None
    if manifest.has_chunk_manifest:
        chunk_rows = defaultdict(dict)
        for c in manifest.chunks(scope):
            chunk_rows[(c.tenant_id, c.document_id)][c.chunk_id] = c
    required = derive_required_fields(opts.required_fields, {k[0] for k in src} | opts.known_tenants)
    ctx = AggContext(source=src, manifest=man, target=opts.target, default_tenant=opts.default_tenant,
                     required_fields=required)
    agg = IndexAggregator(ctx)
    agg.add_all(index.scan(scope, with_vectors=opts.check_vectors))
    return Collected(src, man, chunk_rows, agg, required)


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
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, opts, c.required), scope)
    result.stats["required_payload_fields"] = c.required
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
