"""The reconciliation engine: source of truth (S3) vs processing manifest (Postgres) vs vector index (Qdrant).

``reconcile`` is a pure function over in-memory inventories, so it is fast to test and independent
of any connector. It produces typed findings with evidence plus one summary per document.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import (
    EMBEDDING_FIELDS,
    SEVERITY_RANK,
    Action,
    ChunkRow,
    DocKey,
    DocSummary,
    Finding,
    Fingerprint,
    IssueType,
    ManifestRow,
    Scope,
    Severity,
    SourceDoc,
    max_severity,
)
from .index_state import (
    OUTDATED,
    STALE,
    UNKNOWN,
    DocIndexState,
    IndexAggregator,
)

SUCCESS_STATUSES = frozenset({"success", "succeeded", "indexed", "completed", "complete", "done", "ready", "ok", "processed"})
INFLIGHT_STATUSES = frozenset({"pending", "queued", "processing", "running", "in_progress", "indexing", "parsing", "embedding"})
FAILED_STATUSES = frozenset({"failed", "error", "errored", "failure"})
DELETED_STATUSES = frozenset({"deleted", "tombstoned", "removed"})

MAX_LIST = 50  # cap on ids embedded in a finding's evidence
MAX_REMOVAL_IDS = 5000


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class ReconcileConfig:
    target: Fingerprint | None = None
    grace_minutes: int = 0
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    vector_sizes: dict[str, int | None] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)


@dataclass
class ReconcileResult:
    findings: list[Finding] = field(default_factory=list)
    summaries: list[DocSummary] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def derive_required_fields(configured: list[str], tenants: set[str]) -> list[str]:
    """document_id + source_hash are always needed to reconcile; tenant_id once there is >1 tenant."""
    if configured:
        return configured
    fields = ["document_id", "source_hash"]
    if len(tenants) > 1:
        fields.insert(0, "tenant_id")
    return fields


def _trim(items: list, n: int = MAX_LIST) -> list:
    return items[:n]


def _removal(points: dict[str, list[str]]) -> dict[str, Any]:
    total = sum(len(v) for v in points.values())
    capped = {c: ids[:MAX_REMOVAL_IDS] for c, ids in points.items()}
    return {"removal_points": capped, "removal_count": total, "removal_truncated": total > MAX_REMOVAL_IDS}


# ----------------------------------------------------------------------------------------------
def reconcile(
    source: dict[DocKey, SourceDoc],
    manifest: dict[DocKey, ManifestRow],
    chunk_manifest: dict[DocKey, dict[str, ChunkRow]] | None,
    agg: IndexAggregator,
    cfg: ReconcileConfig,
    scope: Scope | None = None,
) -> ReconcileResult:
    states = agg.states
    keys = set(source) | set(manifest) | set(states)
    if scope is not None and not scope.is_full:
        keys = {k for k in keys if scope.matches(k)}

    src_tenants_by_doc: dict[str, set[str]] = defaultdict(set)
    for tenant, doc in source:
        src_tenants_by_doc[doc].add(tenant)

    result = ReconcileResult()
    for key in sorted(keys):
        s, m, ix = source.get(key), manifest.get(key), states.get(key)
        has_vectors = bool(ix and ix.point_count)
        findings: list[Finding] = []
        pending = False

        if s is None:
            findings += _check_not_in_source(key, m, ix, src_tenants_by_doc)
        elif not has_vectors:
            pending = _in_grace(s, m, cfg)
            if not pending:
                findings += _check_missing(key, s, m, cfg)
        else:
            assert ix is not None
            pending = ix.live_count() == 0 and ix.classes[STALE] > 0 and _source_changed_recently(s, cfg)
            if not pending:
                findings += _check_indexed(key, s, m, ix, (chunk_manifest or {}).get(key), cfg)

        result.findings += findings
        result.summaries.append(_summarize(key, s, m, ix, findings, pending))

    if scope is None or scope.is_full:
        result.findings += _collection_checks(agg, cfg)

    result.stats = _stats(result, source, manifest, agg)
    return result


# ---------------------------------------------------------------------------------------------- #
# graceful handling of documents that are probably still being ingested


def _source_changed_recently(s: SourceDoc, cfg: ReconcileConfig) -> bool:
    if cfg.grace_minutes <= 0:
        return False
    lm = parse_ts(s.last_modified)
    return bool(lm and lm >= cfg.now - timedelta(minutes=cfg.grace_minutes))


def _in_grace(s: SourceDoc, m: ManifestRow | None, cfg: ReconcileConfig) -> bool:
    if cfg.grace_minutes <= 0:
        return False
    cutoff = cfg.now - timedelta(minutes=cfg.grace_minutes)
    if _source_changed_recently(s, cfg):
        return True
    if m and _norm(m.processing_status) in INFLIGHT_STATUSES:
        upd = parse_ts(m.updated_at)
        return upd is None or upd >= cutoff
    return False


# ---------------------------------------------------------------------------------------------- #
def _finding(
    typ: IssueType, sev: Severity, key: DocKey, title: str, detail: str, evidence: dict, action: Action,
    collection: str | None = None,
) -> Finding:
    return Finding(typ, sev, key[0], key[1], collection, title, detail, evidence, action)


def _check_not_in_source(
    key: DocKey, m: ManifestRow | None, ix: DocIndexState | None, src_tenants: dict[str, set[str]]
) -> list[Finding]:
    if ix and ix.point_count:
        other = sorted(src_tenants.get(key[1], set()) - {key[0]})
        removal = _removal(ix.points_of(*ix.classes.keys()))
        ev = {
            "point_count": ix.point_count,
            "chunks": len({k[1] for k in ix.slots}),
            "collections": sorted(ix.collections),
            "sample_point_ids": ix.sample_ids,
            "manifest_present": m is not None,
            "manifest_status": m.processing_status if m else None,
            **removal,
        }
        if other:
            ev["expected_tenants"] = other
            return [_finding(
                IssueType.TENANT_MISMATCH, Severity.CRITICAL, key,
                "Vectors are tagged with the wrong tenant",
                f"{ix.point_count} vectors are indexed under tenant '{key[0]}' but the source document "
                f"only exists under tenant(s) {', '.join(other)}. This can leak content across tenants.",
                ev, Action.CLEANUP_VECTORS,
            )]
        return [_finding(
            IssueType.ORPHAN_VECTOR, Severity.HIGH, key,
            "Vectors remain for a document that no longer exists",
            f"{ix.point_count} vectors still point at a document that is gone from the source. "
            "Retrieval can keep returning deleted content.",
            ev, Action.CLEANUP_VECTORS,
        )]
    if m and _norm(m.processing_status) not in DELETED_STATUSES:
        return [_finding(
            IssueType.MANIFEST_ORPHAN, Severity.LOW, key,
            "Manifest row for a document that no longer exists",
            "The processing manifest still lists this document, but it is gone from both the source "
            "and the index.",
            {"manifest_status": m.processing_status, "source_uri": m.source_uri}, Action.INVESTIGATE,
        )]
    return []


def _check_missing(key: DocKey, s: SourceDoc, m: ManifestRow | None, cfg: ReconcileConfig) -> list[Finding]:
    status = _norm(m.processing_status) if m else None
    claims_success = bool(m and (status in SUCCESS_STATUSES or (m.indexed_chunk_count or 0) > 0))
    ev: dict[str, Any] = {
        "manifest_present": m is not None,
        "manifest_status": m.processing_status if m else None,
        "manifest_indexed_chunk_count": m.indexed_chunk_count if m else None,
        "expected_chunk_count": m.expected_chunk_count if m else None,
        "pipeline_reported_success": claims_success,
        "source_hash": s.source_hash,
        "source_version": s.source_version,
    }
    if m and status in INFLIGHT_STATUSES:
        ev["stuck_in_flight_since"] = m.updated_at
        reason = f"The pipeline has had this document in '{m.processing_status}' since {m.updated_at}."
    elif m is None:
        reason = "The document has never been picked up by the pipeline (no manifest row)."
    elif status in FAILED_STATUSES:
        reason = f"The pipeline marked it '{m.processing_status}' and it was never retried successfully."
    elif claims_success:
        reason = (
            f"The pipeline reports '{m.processing_status}' with {m.indexed_chunk_count} indexed chunks, "
            "but there are no vectors in the index."
        )
    else:
        reason = "The manifest has no completed indexing record for it."
    sev = Severity.CRITICAL if claims_success else Severity.HIGH
    return [_finding(
        IssueType.MISSING_EMBEDDING, sev, key,
        "Document has no embeddings in the index" + (" (pipeline claims success)" if claims_success else ""),
        reason, ev, Action.REINDEX_FULL,
    )]


# ---------------------------------------------------------------------------------------------- #
def _check_indexed(
    key: DocKey,
    s: SourceDoc,
    m: ManifestRow | None,
    ix: DocIndexState,
    chunk_rows: dict[str, ChunkRow] | None,
    cfg: ReconcileConfig,
) -> list[Finding]:
    out: list[Finding] = []
    live, stale, outdated = ix.live_count(), ix.classes[STALE], ix.classes[OUTDATED]
    claims_success = bool(m and _norm(m.processing_status) in SUCCESS_STATUSES)
    base_ev = {
        "collections": sorted(ix.collections),
        "point_count": ix.point_count,
        "source_hash": s.source_hash,
        "source_version": s.source_version,
        "hash_reliable": s.hash_reliable,
    }
    stale_points = ix.points_of(STALE)

    # ---- freshness ----------------------------------------------------------------------------
    stale_by_manifest = False
    if live == 0 and stale > 0:
        ev = {**base_ev, "indexed_hashes": _trim([h for h in ix.hashes if h]),
              "indexed_versions": _trim(list(ix.versions)), "pipeline_status": m.processing_status if m else None,
              "outdated_points": stale, **_removal(stale_points)}
        sev = Severity.HIGH if s.hash_reliable else Severity.MEDIUM
        note = "" if s.hash_reliable else " (source hash is a multipart ETag, so a re-upload of identical content can look like a change)"
        out.append(_finding(
            IssueType.STALE_EMBEDDING, sev, key, "Embeddings are from an older version of the document",
            f"The source changed but all {stale} indexed vectors still describe the previous version{note}.",
            ev, Action.REINDEX_FULL,
        ))
    elif live > 0 and (stale > 0 or outdated > 0):
        reasons = []
        if stale:
            reasons.append(f"{stale} vectors from an older document version")
        if outdated:
            reasons.append(f"{outdated} vectors built with an older pipeline config")
        pts = ix.points_of(STALE, OUTDATED)
        ev = {**base_ev, "live_points": live, "stale_points": stale, "outdated_config_points": outdated,
              "config_conflicts": ix.outdated_conflicts, **_removal(pts)}
        out.append(_finding(
            IssueType.SUPERSEDED_ACTIVE, Severity.MEDIUM, key,
            "Superseded vectors are still active next to the current ones",
            "The latest version is indexed, but " + " and ".join(reasons) + " still answer queries.",
            ev, Action.CLEANUP_VECTORS,
        ))

    # when the index cannot say which version it holds, fall back to what the manifest recorded
    if live == ix.classes[UNKNOWN] and live > 0 and stale == 0 and m and m.source_hash and s.source_hash \
            and m.source_hash != s.source_hash:
        stale_by_manifest = True
        out.append(_finding(
            IssueType.STALE_EMBEDDING, Severity.HIGH, key, "Embeddings are from an older version of the document",
            "The index payloads carry no hash/version, but the processing manifest last indexed a different "
            "source hash than the one in the source.",
            {**base_ev, "manifest_source_hash": m.source_hash}, Action.REINDEX_FULL,
        ))

    is_stale = (live == 0 and stale > 0) or stale_by_manifest

    # ---- completeness (only meaningful for the live generation) ---------------------------------
    partial: Finding | None = None
    if live > 0 and not is_stale:
        partial = _check_partial(key, m, ix, chunk_rows, claims_success)
        if partial:
            out.append(partial)
        drop, dup_chunks, examples = ix.duplicate_points()
        if dup_chunks:
            extra = sum(len(v) for v in drop.values())
            out.append(_finding(
                IssueType.DUPLICATE_CHUNK, Severity.MEDIUM, key, "Duplicate active chunks",
                f"{dup_chunks} chunk(s) are indexed more than once ({extra} extra vectors), typically from "
                "retried or non-idempotent ingestion.",
                {**base_ev, "duplicated_chunks": dup_chunks, "extra_points": extra, "example_chunks": examples,
                 "keep_policy": "first_seen", **_removal(drop)}, Action.CLEANUP_VECTORS,
            ))

    if ix.empty_vector_ids:
        by_coll: dict[str, list[str]] = {}
        for coll, pid in ix.empty_vector_ids:
            by_coll.setdefault(coll, []).append(pid)
        out.append(_finding(
            IssueType.EMPTY_EMBEDDING, Severity.HIGH, key, "Points exist without a usable embedding",
            f"{len(ix.empty_vector_ids)} point(s) have a missing, empty or all-zero vector, so they can "
            "never be retrieved correctly.",
            {**base_ev, "empty_points": len(ix.empty_vector_ids),
             "sample_point_ids": _trim([p for _, p in ix.empty_vector_ids], 10)}, Action.REINDEX_FULL,
        ))

    # ---- pipeline configuration ----------------------------------------------------------------
    drift = _check_drift(key, m, ix, cfg, base_ev, live, stale, outdated)
    if drift:
        out.append(drift)

    # ---- metadata ---------------------------------------------------------------------------
    meta = _check_metadata(key, s, m, ix, base_ev, is_stale, live, explained_count=partial is not None)
    if meta:
        out.append(meta)

    # a document the pipeline believes is fine is the dangerous case: surface it
    if claims_success:
        for f in out:
            if f.type in (IssueType.STALE_EMBEDDING, IssueType.PARTIAL_INDEX, IssueType.EMPTY_EMBEDDING):
                f.evidence["pipeline_reported_success"] = True
    return out


def _check_partial(
    key: DocKey, m: ManifestRow | None, ix: DocIndexState, chunk_rows: dict[str, ChunkRow] | None, claims_success: bool
) -> Finding | None:
    live = ix.live_chunks()
    missing: list[str] = []
    method = ""
    expected_total = 0
    indexed_total = sum(len(v) for v in live.values())
    unexpected: list[str] = []

    if chunk_rows:
        method = "chunk_manifest"
        expected_ids = set(chunk_rows)
        expected_total = len(expected_ids)
        by_index = {r.chunk_index: cid for cid, r in chunk_rows.items() if r.chunk_index is not None}
        for coll, chunks in live.items():
            have_ids = {ck for ck in chunks if not ck.startswith(("idx:", "pt:"))}
            if have_ids:
                missing += [f"{coll}:{c}" for c in sorted(expected_ids - have_ids)]
                unexpected += [f"{coll}:{c}" for c in sorted(have_ids - expected_ids)]
            else:  # payloads without chunk ids: compare chunk indexes instead
                have_idx = {i for i in chunks.values() if i is not None}
                missing += [f"{coll}:{cid}" for i, cid in sorted(by_index.items()) if i not in have_idx]
    elif m and m.expected_chunk_count:
        method = "expected_chunk_count"
        expected_total = m.expected_chunk_count
        for coll, chunks in live.items():
            idx = {i for i in chunks.values() if i is not None}
            if idx:
                missing += [f"{coll}:#{i}" for i in range(expected_total) if i not in idx]
            elif len(chunks) < expected_total:
                missing += [f"{coll}:<{expected_total - len(chunks)} unidentified>"]
    else:
        method = "index_gaps"
        for coll, chunks in live.items():
            idx = {i for i in chunks.values() if i is not None}
            if idx:
                top = max(idx)
                expected_total = max(expected_total, top + 1)
                missing += [f"{coll}:#{i}" for i in range(top + 1) if i not in idx]

    if not missing:
        return None
    suspected = method == "index_gaps"
    sev = Severity.MEDIUM if suspected else (Severity.CRITICAL if claims_success else Severity.HIGH)
    ev = {
        "method": method,
        "expected_chunks": expected_total,
        "indexed_chunks": indexed_total,
        "missing_count": len(missing),
        "missing_chunks": _trim(missing),
        "unexpected_chunks": _trim(unexpected),
        "pipeline_reported_success": claims_success,
        "collections": sorted(ix.collections),
        "confidence": "suspected (gap in chunk indexes)" if suspected else "confirmed",
    }
    return _finding(
        IssueType.PARTIAL_INDEX, sev, key,
        "Only part of the document is indexed" + (" (pipeline claims success)" if claims_success and not suspected else ""),
        f"{len(missing)} expected chunk(s) are missing from the index "
        f"({indexed_total} indexed vs {expected_total} expected).",
        ev, Action.REINDEX_CHUNKS,
    )


def _check_drift(
    key: DocKey, m: ManifestRow | None, ix: DocIndexState, cfg: ReconcileConfig, base_ev: dict,
    live: int, stale: int, outdated: int,
) -> Finding | None:
    # outdated-config vectors with no current-generation vectors: the doc was never re-embedded
    if outdated > 0 and live == 0 and stale == 0 and cfg.target is not None:
        diff = ix.outdated_conflicts
        high = any(k in EMBEDDING_FIELDS for k in diff)
        return _finding(
            IssueType.PIPELINE_DRIFT, Severity.HIGH if high else Severity.MEDIUM, key,
            "Indexed with an outdated pipeline configuration",
            "Content is current, but it was parsed/chunked/embedded with a different configuration than the "
            "target: " + ", ".join(f"{k} ({v['indexed']} -> {v['target']})" for k, v in diff.items()) + ".",
            {**base_ev, "differences": diff, "outdated_points": outdated}, Action.REINDEX_FULL,
        )
    # mixed fingerprints inside one document's live vectors (no target needed)
    if len(ix.fp_live) > 1:
        fps = [ix.fp_objs[k] for k in ix.fp_live]
        varying = sorted({f for f in Fingerprint.__dataclass_fields__
                          if len({getattr(fp, f) for fp in fps if getattr(fp, f) is not None}) > 1})
        if varying:
            high = any(f in EMBEDDING_FIELDS for f in varying)
            return _finding(
                IssueType.PIPELINE_DRIFT, Severity.HIGH if high else Severity.MEDIUM, key,
                "Chunks of one document were built with different pipeline configs",
                "Live vectors of this document disagree on: " + ", ".join(varying) + ".",
                {**base_ev, "varying_fields": varying,
                 "fingerprints": [ix.fp_objs[k].to_dict() for k in ix.fp_live]}, Action.REINDEX_FULL,
            )
    return None


def _check_metadata(
    key: DocKey, s: SourceDoc, m: ManifestRow | None, ix: DocIndexState, base_ev: dict, is_stale: bool, live: int,
    explained_count: bool = False,
) -> Finding | None:
    problems: list[dict[str, Any]] = []

    if ix.missing_fields:
        problems.append({
            "code": "missing_payload_fields", "severity": "medium",
            "message": "Vector payloads lack required fields: "
                       + ", ".join(f"{f} ({n} points)" for f, n in sorted(ix.missing_fields.items())),
        })
    if m is None and live > 0 and not is_stale:
        problems.append({
            "code": "untracked_in_manifest", "severity": "medium",
            "message": "Vectors exist for a current document but the pipeline has no manifest row for it.",
        })
    if m is not None and not is_stale:
        live_chunks = sum(len(v) for v in ix.live_chunks().values())
        if m.indexed_chunk_count is not None and live and not explained_count and m.indexed_chunk_count != live_chunks:
            problems.append({
                "code": "manifest_count_mismatch", "severity": "medium",
                "message": f"Manifest says {m.indexed_chunk_count} chunks indexed, the index holds {live_chunks}.",
            })
        if m.acl_hash and ix.acl:
            bad = {a: n for a, n in ix.acl.items() if a != m.acl_hash}
            if bad:
                problems.append({
                    "code": "acl_mismatch", "severity": "high",
                    "message": f"{sum(bad.values())} vectors carry a different ACL than the manifest "
                               "(permissions may be wrong at query time).",
                })
        if live and m.source_hash and s.source_hash and m.source_hash != s.source_hash:
            problems.append({
                "code": "manifest_lags_index", "severity": "low",
                "message": "The index is current but the manifest still records an older source hash.",
            })
        if m.indexed_version and s.source_version and m.indexed_version != s.source_version and live \
                and not (m.source_hash and s.source_hash and m.source_hash != s.source_hash):
            problems.append({
                "code": "manifest_version_mismatch", "severity": "low",
                "message": f"Manifest indexed_version {m.indexed_version} differs from the source version "
                           f"{s.source_version} although content hashes agree.",
            })
        if _norm(m.processing_status) in FAILED_STATUSES and live and not ix.missing_fields:
            problems.append({
                "code": "status_failed_but_indexed", "severity": "low",
                "message": f"Manifest status is '{m.processing_status}' although the document is indexed.",
            })

    if not problems:
        return None
    sev = max_severity([p["severity"] for p in problems]) or "low"
    action = Action.FIX_METADATA
    return _finding(
        IssueType.METADATA_INCONSISTENT, Severity(sev), key, "Metadata disagrees between systems",
        "; ".join(p["message"] for p in problems), {**base_ev, "problems": problems}, action,
    )


# ---------------------------------------------------------------------------------------------- #
def _collection_checks(agg: IndexAggregator, cfg: ReconcileConfig) -> list[Finding]:
    out: list[Finding] = []
    for coll, (count, samples) in sorted(agg.unattributed.items()):
        out.append(_finding(
            IssueType.METADATA_INCONSISTENT, Severity.HIGH, ("*", "*"),
            "Vectors without a document id",
            f"{count} point(s) in collection '{coll}' carry no document id, so they cannot be reconciled "
            "with any source document.",
            {"collection": coll, "points": count, "sample_point_ids": samples,
             "problems": [{"code": "unattributed_vectors", "severity": "high", "message": "no document_id in payload"}]},
            Action.INVESTIGATE, collection=coll,
        ))
    target_dim = cfg.target.embedding_dim if cfg.target else None
    if target_dim:
        for coll, size in sorted(cfg.vector_sizes.items()):
            if size and size != target_dim:
                out.append(_finding(
                    IssueType.PIPELINE_DRIFT, Severity.CRITICAL, ("*", "*"),
                    "Collection vector size does not match the target embedding model",
                    f"Collection '{coll}' stores {size}-dimensional vectors but the target embedding model "
                    f"produces {target_dim}. Queries embedded with the target model cannot match this collection.",
                    {"collection": coll, "collection_vector_size": size, "target_embedding_dim": target_dim},
                    Action.INVESTIGATE, collection=coll,
                ))
    return out


# ---------------------------------------------------------------------------------------------- #
def _summarize(
    key: DocKey, s: SourceDoc | None, m: ManifestRow | None, ix: DocIndexState | None,
    findings: list[Finding], pending: bool,
) -> DocSummary:
    sevs = [f.severity.value for f in findings]
    worst = max_severity(sevs)
    if pending and not findings:
        status = "pending"
    elif s is None and ix and ix.point_count:
        status = "orphaned"
    elif worst in ("critical", "high"):
        status = "broken"
    elif worst in ("medium", "low", "info"):
        status = "degraded"
    else:
        status = "healthy"

    fp: Fingerprint | None = None
    if ix and ix.fp_all:
        counter = ix.fp_live or ix.fp_all
        fp = ix.fp_objs[counter.most_common(1)[0][0]]
    if fp is None and m is not None:
        fp = m.fingerprint
    elif fp is not None and m is not None:
        fp = fp.fill_from(m.fingerprint)

    return DocSummary(
        tenant_id=key[0], document_id=key[1], status=status,
        issue_types=sorted({f.type.value for f in findings}), worst_severity=worst,
        source_present=s is not None, manifest_present=m is not None, index_present=bool(ix and ix.point_count),
        source_uri=(s.source_uri if s else (m.source_uri if m else None)),
        source_hash=s.source_hash if s else None, source_version=s.source_version if s else None,
        size_bytes=s.size_bytes if s else 0,
        fingerprint=fp.to_dict() if fp else {},
        expected_chunks=m.expected_chunk_count if m else None,
        indexed_chunks=sum(len(v) for v in ix.live_chunks().values()) if ix else 0,
        manifest_status=m.processing_status if m else None,
        manifest_updated_at=m.updated_at if m else None,
        collections=sorted(ix.collections) if ix else [],
        # what the index really holds beats what the manifest claims; the claim is the fallback when payloads carry no version
        indexed_version=(ix.versions.most_common(1)[0][0] if ix and ix.versions else (m.indexed_version if m else None)),
    )


def refresh_after_escalation(result: ReconcileResult) -> None:
    """Severities can change after reconciliation (a confirmed retrieval probe escalates a finding).
    Bring per-document status and the run statistics back in line with the final findings."""
    sev_by_doc: dict[DocKey, list[str]] = defaultdict(list)
    for f in result.findings:
        sev_by_doc[f.key].append(f.severity.value)
    for s in result.summaries:
        sevs = sev_by_doc.get(s.key)
        if not sevs:
            continue
        s.worst_severity = max_severity(sevs)
        if s.status not in ("pending", "orphaned"):
            s.status = "broken" if s.worst_severity in ("critical", "high") else "degraded"
    result.stats.update(_derived_stats(result))


def _derived_stats(result: ReconcileResult) -> dict[str, Any]:
    by_status = Counter(s.status for s in result.summaries)
    by_type = Counter(f.type.value for f in result.findings)
    by_sev = Counter(f.severity.value for f in result.findings)
    total = len(result.summaries)
    healthy = by_status.get("healthy", 0) + by_status.get("pending", 0)
    return {
        "documents_total": total,
        "documents_by_status": dict(by_status),
        "findings_total": len(result.findings),
        "findings_by_type": dict(by_type),
        "findings_by_severity": {k: by_sev.get(k, 0) for k in sorted(SEVERITY_RANK, key=lambda x: -SEVERITY_RANK[x])},
        "health_score": round(100.0 * healthy / total, 1) if total else 100.0,
    }


def _stats(result: ReconcileResult, source: dict, manifest: dict, agg: IndexAggregator) -> dict[str, Any]:
    return {
        "source_documents": len(source),
        "manifest_rows": len(manifest),
        "index_points": agg.points_seen,
        **_derived_stats(result),
    }
