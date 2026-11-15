"""Glue: pull the three inventories through read-only connectors, then reconcile.

Two ways to read the vector index:

* one pass over the whole collection (the default, and the only way to find vectors that belong to no known document), and
* in slices (when "only audit documents found in the source" is on): the index is read for a few thousand documents at a time.
  After every slice that slice is reconciled and handed to ``AuditOptions.on_slice``, which records it. A slice that is done is
  a checkpoint: if the scan stops later (a timeout, an index that stays unreachable), the audit ends as ``partial`` with
  everything before the stop already reported, and a resumed audit continues after the last checkpoint.

Either way an incomplete scan is never treated as proof that anything is missing: a document is only judged once the part
of the index that could hold its vectors has been read completely.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

from ..connectors.base import (  # noqa: F401  (AuditTimeout is re-exported: the API maps it to a 504)
    AuditTimeout,
    IndexConnector,
    ManifestConnector,
    ScanStats,
    SourceConnector,
    check_deadline,
)
from ..models import (
    SEVERITY_RANK,
    ChunkRow,
    DocKey,
    DocSummary,
    Finding,
    Fingerprint,
    IssueType,
    ManifestRow,
    Scope,
    SourceDoc,
)
from .coverage import Unique, id_warnings
from .index_state import AggContext, IndexAggregator
from .isolation import build_summary as build_isolation
from .reconcile import (
    DELETED_STATUSES,
    ReconcileConfig,
    ReconcileResult,
    collection_checks,
    derive_required_fields,
    manifest_block,
    reconcile,
    refresh_after_escalation,
)
from .retrieval import probe_findings
from .versions import version_check

T = TypeVar("T")

SLICE_DOCUMENTS = 5000  # documents per slice of the index (the checkpoint granularity of a sliced scan)
COLLECTION_KEY: DocKey = ("*", "*")  # collection-level findings (vectors without a document id, a wrong vector size) live here


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
    names: dict[str, str] = field(default_factory=dict)  # setting names quoted in warnings (see IntegrityService.id_names)
    # deletion checks while only the source's documents are audited: documents an earlier audit saw in the source (so a
    # document that has since vanished from it is looked for in the index), and the slice size / resume point of a sliced scan
    prior_source_keys: frozenset[DocKey] | None = None
    slice_size: int = SLICE_DOCUMENTS
    resume_after: DocKey | None = None  # a resumed audit skips every document up to and including this one
    resumed_from: str | None = None  # the run it continues (recorded in the result)
    carry: dict[str, Any] | None = None  # counts of the slices an earlier, interrupted run already reported
    on_slice: Callable[[SliceResult], None] | None = None  # called after each completed slice (the checkpoint)


@dataclass
class SliceResult:
    """One completed slice of a sliced scan: everything about its documents is final and can be recorded."""

    index: int  # 1-based; 0 for the collection-level findings
    total: int
    scope: Scope
    findings: list[Finding]
    summaries: list[DocSummary]
    last_key: DocKey | None
    documents_done: int
    documents_total: int
    points_scanned: int
    carry: dict[str, Any]  # running counts of everything reported so far (this run and the one it resumed)
    final: bool = False  # the collection-level step after the last slice


class PartialAudit(Exception):
    """The scan stopped part-way. The slices before it are complete and were recorded; nothing is claimed about the rest."""

    def __init__(self, reason: str, result: ReconcileResult, scan: dict[str, Any], carry: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason, self.result, self.scan, self.carry = reason, result, scan, carry


def _guard(items: Iterable[T], deadline: float | None, what: str) -> Iterator[T]:
    """Pass items through, but give up with a clear message once the time budget is spent."""
    for i, item in enumerate(items):
        if i % 200 == 0:
            check_deadline(deadline, what, f" (after {i:,} items)")
        yield item


def _count(stats: ScanStats, items: Iterable[T]) -> Iterator[T]:
    for item in items:
        stats.points += 1
        yield item


def _fill(unique: Unique, items: Iterable, keep: Callable[[Any], bool] = lambda _: True) -> dict:
    """Index documents by (tenant, document id), counting ids that turn up more than once instead of hiding them."""
    for item in items:
        if keep(item):
            unique.add(item.key, item)
    return unique.items


def _note(opts: AuditOptions, t0: float, phase: str, **info: Any) -> None:
    """Report progress. Best effort: it must never break an audit."""
    if opts.progress is None:
        return
    try:
        opts.progress(phase, elapsed_seconds=round(time.monotonic() - t0, 1), **info)
    except Exception:  # a failed progress write is not worth losing the audit for
        pass


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


class _Totals:
    """Running counts of what a (possibly resumed) audit has reported, so a partial run still has honest statistics."""

    def __init__(self, carry: dict[str, Any] | None = None) -> None:
        self.by_status: Counter = Counter()
        self.by_type: Counter = Counter()
        self.by_sev: Counter = Counter()
        if carry:
            self.by_status.update(carry.get("documents_by_status", {}))
            self.by_type.update(carry.get("findings_by_type", {}))
            self.by_sev.update(carry.get("findings_by_severity", {}))

    def add(self, findings: list[Finding], summaries: list[DocSummary]) -> None:
        self.by_status.update(s.status for s in summaries)
        self.by_type.update(f.type.value for f in findings)
        self.by_sev.update(f.severity.value for f in findings)

    def carry(self) -> dict[str, Any]:
        return {"documents_by_status": dict(self.by_status), "findings_by_type": dict(self.by_type),
                "findings_by_severity": dict(self.by_sev)}

    def stats(self) -> dict[str, Any]:
        total = sum(self.by_status.values())
        healthy = self.by_status.get("healthy", 0) + self.by_status.get("pending", 0)
        return {
            "documents_total": total, "documents_by_status": dict(self.by_status),
            "findings_total": sum(self.by_type.values()), "findings_by_type": dict(self.by_type),
            "findings_by_severity": {k: self.by_sev.get(k, 0) for k in sorted(SEVERITY_RANK, key=lambda x: -SEVERITY_RANK[x])},
            "health_score": round(100.0 * healthy / total, 1) if total else 100.0,
        }


def scan_block(
    status: str, stats: ScanStats, *, mode: str, slices_total: int = 1, slices_done: int = 1, documents_done: int | None = None,
    documents_total: int | None = None, checkpoint: DocKey | None = None, resumed_from: str | None = None, reason: str | None = None,
) -> dict[str, Any]:
    """How complete and how reliable the scan was: the block a result carries as ``stats.scan``.

    ``status`` is ``completed`` (every slice read), ``partial`` (stopped part-way: what was reported before the stop is final,
    the rest is unknown), ``failed`` (nothing usable) or ``in_progress`` (a progress note)."""
    if documents_total:
        percent: float | None = round(100.0 * (documents_done or 0) / documents_total, 1)
    elif status == "completed":
        percent = 100.0
    elif stats.estimated_total:
        percent = round(min(99.9, 100.0 * stats.points / stats.estimated_total), 1)
    else:
        percent = None
    if status == "completed":
        percent = 100.0
    return {
        "status": status, "complete": status == "completed", "provisional": status != "completed", "mode": mode,
        **stats.snapshot(), "percent": percent, "slices_total": slices_total, "slices_done": slices_done,
        "documents_done": documents_done, "documents_total": documents_total, "checkpoints_saved": slices_done,
        "checkpoint": list(checkpoint) if checkpoint else None, "resumed_from": resumed_from, "stopped_because": reason,
    }


def _shared_stats(index: Any) -> ScanStats:
    stats = getattr(index, "scan_stats", None)
    if not isinstance(stats, ScanStats):
        stats = ScanStats()
    return stats


def _attach(exc: BaseException, block: dict[str, Any]) -> None:
    """Hand the scan's numbers to whoever records the failure (an exception can carry extra attributes)."""
    try:
        exc.scan_snapshot = block  # type: ignore[attr-defined]
    except Exception:
        pass


@dataclass
class Collected:
    source: dict[DocKey, SourceDoc]
    manifest: dict[DocKey, ManifestRow]
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None
    agg: IndexAggregator
    required: list[str]
    started: float = 0.0  # time.monotonic() when collecting began (for progress notes)
    warnings: list[dict] = field(default_factory=list)  # ids that appear twice, rows without an id: see coverage.id_warnings
    deletion_keys: set[DocKey] = field(default_factory=set)  # source-only: documents gone from the source that are looked for in the index
    scan_keys: list[DocKey] | None = None  # source-only: the documents whose vectors are read (sorted), when the scan was left to the caller
    scan_tenant: str | None = None
    has_manifest: bool = True  # False: no manifest is connected (the manifest checks are left out, see reconcile.manifest_block)


def _reading_index(index: Any) -> str:
    """The progress step that names the vector store ("Qdrant", "pgvector"): the connector says what it is called."""
    return f"reading the vector index ({getattr(index, 'label', 'Qdrant')})"


def _start_progress(index: Any, opts: AuditOptions, t0: float, stats: ScanStats) -> None:
    """Let the connector report page-by-page progress (throttled by the connector)."""
    if not hasattr(index, "on_progress"):
        return

    def report(s: ScanStats) -> None:
        pct = round(min(99.9, 100.0 * s.points / s.estimated_total), 1) if s.estimated_total else None
        _note(opts, t0, _reading_index(index), points_scanned=s.points, estimated_total=s.estimated_total,
              percent=pct, retries=s.retries, recovered_errors=s.recovered_errors)

    index.on_progress = report


def collect(
    source: SourceConnector, manifest: ManifestConnector, index: IndexConnector, opts: AuditOptions,
    scope: Scope | None = None, *, scan: bool = True,
) -> Collected:
    """Read the three inventories. With ``scan=False`` the vector index is left unread (a sliced audit reads it slice by slice)."""
    dl = opts.deadline
    t0 = time.monotonic()
    stats = _shared_stats(index)
    for connector in (source, manifest, index):  # connectors that page through data check the budget between pages
        if hasattr(connector, "deadline"):
            connector.deadline = dl
    lookup = getattr(source, "lookup", None)
    has_manifest = bool(getattr(manifest, "available", True))
    src_u: Unique = Unique(lambda d: d.source_uri)
    man_u: Unique = Unique(lambda r: (r.source_uri or "a manifest row") + (f" (status: {r.processing_status})" if r.processing_status else ""))
    if opts.lookup_from_manifest and lookup is not None and has_manifest:
        # large buckets: read exactly the files the manifest names (one HEAD each) instead of listing everything.
        # This also keeps "re-audit one document" fast: the manifest is queried for just that document.
        _note(opts, t0, "reading the processing manifest")
        man = _fill(man_u, _guard(manifest.documents(scope), dl, "the processing manifest"))
        _note(opts, t0, "looking up the files the manifest names (S3)", manifest_rows=len(man))
        src = _fill(src_u, _guard(lookup(r.source_uri for r in man.values()), dl, "the source bucket"),
                    keep=lambda d: scope is None or scope.matches(d.key))
    else:
        _note(opts, t0, "listing the source documents (S3)")
        src = _fill(src_u, _guard(source.inventory(scope), dl, "the source bucket"))  # first: the index scan classifies against it
        _note(opts, t0, "reading the processing manifest", source_documents=len(src))
        man = _fill(man_u, _guard(manifest.documents(scope), dl, "the processing manifest"))
    scan_scope, scan_nothing = scope, False
    deletion_keys: set[DocKey] = set()
    scan_keys: list[DocKey] | None = None
    if opts.source_only:
        if scope is None or scope.keys is None:
            # Only the source's documents are audited, but a document that has been DELETED must still be checked: its
            # vectors may be left behind. Deleted means: seen in the source by an earlier audit and gone now, or marked
            # deleted in the manifest. Other manifest rows that merely have no file here (another source) stay ignored.
            gone = set(opts.prior_source_keys or ()) - set(src)
            marked = {k for k, r in man.items() if k not in src and _norm(r.processing_status) in DELETED_STATUSES}
            deletion_keys = gone | marked
            if scope is not None and scope.tenant:
                deletion_keys = {k for k in deletion_keys if k[0] == scope.tenant}
        man = man_u.restrict(lambda k: k in src or k in deletion_keys)  # rows of other documents are ignored, so are their duplicates
        if scope is None or scope.keys is None:
            wanted = set(src) | deletion_keys
            if wanted:  # read only the points of known documents (server-side filter) instead of the whole collection
                scan_scope = Scope(tenant=scope.tenant if scope else None, keys=frozenset(wanted))
                scan_keys = sorted(wanted)
            else:
                scan_nothing = True
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None = None
    if manifest.has_chunk_manifest:
        chunk_rows = defaultdict(dict)
        for c in _guard(manifest.chunks(scope), dl, "the chunk manifest"):
            if opts.source_only and (c.tenant_id, c.document_id) not in src and (c.tenant_id, c.document_id) not in deletion_keys:
                continue
            chunk_rows[(c.tenant_id, c.document_id)][c.chunk_id] = c
    required = derive_required_fields(opts.required_fields, {k[0] for k in src} | opts.known_tenants)
    ctx = AggContext(source=src, manifest=man, target=opts.target, default_tenant=opts.default_tenant,
                     required_fields=required, chunk_rows=chunk_rows)
    agg = IndexAggregator(ctx)
    _start_progress(index, opts, t0, stats)
    if scan and not scan_nothing:
        _note(opts, t0, _reading_index(index), source_documents=len(src), manifest_rows=len(man))
        if hasattr(index, "estimated_points"):
            index.estimated_points()
        agg.add_all(_count(stats, _guard(index.scan(scan_scope, with_vectors=opts.check_vectors), dl, "the vector index")))
    warnings = id_warnings(src_u, man_u, getattr(manifest, "empty_ids", 0) or 0, opts.names)
    return Collected(src, man, chunk_rows, agg, required, started=t0, warnings=warnings, deletion_keys=deletion_keys,
                     scan_keys=scan_keys, scan_tenant=scope.tenant if scope else None, has_manifest=has_manifest)


def _config(index: IndexConnector, opts: AuditOptions, required: list[str], has_manifest: bool = True) -> ReconcileConfig:
    return ReconcileConfig(target=opts.target, grace_minutes=opts.grace_minutes,
                           now=opts.now or datetime.now(timezone.utc), vector_sizes=index.vector_sizes(),
                           required_fields=required, has_manifest=has_manifest)


def _deletion_summary(c: Collected, findings: list[Finding]) -> dict[str, Any]:
    leftover = {f.key for f in findings if f.type in (IssueType.ORPHAN_VECTOR, IssueType.TENANT_MISMATCH) and f.key in c.deletion_keys}
    return {"documents_checked": len(c.deletion_keys), "with_remaining_vectors": len(leftover),
            "verified_gone": len(c.deletion_keys) - len(leftover)}


def run_reconciliation(
    source: SourceConnector,
    manifest: ManifestConnector,
    index: IndexConnector,
    opts: AuditOptions,
    scope: Scope | None = None,
) -> ReconcileResult:
    sliced = opts.source_only and (scope is None or scope.keys is None)
    stats = _shared_stats(index)
    stats.__init__()  # type: ignore[misc]  # a fresh count for this audit
    try:
        c = collect(source, manifest, index, opts, scope, scan=not sliced)
    except Exception as exc:
        _attach(exc, scan_block("failed", stats, mode="sliced" if sliced else "single_pass", slices_done=0,
                                reason=f"{type(exc).__name__}: {str(exc)[:200]}"))
        raise
    if sliced:
        return _run_sliced(index, opts, scope, c, stats)

    _note(opts, c.started, "comparing the three lists", source_documents=len(c.source), manifest_rows=len(c.manifest))
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, opts, c.required, c.has_manifest), scope)
    result.stats["required_payload_fields"] = c.required
    result.stats["manifest"] = manifest_block(c.has_manifest)
    result.stats["warnings"] = c.warnings
    if opts.source_only:
        result.stats["source_documents_only"] = True
    if c.deletion_keys or opts.source_only:
        result.stats["deletion_check"] = _deletion_summary(c, result.findings)
    if opts.probe and result.findings:
        result.stats["retrieval_probes"] = probe_findings(
            index, result.findings, top_k=opts.probe_top_k, max_probes=opts.probe_max)
        refresh_after_escalation(result)  # probes can escalate severities
    if scope is None or scope.is_full:  # the isolation picture needs the whole index: not for scoped runs
        result.stats["isolation"] = build_isolation(c.agg, c.source, c.manifest, result, limited=opts.source_only)
    result.stats["scan"] = scan_block("completed", stats, mode="single_pass")
    return result


def _run_sliced(index: IndexConnector, opts: AuditOptions, scope: Scope | None, c: Collected, stats: ScanStats) -> ReconcileResult:
    """Read the index a slice of documents at a time, reconciling and handing over each slice as soon as it is complete."""
    dl = opts.deadline
    keys = c.scan_keys or []
    remaining = [k for k in keys if opts.resume_after is None or k > opts.resume_after]
    size = max(1, opts.slice_size)
    slices = [remaining[i:i + size] for i in range(0, len(remaining), size)]
    total_docs = len(keys)
    done_docs = total_docs - len(remaining)
    cfg = _config(index, opts, c.required, c.has_manifest)
    totals = _Totals(opts.carry)
    findings: list[Finding] = []
    summaries: list[DocSummary] = []
    probes_left, probes_done = opts.probe_max, 0
    mode_kw = {"mode": "sliced", "resumed_from": opts.resumed_from}
    last_key: DocKey | None = opts.resume_after
    failure: BaseException | None = None
    done = 0

    for n, part in enumerate(slices, 1):
        slice_scope = Scope(tenant=c.scan_tenant, keys=frozenset(part))
        try:
            check_deadline(dl, "the vector index", f" (before slice {n} of {len(slices)})")
            c.agg.add_all(_count(stats, _guard(index.scan(slice_scope, with_vectors=opts.check_vectors), dl, "the vector index")))
            res = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, cfg, slice_scope)
        except Exception as exc:  # whatever stopped this slice, the earlier ones stay reported and this one claims nothing
            failure = exc
            break
        if opts.probe and res.findings and probes_left > 0:
            probes_done += (used := probe_findings(index, res.findings, top_k=opts.probe_top_k, max_probes=probes_left))
            probes_left -= used
            refresh_after_escalation(res)
        findings += res.findings
        summaries += res.summaries
        totals.add(res.findings, res.summaries)
        done += 1
        done_docs += len(part)
        last_key = part[-1]
        _note(opts, c.started, "scanned a slice of the index", slice=n, slices=len(slices), documents_done=done_docs,
              documents_total=total_docs, percent=round(100.0 * done_docs / max(1, total_docs), 1), **stats.snapshot())
        if opts.on_slice is not None:  # the checkpoint: this slice is final and is recorded now
            opts.on_slice(SliceResult(n, len(slices), slice_scope, res.findings, res.summaries, last_key, done_docs, total_docs,
                                      stats.points, totals.carry()))

    result = ReconcileResult(findings=findings, summaries=summaries)
    result.stats = {"source_documents": len(c.source), "manifest_rows": len(c.manifest), "index_points": c.agg.points_seen,
                    **totals.stats(), "required_payload_fields": c.required, "warnings": c.warnings, "source_documents_only": True,
                    "deletion_check": _deletion_summary(c, findings), "manifest": manifest_block(c.has_manifest)}
    if probes_done:
        result.stats["retrieval_probes"] = probes_done

    if failure is not None:
        reason = f"{type(failure).__name__}: {str(failure)[:300]}"
        if done == 0 and opts.resume_after is None:  # not one slice finished: there is nothing to keep
            _attach(failure, scan_block("failed", stats, slices_total=len(slices), slices_done=0, documents_done=done_docs,
                                        documents_total=total_docs, reason=reason, **mode_kw))
            raise failure
        block = scan_block("partial", stats, slices_total=len(slices), slices_done=done, documents_done=done_docs,
                           documents_total=total_docs, checkpoint=last_key, reason=reason, **mode_kw)
        result.stats["scan"] = block
        raise PartialAudit(reason, result, block, totals.carry()) from failure

    # every slice is read: the collection-level checks (a wrong vector size, vectors without a document id) come last
    extra = collection_checks(c.agg, cfg)
    findings += extra
    result.findings = findings
    totals.add(extra, [])
    result.stats.update(totals.stats())
    if opts.on_slice is not None:
        opts.on_slice(SliceResult(0, len(slices), Scope(keys=frozenset({COLLECTION_KEY})), extra, [], last_key, done_docs, total_docs,
                                  stats.points, totals.carry(), final=True))
    if opts.resume_after is None:  # after a resumed audit the picture is built from only the later slices: leave it to a full audit
        result.stats["isolation"] = build_isolation(c.agg, c.source, c.manifest, result, limited=True)
    result.stats["scan"] = scan_block("completed", stats, slices_total=len(slices), slices_done=done, documents_done=done_docs,
                                      documents_total=total_docs, checkpoint=last_key, **mode_kw)
    return result


def inspect_document(
    source: SourceConnector, manifest: ManifestConnector, index: IndexConnector, opts: AuditOptions,
    tenant: str, document_id: str,
) -> dict[str, Any]:
    """A live, three-way view of one document: what the source, the manifest and the index each say."""
    key = (tenant, document_id)
    scope = Scope(keys=frozenset({key}))
    c = collect(source, manifest, index, opts, scope)
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, opts, c.required, c.has_manifest), scope)
    s, m, st = c.source.get(key), c.manifest.get(key), c.agg.states.get(key)

    chunks: list[dict[str, Any]] = []
    if st:
        for (coll, ck, cls), slot in st.slots.items():
            chunks.append({"collection": coll, "chunk_id": ck, "chunk_index": slot.index, "class": cls,
                           "copies": len(slot.ids), "point_ids": slot.ids[:3]})
        chunks.sort(key=lambda r: (r["class"], r["chunk_index"] if r["chunk_index"] is not None else -1, r["chunk_id"]))
    expected = sorted((c.chunk_rows or {}).get(key, {}).values(), key=lambda r: (r.chunk_index is None, r.chunk_index))
    return {
        "tenant_id": tenant, "document_id": document_id, "manifest_connected": c.has_manifest,
        "version_check": version_check(s, m, st, (c.chunk_rows or {}).get(key), opts.target),
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
