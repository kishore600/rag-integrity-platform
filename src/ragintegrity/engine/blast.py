"""Blast-radius analysis: given a change or a failure, what is affected and what will it cost to fix?"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import DocKey, Fingerprint
from .planning import estimate_workload, plan_items
from .reconcile import parse_ts

SCENARIOS = ("open_issues", "config_change", "ingestion_failure")


def _affected_queries(queries: list[dict[str, Any]], affected: set[DocKey]) -> dict[str, Any]:
    hit = 0
    per_doc: Counter = Counter()
    for q in queries:
        tenant = q["tenant_id"]
        docs = [d for d in (q.get("retrieved_doc_ids") or []) if (tenant, d) in affected]
        if docs:
            hit += 1
            per_doc.update((tenant, d) for d in docs)
    return {
        "queries_in_window": len(queries), "affected_queries": hit,
        "affected_pct": round(100.0 * hit / len(queries), 1) if queries else None,
        "top_documents": [{"tenant_id": t, "document_id": d, "queries": n} for (t, d), n in per_doc.most_common(8)],
    }


def blast_radius(ledger, scenario: dict[str, Any], *, chunk_tokens: int, price_per_mtok: float, window_days: int = 14) -> dict[str, Any]:
    kind = scenario.get("type", "open_issues")
    if kind not in SCENARIOS:
        raise ValueError(f"scenario.type must be one of {', '.join(SCENARIOS)}")

    all_docs = list(ledger.all_documents())
    docs_by_key: dict[DocKey, dict[str, Any]] = {(d["tenant_id"], d["document_id"]): d for d in all_docs}
    confirmed: set[DocKey] = set()
    affected: dict[DocKey, dict[str, Any]] = {}
    open_issues = ledger.open_issues()
    by_doc_issues: dict[DocKey, list[dict[str, Any]]] = defaultdict(list)
    for i in open_issues:
        by_doc_issues[(i["tenant_id"], i["document_id"])].append(i)

    describe = ""
    if kind == "open_issues":
        describe = "Every document with an open integrity issue."
        for key in by_doc_issues:
            if key in docs_by_key:
                affected[key] = docs_by_key[key]
                confirmed.add(key)
    elif kind == "config_change":
        target = Fingerprint.from_dict(scenario.get("target"))
        if target.is_empty():
            raise ValueError("config_change needs scenario.target with at least one pipeline field "
                             "(e.g. {\"embedding_model\": \"text-embedding-3-large\"})")
        describe = "Documents whose indexed pipeline fingerprint differs from the proposed one: " + ", ".join(
            f"{k}={v}" for k, v in target.to_dict().items())
        for key, d in docs_by_key.items():
            if not d["source_present"]:
                continue
            fp = Fingerprint.from_dict(d.get("fingerprint"))
            diff = fp.conflicts_with(target)
            unknown = [k for k, v in target.to_dict().items() if getattr(fp, k) is None]
            if diff or unknown:
                affected[key] = {**d, "_diff": diff, "_unknown": unknown}
                if diff:
                    confirmed.add(key)
    else:  # ingestion_failure
        since = parse_ts(scenario.get("since"))
        until = parse_ts(scenario.get("until")) or datetime.now(timezone.utc)
        if since is None:
            raise ValueError("ingestion_failure needs scenario.since (ISO timestamp)")
        describe = f"Documents the pipeline processed between {since.isoformat()} and {until.isoformat()}."
        for key, d in docs_by_key.items():
            ts = parse_ts(d.get("manifest_updated_at"))
            if ts and since <= ts <= until:
                affected[key] = d
                if key in by_doc_issues:
                    confirmed.add(key)

    keys = set(affected)
    synthetic_items = []
    if kind == "open_issues":
        synthetic_items = plan_items([i for k in keys for i in by_doc_issues[k]], docs_by_key)
    else:
        for k in sorted(keys):
            d = docs_by_key[k]
            synthetic_items.append({
                "tenant_id": k[0], "document_id": k[1], "actions": ["reindex_full"], "cleanup": False,
                "cleanup_vectors": 0, "collections": d.get("collections") or [], "size_bytes": d.get("size_bytes") or 0,
                "missing_count": 0,
            })
    workload = estimate_workload(synthetic_items, docs_by_key, all_docs, chunk_tokens=chunk_tokens, price_per_mtok=price_per_mtok)

    per_tenant_total = Counter(d["tenant_id"] for d in all_docs)
    per_tenant_aff = Counter(k[0] for k in keys)
    by_type: Counter = Counter()
    for k in keys:
        for i in by_doc_issues.get(k, []):
            by_type[i["type"]] += 1

    sample = []
    for k in sorted(keys)[:25]:
        row: dict[str, Any] = {"tenant_id": k[0], "document_id": k[1], "status": affected[k]["status"],
                               "confirmed": k in confirmed}
        if "_diff" in affected[k]:
            row["differences"] = affected[k]["_diff"]
            row["unknown_fields"] = affected[k]["_unknown"]
        sample.append(row)

    queries = ledger.queries_since(window_days)
    return {
        "scenario": {"type": kind, **{k: v for k, v in scenario.items() if k != "type"}},
        "description": describe,
        "documents": {
            "affected": len(keys), "confirmed": len(confirmed), "total": len(all_docs),
            "affected_pct": round(100.0 * len(keys) / len(all_docs), 1) if all_docs else 0.0,
        },
        "tenants": [{"tenant_id": t, "affected": per_tenant_aff.get(t, 0), "total": n} for t, n in sorted(per_tenant_total.items())
                    if per_tenant_aff.get(t, 0)],
        "collections": workload["collections_affected"],
        "by_issue_type": dict(by_type),
        "queries": {**_affected_queries(queries, keys), "window_days": window_days,
                    "note": None if queries else "No query log ingested yet. POST /api/query-log to enable query impact."},
        "workload": workload,
        "sample": sample,
    }


def window_start(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
