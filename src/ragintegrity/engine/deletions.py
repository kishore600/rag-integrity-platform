"""Deletion and retrieval verification: a document was deleted from the source. Is it really gone from the index and from search?

The failure this catches: a confidential file is deleted from S3, its vectors stay in the vector index, and a user's search
still returns its text. For each deleted document the check answers, with evidence:

    Source document       Deleted
    Manifest status       success        (the pipeline still believes it is indexed)
    Vector chunks found   12
    Retrieval test        3 matching chunks returned

and recommends what to do (review the remaining vectors, run an approved cleanup through the customer's own ingestion pipeline).
Read-only: it looks in the source, the manifest and the index, and queries the index with the stored vectors of a few chunks.
It never deletes anything; removal is the repair workflow's job and needs approval.

Which documents count as deleted: a document an earlier audit saw in the source that is gone now, a document the manifest marks
deleted, or a document the caller names. A manifest row that merely has no file in this source (another source) is not a deletion.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any

from ..connectors.base import IndexConnector, ManifestConnector, SourceConnector
from ..ids import normalize_id
from ..models import DocKey, Finding, IssueType, Scope, Severity
from .audit import AuditOptions, _config, collect
from .index_state import DocIndexState
from .reconcile import DELETED_STATUSES, ReconcileResult, _norm, reconcile, refresh_after_escalation

PROBES_PER_DOCUMENT = 3
TOP_K = 10

VERDICTS = {
    "verified_deleted": "Verified deleted",
    "deletion_mismatch": "Deletion mismatch",
    "manifest_not_updated": "Manifest not updated",
    "not_deleted": "Still in the source",
}


def retrieval_test(index: IndexConnector, key: DocKey, st: DocIndexState, probes: int = PROBES_PER_DOCUMENT,
                   top_k: int = TOP_K) -> dict[str, Any]:
    """Query the live index with the stored vectors of a few of the document's own chunks (filtered to its tenant, as a real
    query is) and count how many of the document's chunks come back. It proves the content is searchable, not user traffic."""
    points = st.points_of(*st.classes) if st else {}
    coll = next((c for c, ids in points.items() if ids), None)
    if coll is None:
        return {"run": False, "reachable": False, "returned_chunks": 0, "queries": 0, "best_rank": None,
                "note": "no vectors to query with"}
    ids = points[coll]
    step = max(1, len(ids) // probes)
    chosen = ids[::step][:probes]
    returned: set[str] = set()
    best: int | None = None
    top: list[dict[str, Any]] = []
    queries = errors = 0
    last_error = ""
    for pid in chosen:
        try:
            hits = index.probe(coll, pid, key[0], top_k)
        except Exception as exc:  # a failed probe is reported, never raised: the check goes on
            errors += 1
            last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            continue
        if hits is None:  # the point's vector could not be read
            continue
        queries += 1
        for rank, (point_id, _score, doc) in enumerate(hits, 1):
            if doc is not None and normalize_id(doc) == key[1]:
                returned.add(point_id)
                best = rank if best is None else min(best, rank)
        if not top:
            top = [{"rank": i + 1, "document_id": h[2], "score": round(h[1], 4),
                    "is_deleted_content": h[2] is not None and normalize_id(h[2]) == key[1]} for i, h in enumerate(hits[:5])]
    out: dict[str, Any] = {"run": queries > 0, "reachable": bool(returned), "returned_chunks": len(returned), "queries": queries,
                           "best_rank": best, "top_k": top_k, "tenant_filter": key[0], "results": top,
                           "method": f"queries by the stored vectors of up to {probes} of the document's own chunks, filtered to its tenant"}
    if errors:
        out["errors"] = errors
        out["note"] = last_error
    return out


def _row(key: DocKey, reason: str, c: Any, findings: list[Finding], probes: int, top_k: int, index: IndexConnector) -> dict[str, Any]:
    s, m, st = c.source.get(key), c.manifest.get(key), c.agg.states.get(key)
    vectors = st.point_count if st else 0
    status = m.processing_status if m else None
    test = retrieval_test(index, key, st, probes, top_k) if (s is None and vectors and st) else None
    if s is not None:
        verdict = "not_deleted"
    elif vectors:
        verdict = "deletion_mismatch"
    elif m is not None and _norm(m.processing_status) not in DELETED_STATUSES:
        verdict = "manifest_not_updated"
    else:
        verdict = "verified_deleted"

    checks = [
        {"check": "Source document", "result": "Still in the source" if s else "Deleted", "status": "mismatch" if s else "ok"},
        {"check": "Manifest status", "result": status if m else ("no manifest row" if c.has_manifest else "no manifest connected"),
         "status": "ok" if (m is None or _norm(status) in DELETED_STATUSES) else "mismatch"},
        {"check": "Vector chunks found", "result": vectors, "status": "mismatch" if vectors and not s else "ok"},
    ]
    if test is None:
        checks.append({"check": "Retrieval test", "result": "not run: " + ("the document still exists" if s else "no vectors remain"),
                       "status": "ok" if not s else "unknown"})
    elif not test["run"]:
        checks.append({"check": "Retrieval test", "result": "could not be run" + (f" ({test.get('note')})" if test.get("note") else ""),
                       "status": "unknown"})
    elif test["reachable"]:
        checks.append({"check": "Retrieval test", "result": f"{test['returned_chunks']} matching chunk(s) returned (best rank {test['best_rank']})",
                       "status": "mismatch"})
    else:
        checks.append({"check": "Retrieval test", "result": f"not returned in the top {test['top_k']} of {test['queries']} queries", "status": "ok"})

    action = {
        "deletion_mismatch": (f"Review the {vectors} remaining vector(s) and run an approved cleanup through your ingestion pipeline "
                              "(create a repair plan from the audit's issue; nothing is deleted until you approve it)."),
        "manifest_not_updated": "The vectors are gone. Mark the document deleted (or remove its row) in the processing manifest.",
        "not_deleted": "The document still exists in the source. If it should be deleted, delete it there first.",
        "verified_deleted": ("Nothing to do: the document is gone from the source, the manifest and the index." if c.has_manifest
                             else "Nothing to do: the document is gone from the source and the index."),
    }[verdict]
    return {
        "tenant_id": key[0], "document_id": key[1], "reason": reason, "verdict": verdict, "title": VERDICTS[verdict],
        "source_present": s is not None, "manifest_status": status, "vectors": vectors, "collections": sorted(st.collections) if st else [],
        "retrieval": test, "checks": checks, "recommended_action": action,
        "issue_types": sorted({f.type.value for f in findings if f.key == key}),
    }


def verify_deletions(
    source: SourceConnector, manifest: ManifestConnector, index: IndexConnector, opts: AuditOptions,
    candidates: dict[DocKey, str], *, probes_per_document: int = PROBES_PER_DOCUMENT, top_k: int = TOP_K,
) -> tuple[dict[str, Any], ReconcileResult, Scope]:
    """Verify the deletion of each candidate document (``{(tenant, document): why it is a candidate}``).

    Returns the report, the reconciliation result for those documents (findings escalated by what the retrieval test proved,
    so the caller can record them) and the scope it covers (so recording resolves issues only inside it)."""
    scope = Scope(keys=frozenset(candidates))
    plain = dataclasses.replace(opts, source_only=False, prior_source_keys=None, probe=False)
    c = collect(source, manifest, index, plain, scope)
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, plain, c.required, c.has_manifest), scope)
    rows = [_row(key, reason, c, result.findings, probes_per_document, top_k, index) for key, reason in sorted(candidates.items())]

    by_key = {r["tenant_id"] + "\0" + r["document_id"]: r for r in rows}
    for f in result.findings:  # what the retrieval test proved belongs on the issue too
        r = by_key.get(f.tenant_id + "\0" + f.document_id)
        if r is None or r["retrieval"] is None:
            continue
        f.evidence["deletion_verification"] = {"checks": r["checks"], "verdict": r["verdict"]}
        f.evidence["retrieval_probe"] = {k: v for k, v in r["retrieval"].items() if k != "run"}
        if r["retrieval"]["reachable"] and f.type == IssueType.ORPHAN_VECTOR and f.severity != Severity.CRITICAL:
            f.severity = Severity.CRITICAL
            f.detail += (f" Confirmed: {r['retrieval']['returned_chunks']} of its chunks are returned by a search "
                         f"(best rank {r['retrieval']['best_rank']}).")
    refresh_after_escalation(result)

    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "documents_checked": len(rows), **counts,
            "vectors_remaining": sum(r["vectors"] for r in rows if r["verdict"] == "deletion_mismatch"),
            "retrievable": sum(1 for r in rows if r["retrieval"] and r["retrieval"]["reachable"]),
        },
        "documents": rows,
        "limits": [f"The retrieval test queries the index with the stored vectors of up to {probes_per_document} of a document's chunks, "
                   "filtered to its tenant. It proves the content can be returned and how it ranks; it does not replay real user queries."],
    }
    return report, result, scope
