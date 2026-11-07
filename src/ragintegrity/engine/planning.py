"""Safe reindex recommendations and repair-plan construction.

The goal is to avoid blanket re-embedding: for every affected document we compute the *smallest*
safe action, and how much work that really is compared with re-processing the whole corpus.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from ..models import CLEANUP_TYPES, SEVERITY_RANK, DocKey, IssueType

REINDEX_FULL_TYPES = {
    IssueType.MISSING_EMBEDDING.value, IssueType.STALE_EMBEDDING.value,
    IssueType.PIPELINE_DRIFT.value, IssueType.EMPTY_EMBEDDING.value,
}


def plan_items(issues: list[dict[str, Any]], docs: dict[DocKey, dict[str, Any]]) -> list[dict[str, Any]]:
    """Group open document-level issues into one repair item per document."""
    by_doc: dict[DocKey, list[dict[str, Any]]] = defaultdict(list)
    for i in issues:
        if i["document_id"] == "*":
            continue  # collection-level findings need a human; they are not document repairs
        by_doc[(i["tenant_id"], i["document_id"])].append(i)

    items: list[dict[str, Any]] = []
    for key, iss in by_doc.items():
        types = {i["type"] for i in iss}
        actions: list[str] = []
        if types & REINDEX_FULL_TYPES:
            actions.append("reindex_full")  # a full reindex rewrites chunks *and* the manifest
        elif IssueType.PARTIAL_INDEX.value in types:
            actions.append("reindex_chunks")
        if IssueType.METADATA_INCONSISTENT.value in types and "reindex_full" not in actions:
            actions.append("fix_metadata")
        cleanup_issues = [i for i in iss if i["type"] in CLEANUP_TYPES]
        doc = docs.get(key) or {}
        missing = sum(int(i["evidence"].get("missing_count", 0)) for i in iss if i["type"] == IssueType.PARTIAL_INDEX.value)
        worst = max((i["severity"] for i in iss), key=lambda s: SEVERITY_RANK[s])
        items.append({
            "tenant_id": key[0], "document_id": key[1], "actions": actions,
            "cleanup": bool(cleanup_issues), "cleanup_vectors": sum(int(i["evidence"].get("removal_count", 0)) for i in cleanup_issues),
            "issue_ids": [i["id"] for i in iss], "issue_types": sorted(types), "worst_severity": worst,
            "source_uri": doc.get("source_uri"), "source_hash": doc.get("source_hash"), "source_version": doc.get("source_version"),
            "expected_chunk_count": doc.get("expected_chunks"), "missing_count": missing,
            "missing_chunks": [c for i in iss if i["type"] == IssueType.PARTIAL_INDEX.value
                               for c in i["evidence"].get("missing_chunks", [])][:50],
            "collections": doc.get("collections") or [], "size_bytes": doc.get("size_bytes") or 0,
            "status": "planned", "checks": {}, "remaining_types": [],
        })
    items.sort(key=lambda it: (-SEVERITY_RANK[it["worst_severity"]], it["tenant_id"], it["document_id"]))
    return items


def _doc_chunks(doc: dict[str, Any], chunk_tokens: int) -> int:
    n = doc.get("expected_chunks") or doc.get("indexed_chunks")
    if n:
        return int(n)
    size = doc.get("size_bytes") or 0
    return max(1, math.ceil(size / 4 / max(1, chunk_tokens))) if size else 1  # ~4 bytes per token


def estimate_workload(
    items: list[dict[str, Any]], docs: dict[DocKey, dict[str, Any]], all_docs: list[dict[str, Any]] | None,
    *, chunk_tokens: int, price_per_mtok: float,
) -> dict[str, Any]:
    """What the repair costs, and what a blanket re-embed of the whole corpus would have cost."""
    chunks = 0
    for it in items:
        key = (it["tenant_id"], it["document_id"])
        if "reindex_full" in it["actions"]:
            chunks += _doc_chunks(docs.get(key) or {"size_bytes": it.get("size_bytes")}, chunk_tokens)
        elif "reindex_chunks" in it["actions"]:
            chunks += max(1, it.get("missing_count", 0))
    tokens = chunks * chunk_tokens
    reprocess = [it for it in items if it["actions"] and any(a.startswith("reindex") for a in it["actions"])]

    corpus_chunks = sum(_doc_chunks(d, chunk_tokens) for d in (all_docs or []) if d.get("source_present", 1))
    corpus_tokens = corpus_chunks * chunk_tokens
    by_tenant: dict[str, dict[str, int]] = defaultdict(lambda: {"documents": 0, "chunks": 0})
    for it in reprocess:
        key = (it["tenant_id"], it["document_id"])
        n = _doc_chunks(docs.get(key) or {}, chunk_tokens) if "reindex_full" in it["actions"] else max(1, it.get("missing_count", 0))
        by_tenant[it["tenant_id"]]["documents"] += 1
        by_tenant[it["tenant_id"]]["chunks"] += n

    def cost(t: int) -> float:
        return round(t / 1_000_000 * price_per_mtok, 4)

    return {
        "documents_affected": len(items),
        "documents_to_reprocess": len(reprocess),
        "full_reindex_documents": sum("reindex_full" in it["actions"] for it in items),
        "chunk_reindex_documents": sum("reindex_chunks" in it["actions"] for it in items),
        "metadata_fix_documents": sum("fix_metadata" in it["actions"] for it in items),
        "cleanup_documents": sum(1 for it in items if it["cleanup"]),
        "vectors_to_remove": sum(it["cleanup_vectors"] for it in items),
        "chunks_to_regenerate": chunks,
        "embeddings_to_update": chunks,
        "estimated_tokens": tokens,
        "estimated_cost_usd": cost(tokens),
        "collections_affected": sorted({c for it in items for c in it["collections"]}),
        "tenants_affected": sorted({it["tenant_id"] for it in items}),
        "by_tenant": [{"tenant_id": t, **v} for t, v in sorted(by_tenant.items())],
        "full_corpus": {
            "documents": len(all_docs or []), "chunks": corpus_chunks, "estimated_tokens": corpus_tokens,
            "estimated_cost_usd": cost(corpus_tokens),
        },
        "savings_vs_full_reindex_pct": round(100.0 * (1 - tokens / corpus_tokens), 1) if corpus_tokens else None,
        "assumptions": f"{chunk_tokens} tokens per chunk, ${price_per_mtok}/1M tokens; chunk counts come from the "
                       "manifest, falling back to ~4 bytes/token of source size.",
    }
