"""`ragguard`: check that your RAG index matches your source documents, from a terminal, a CI job or an AI assistant.

    ragguard check --fail-on high   run an audit, wait for it, print the result; exit 1 if open issues are at or above "high"
    ragguard status                 the latest results, without running an audit
    ragguard issues [--severity S]  open issues, most severe first
    ragguard issue ISSUE_ID         one issue with its evidence and the recommended fix
    ragguard document DOCUMENT_ID   everything RAGGuard knows about one document
    ragguard report                 the full report as Markdown
    ragguard mcp                    run the MCP server for AI assistants (also: uvx ragguard-cli mcp)

Set RAGGUARD_API_KEY (create a key on the Integrations page of RAGGuard). RAGGUARD_URL defaults to the hosted service.
Exit codes: 0 fine, 1 open issues at or above --fail-on, 2 an error (bad key, unreachable server, failed audit).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .client import SEVERITIES, RagGuard, RagGuardError, worst_open


def _count_line(by_severity: dict[str, int]) -> str:
    parts = [f"{sev} {by_severity[sev]}" for sev in SEVERITIES if by_severity.get(sev)]
    return ", ".join(parts) if parts else "none"


def _issue_line(i: dict[str, Any]) -> str:
    where = f"{i.get('tenant_id')}/{i.get('document_id')}" if i.get("tenant_id") not in (None, "", "default") else i.get("document_id")
    return f"  [{i.get('severity')}] {i.get('title')}  ({where})  id={i.get('id')}"


def _print_status(ov: dict[str, Any]) -> None:
    docs, issues = ov.get("documents", {}), ov.get("issues", {})
    score = docs.get("health_score")
    print(f"  health score   : {'-' if score is None else f'{score}%'}")
    print(f"  documents      : {docs.get('total', 0):,}")
    print(f"  open issues    : {issues.get('open', 0):,} ({_count_line(issues.get('by_severity', {}))})")
    run = ov.get("latest_run")
    if run:
        print(f"  latest audit   : {run.get('status')} at {run.get('finished_at') or run.get('started_at')}")


def cmd_check(rg: RagGuard, args: argparse.Namespace) -> int:
    progress = None if args.json else (lambda msg: print(f"... {msg}", file=sys.stderr))
    run = rg.run_audit(timeout=args.timeout, on_progress=progress)
    if run["status"] == "failed":
        print(f"The audit failed: {run.get('error') or 'no reason given'}", file=sys.stderr)
        return 2
    ov = rg.status()
    open_issues = rg.issues(limit=args.top)["items"] if args.top else []
    over = worst_open(ov.get("issues", {}).get("by_severity", {}), args.fail_on)
    if args.json:
        print(json.dumps({"run": run, "overview": {k: ov.get(k) for k in ("documents", "issues")}, "open_issues": open_issues,
                          "at_or_above_fail_on": over}, indent=2, default=str))
    else:
        stats = run.get("stats") or {}
        dur = stats.get("duration_seconds")
        print(f"RAGGuard audit {run['id'][:8]}: {run['status']}" + (f" in {dur:.1f} s" if isinstance(dur, (int, float)) else ""))
        _print_status(ov)
        if open_issues:
            print("Open issues, most severe first:")
            for i in open_issues:
                print(_issue_line(i))
        if run["status"] == "partial":
            print("This audit stopped part-way; the numbers cover the documents it reached.")
        print(f"Open issues at or above {args.fail_on!r}: {over}")
    return 1 if over else 0


def cmd_status(rg: RagGuard, args: argparse.Namespace) -> int:
    ov = rg.status()
    if args.json:
        print(json.dumps({k: ov.get(k) for k in ("documents", "issues", "latest_run")}, indent=2, default=str))
    else:
        print("RAGGuard status")
        _print_status(ov)
    return 0


def cmd_issues(rg: RagGuard, args: argparse.Namespace) -> int:
    out = rg.issues(severity=args.severity, limit=args.limit)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"{out['total']} open issue(s)" + (f" of severity {args.severity}" if args.severity else ""))
        for i in out["items"]:
            print(_issue_line(i))
    return 0


def cmd_issue(rg: RagGuard, args: argparse.Namespace) -> int:
    i = rg.issue(args.issue_id)
    if args.json:
        print(json.dumps(i, indent=2, default=str))
        return 0
    print(f"[{i.get('severity')}] {i.get('title')}  ({i.get('status')})")
    print(f"  document : {i.get('tenant_id')}/{i.get('document_id')}")
    print(f"  what     : {i.get('detail')}")
    action = i.get("action")
    if isinstance(action, dict):
        action = action.get("summary") or action.get("kind")
    if action:
        print(f"  fix      : {str(action).replace('_', ' ')}")
    print("  evidence :")
    print("    " + json.dumps(i.get("evidence"), indent=2, default=str).replace("\n", "\n    "))
    return 0


def cmd_document(rg: RagGuard, args: argparse.Namespace) -> int:
    d = rg.document(args.document_id, tenant=args.tenant)
    if args.json:
        print(json.dumps(d, indent=2, default=str))
        return 0
    doc = d.get("document") or {}
    print(f"{doc.get('tenant_id')}/{doc.get('document_id')}: {doc.get('status')}")
    for key in ("source_uri", "source_hash", "expected_chunks", "indexed_chunks"):
        if doc.get(key) is not None:
            print(f"  {key:<15}: {doc[key]}")
    issues = d.get("issues") or []
    print(f"  issues         : {len(issues)}")
    for i in issues:
        print(_issue_line(i))
    return 0


def cmd_report(rg: RagGuard, args: argparse.Namespace) -> int:
    sys.stdout.write(rg.report(args.format))
    return 0


def cmd_mcp(_rg: RagGuard | None, _args: argparse.Namespace) -> int:
    try:
        from .mcp_server import serve
    except ImportError:
        print('The MCP server needs the "mcp" package: pip install --upgrade ragguard-cli', file=sys.stderr)
        return 2
    serve()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ragguard", description="Check that your RAG index matches your source documents (RAGGuard).")
    p.add_argument("--version", action="version", version=f"ragguard-cli {__version__}")
    p.add_argument("--url", help="the RAGGuard server (default: $RAGGUARD_URL, else the hosted service)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="run an audit and wait for the result")
    c.add_argument("--fail-on", choices=SEVERITIES, default="high", help="exit 1 when open issues are at or above this (default: high)")
    c.add_argument("--top", type=int, default=10, help="how many open issues to list (default 10, 0 for none)")
    c.add_argument("--timeout", type=float, default=1800.0, help="seconds to wait for the audit (default 1800)")
    c.add_argument("--json", action="store_true", help="print JSON instead of text")
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("status", help="the latest results, without running an audit")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    i = sub.add_parser("issues", help="open issues, most severe first")
    i.add_argument("--severity", choices=SEVERITIES)
    i.add_argument("--limit", type=int, default=50)
    i.add_argument("--json", action="store_true")
    i.set_defaults(fn=cmd_issues)

    one = sub.add_parser("issue", help="one issue with its evidence and the recommended fix")
    one.add_argument("issue_id")
    one.add_argument("--json", action="store_true")
    one.set_defaults(fn=cmd_issue)

    d = sub.add_parser("document", help="everything RAGGuard knows about one document")
    d.add_argument("document_id")
    d.add_argument("--tenant", help="the tenant, when the same ID exists for several")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_document)

    r = sub.add_parser("report", help="the full report")
    r.add_argument("--format", choices=["md", "json", "csv"], default="md")
    r.set_defaults(fn=cmd_report)

    m = sub.add_parser("mcp", help="run the MCP server over stdio, for AI assistants")
    m.set_defaults(fn=cmd_mcp)
    return p


def main(argv: list[str] | None = None, *, client: RagGuard | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "mcp":
        return cmd_mcp(None, args)
    try:
        rg = client or RagGuard(url=args.url)
        return args.fn(rg, args)
    except RagGuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
