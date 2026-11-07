"""Retrieval-level stale-content detection.

Having a bad vector is one thing; whether it can actually be *returned to a user* is what matters. For
orphaned / stale / superseded content we query the live index with the stored vector of one offending
chunk, scoped by the tenant filter a real query would use, and record where it ranks.

Limitation (by design, no embedding model needed): the probe stands in for "a user asks something that
matches this chunk". It proves the content is searchable and what it competes with; it does not replay
real traffic.
"""

from __future__ import annotations

from ..connectors.base import IndexConnector
from ..models import Finding, IssueType, Severity

PROBE_ORDER = (
    IssueType.TENANT_MISMATCH, IssueType.ORPHAN_VECTOR, IssueType.STALE_EMBEDDING, IssueType.SUPERSEDED_ACTIVE,
)


def probe_findings(index: IndexConnector, findings: list[Finding], *, top_k: int = 10, max_probes: int = 25) -> int:
    ranked = sorted(
        (f for f in findings if f.type in PROBE_ORDER and f.evidence.get("removal_points")),
        key=lambda f: PROBE_ORDER.index(f.type),
    )
    done = 0
    for f in ranked:
        if done >= max_probes:
            break
        points: dict[str, list[str]] = f.evidence["removal_points"]
        collection, ids = next(((c, v) for c, v in points.items() if v), (None, None))
        if collection is None or not ids:
            continue
        try:
            hits = index.probe(collection, ids[0], f.tenant_id, top_k)
        except Exception as exc:  # a probe must never fail an audit
            f.evidence["retrieval_probe"] = {"error": str(exc)[:200]}
            continue
        if hits is None:
            continue
        done += 1
        bad = {pid for v in points.values() for pid in v}
        rank = next((i + 1 for i, h in enumerate(hits) if h[0] in bad), None)
        reachable = rank is not None
        f.evidence["retrieval_probe"] = {
            "reachable": reachable,
            "rank": rank,
            "top_k": top_k,
            "score": round(hits[rank - 1][1], 4) if rank else None,
            "tenant_filter": f.tenant_id,
            "results": [
                {"rank": i + 1, "document_id": h[2], "score": round(h[1], 4), "is_stale_content": h[0] in bad}
                for i, h in enumerate(hits[:5])
            ],
            "method": "query by the stored vector of one affected chunk, filtered to the owning tenant",
        }
        if reachable:
            if f.type == IssueType.ORPHAN_VECTOR and f.severity != Severity.CRITICAL:
                f.severity = Severity.CRITICAL
                f.detail += f" Confirmed: it is returned at rank {rank} for a query matching it."
            elif f.type == IssueType.SUPERSEDED_ACTIVE and f.severity == Severity.MEDIUM:
                f.severity = Severity.HIGH
                f.detail += f" Confirmed: old content is returned at rank {rank}."
    return done
