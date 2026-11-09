"""Tenant isolation: can one customer's documents reach another customer's answers?

The audit already finds the two ways that happens in the index (vectors tagged with the wrong tenant, and permission
hashes that disagree with the manifest) and proves reachability with a live search. This module turns that into one answer
per tenant and for the whole index, plus a plain-language evidence report. It only reads what the audit already read.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..models import IssueType

MAX_TENANTS = 200  # listed in a stored summary (leaks first); the rest are only counted
ORDER = {"leak": 0, "attention": 1, "clean": 2, "single_tenant": 3}
OVERALL_TEXT = {
    "clean": "No document is indexed under another tenant, and the labels that keep tenants apart are present and consistent.",
    "attention": "No leak was found, but some vectors lack a tenant or permission label, or permissions disagree with the manifest.",
    "leak": "At least one document is indexed under the wrong tenant. Its content can be returned to the wrong customer.",
    "not_applicable": "Only one tenant was found, so there is nothing to keep apart. Isolation checks apply once documents belong to several tenants.",
    "limited": "The audit only read the points of documents found in the source, so wrong-tenant vectors cannot be seen. "
               "Turn off \"Only audit documents found in the source (S3)\" for a full isolation check.",
}


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def _has_acl_problem(f: Any) -> bool:
    return f.type == IssueType.METADATA_INCONSISTENT and any(
        p.get("code") == "acl_mismatch" for p in (f.evidence.get("problems") or []))


def build_summary(agg: Any, source_keys: Any, manifest: dict, result: Any, *, limited: bool = False) -> dict[str, Any]:
    """The isolation picture of one full audit. ``agg`` is the index aggregator, ``result`` the reconcile result."""
    points = agg.iso_points
    tenants = sorted({t for t, _ in source_keys} | {t for t, _ in manifest} | set(points))
    docs = Counter(s.tenant_id for s in result.summaries)
    leaks: Counter = Counter()
    acl_bad: Counter = Counter()
    confirmed = 0
    for f in result.findings:
        if f.type == IssueType.TENANT_MISMATCH:
            leaks[f.tenant_id] += 1
            if (f.evidence.get("retrieval_probe") or {}).get("reachable"):
                confirmed += 1
        elif _has_acl_problem(f):
            acl_bad[f.tenant_id] += 1

    total_points = sum(points.values())
    acl_in_use = any(points[t] > agg.iso_no_acl[t] for t in points) or any(r.acl_hash for r in manifest.values())
    multi = len(tenants) > 1

    rows = []
    for t in tenants:
        pts, no_tenant, no_acl = points[t], agg.iso_no_tenant[t], agg.iso_no_acl[t]
        if not multi:
            status = "single_tenant"
        elif leaks[t]:
            status = "leak"
        elif acl_bad[t] or no_tenant or (acl_in_use and no_acl):
            status = "attention"
        else:
            status = "clean"
        rows.append({
            "tenant_id": t, "status": status, "documents": docs[t], "points": pts,
            "tenant_label_pct": _pct(pts - no_tenant, pts),
            "permission_label_pct": _pct(pts - no_acl, pts) if acl_in_use else None,
            "foreign_documents": leaks[t],  # documents that belong to another tenant but are indexed under this one
            "permission_mismatch_documents": acl_bad[t],
        })
    rows.sort(key=lambda r: (ORDER[r["status"]], r["tenant_id"]))

    total_leaks, total_acl = sum(leaks.values()), sum(acl_bad.values())
    no_tenant_total, no_acl_total = sum(agg.iso_no_tenant.values()), sum(agg.iso_no_acl.values())
    if limited:
        overall = "limited"
    elif not multi:
        overall = "not_applicable"
    else:
        overall = "leak" if total_leaks else ("attention" if any(r["status"] == "attention" for r in rows) else "clean")

    def check(name: str, status: str, detail: str) -> dict[str, str]:
        return {"name": name, "status": status, "detail": detail}

    off = "limited" if limited else ("not_applicable" if not multi else None)
    checks = [
        check("Documents indexed under the wrong tenant",
              "na" if off else ("fail" if total_leaks else "pass"),
              "Needs a full audit." if limited else (f"{total_leaks} document(s) are indexed under a tenant they do not belong to."
                                                     if total_leaks else "None found.")),
        check("Leaks confirmed reachable by a real search",
              "na" if off or not total_leaks else ("fail" if confirmed else "pass"),
              f"{confirmed} of {total_leaks} leaked document(s) were returned by a live search as the wrong tenant."
              if total_leaks and not limited else "Nothing to confirm."),
        check("Every vector carries a tenant label",
              "na" if off else ("warn" if no_tenant_total else "pass"),
              f"{no_tenant_total:,} of {total_points:,} vectors have no tenant label." if no_tenant_total
              else f"All {total_points:,} vectors are labelled."),
        check("Permission labels agree with the manifest",
              "na" if limited or not acl_in_use else ("fail" if total_acl else "pass"),
              f"{total_acl} document(s) have vectors whose permission hash differs from the manifest." if total_acl
              else ("Permissions are not recorded in this index." if not acl_in_use else "All permission hashes agree.")),
        check("Every vector carries a permission label",
              "na" if limited or not acl_in_use else ("warn" if no_acl_total else "pass"),
              f"{no_acl_total:,} of {total_points:,} vectors have no permission hash." if no_acl_total and acl_in_use
              else ("Permissions are not recorded in this index." if not acl_in_use else "All vectors carry one.")),
    ]
    return {
        "overall": {
            "status": overall, "summary": OVERALL_TEXT[overall], "tenants": len(tenants), "points_checked": total_points,
            "leaking_documents": total_leaks, "leaks_confirmed_reachable": confirmed,
            "permission_mismatch_documents": total_acl, "permissions_recorded": acl_in_use,
            "tenant_label_pct": _pct(total_points - no_tenant_total, total_points),
            "permission_label_pct": _pct(total_points - no_acl_total, total_points) if acl_in_use else None,
        },
        "tenants": rows[:MAX_TENANTS], "tenants_total": len(rows),
        "checks": checks,
    }


def to_markdown(data: dict[str, Any]) -> str:
    """The evidence page a customer can hand to their own customers or auditors."""
    if not data.get("available"):
        return "# Tenant isolation report\n\nNo full audit has finished yet, so there is nothing to report.\n"
    o, audit = data["overall"], data["audit"]
    lines = [
        "# Tenant isolation report", "",
        f"**Result: {o['status'].replace('_', ' ').upper()}**. {o['summary']}", "",
        f"- Audit: `{audit['run_id']}` finished {audit['finished_at']}",
        f"- Tenants: {o['tenants']}; vectors checked: {o['points_checked']:,}",
        f"- Documents indexed under the wrong tenant: {o['leaking_documents']} "
        f"({o['leaks_confirmed_reachable']} confirmed reachable by a live search)",
        f"- Vectors with a tenant label: {o['tenant_label_pct']}%"
        + (f"; with a permission label: {o['permission_label_pct']}%" if o["permissions_recorded"] else "; permissions are not recorded"),
        "", "## Checks", "", "| Check | Result | Detail |", "|---|---|---|",
    ]
    lines += [f"| {c['name']} | {c['status']} | {c['detail']} |" for c in data["checks"]]
    lines += ["", "## Tenants", "", "| Tenant | Status | Documents | Vectors | Tenant label | Permission label | Foreign documents |", "|---|---|---|---|---|---|---|"]
    for t in data["tenants"]:
        perm = "n/a" if t["permission_label_pct"] is None else f"{t['permission_label_pct']}%"
        lines.append(f"| {t['tenant_id']} | {t['status'].replace('_', ' ')} | {t['documents']} | {t['points']:,} | "
                     f"{t['tenant_label_pct']}% | {perm} | {t['foreign_documents']} |")
    if data.get("findings"):
        lines += ["", "## Open findings", ""]
        lines += [f"- **{f['severity']}** {f['title']}: document `{f['document_id']}` under tenant `{f['tenant_id']}`" for f in data["findings"]]
    lines += ["", "_Generated read-only: nothing in your S3, database or vector index was changed._", ""]
    return "\n".join(lines)
