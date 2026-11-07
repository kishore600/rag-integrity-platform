"""Document-level integrity report: exactly which documents are inconsistent, and why."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .models import SEVERITY_RANK


def build_report(ledger, *, include_healthy: bool = False, tenant: str | None = None) -> dict[str, Any]:
    docs, _ = ledger.list_documents(limit=1_000_000, tenant=tenant)
    open_issues = ledger.open_issues()
    by_doc: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for i in open_issues:
        by_doc[(i["tenant_id"], i["document_id"])].append(i)
    rows = []
    for d in docs:
        iss = by_doc.get((d["tenant_id"], d["document_id"]), [])
        if not iss and not include_healthy:
            continue
        rows.append({
            "tenant_id": d["tenant_id"], "document_id": d["document_id"], "status": d["status"],
            "worst_severity": d["worst_severity"], "source_uri": d["source_uri"], "last_verified_at": d["last_verified_at"],
            "expected_chunks": d["expected_chunks"], "indexed_chunks": d["indexed_chunks"],
            "issues": [{"id": i["id"], "type": i["type"], "severity": i["severity"], "title": i["title"],
                        "detail": i["detail"], "action": i["action"]}
                       for i in sorted(iss, key=lambda i: -SEVERITY_RANK[i["severity"]])],
        })
    # collection-level issues have no document row
    collection_issues = [i for i in open_issues if i["document_id"] == "*"]
    counts = ledger.document_counts()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {"documents": counts["total"], "by_status": counts["by_status"], "health_score": counts["health_score"],
                    "open_issues": ledger.issue_counts()},
        "collection_issues": [{"id": i["id"], "type": i["type"], "severity": i["severity"], "title": i["title"],
                               "detail": i["detail"]} for i in collection_issues],
        "documents": rows,
    }


def to_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    out = ["# RAG integrity report", "", f"Generated {report['generated_at']}", "",
           f"- Documents checked: **{s['documents']}**", f"- Health score: **{s['health_score']}%**",
           f"- Open issues: **{s['open_issues']['open']}** "
           + ", ".join(f"{k}: {v}" for k, v in s["open_issues"]["by_severity"].items() if v), ""]
    if report["collection_issues"]:
        out += ["## Collection-level issues", ""]
        out += [f"- **{i['severity'].upper()}** {i['title']} - {i['detail']}" for i in report["collection_issues"]]
        out.append("")
    out += ["## Inconsistent documents", ""]
    if not report["documents"]:
        out.append("None. The index agrees with the source.")
    for d in report["documents"]:
        out.append(f"### `{d['tenant_id']}/{d['document_id']}` - {d['status']}")
        out.append(f"Chunks: {d['indexed_chunks']} indexed / {d['expected_chunks'] if d['expected_chunks'] is not None else '?'} expected. "
                   f"Source: {d['source_uri'] or 'gone'}")
        out += [f"- **{i['severity'].upper()}** `{i['type']}` - {i['detail']} (fix: `{i['action']}`)" for i in d["issues"]]
        out.append("")
    return "\n".join(out)


def to_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tenant_id", "document_id", "status", "severity", "issue_type", "recommended_action", "detail",
                "indexed_chunks", "expected_chunks", "source_uri"])
    for d in report["documents"]:
        for i in d["issues"] or [{"severity": "", "type": "", "action": "", "detail": ""}]:
            w.writerow([d["tenant_id"], d["document_id"], d["status"], i["severity"], i["type"], i["action"], i["detail"],
                        d["indexed_chunks"], d["expected_chunks"], d["source_uri"]])
    return buf.getvalue()
