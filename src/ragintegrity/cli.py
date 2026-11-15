"""``ragi`` command line: serve the dashboard, run audits (cron/CI friendly), print reports."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .models import SEVERITY_RANK, Scope

SEV_ORDER = sorted(SEVERITY_RANK, key=lambda s: -SEVERITY_RANK[s])


def _service():
    from .service import IntegrityService

    return IntegrityService()


def _print_summary(stats: dict[str, Any], run_id: str | None = None) -> None:
    sev = stats.get("findings_by_severity", {})
    print(f"  documents checked : {stats.get('documents_total')}")
    print(f"  health score      : {stats.get('health_score')}%")
    print("  findings          : " + (", ".join(f"{k}={v}" for k, v in sev.items() if v) or "none"))
    for typ, n in sorted(stats.get("findings_by_type", {}).items(), key=lambda kv: -kv[1]):
        print(f"      {typ:<24}{n}")
    diff = stats.get("diff")
    if diff:
        print(f"  since last run    : {diff['opened']} opened, {diff['reopened']} reopened, {diff['resolved']} resolved")
    if run_id:
        print(f"  run id            : {run_id}")


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    if args.demo:
        os.environ["RAGI_MODE"] = "demo"
    elif args.app:
        os.environ["RAGI_MODE"] = "app"
    print(f"RAG Integrity dashboard -> http://{args.host}:{args.port}")
    uvicorn.run("ragintegrity.api.main:app", host=args.host, port=args.port, log_level="info")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    os.environ["RAGI_MODE"] = "demo"
    svc = _service()
    svc.demo_reset(seed=args.seed, audit=False)
    svc.bootstrap()
    run = svc.ledger.list_runs(limit=1)[0]
    print("Demo world audited (synthetic corpus with injected faults):")
    _print_summary(run["stats"], run["id"])
    print("\nStart the dashboard with:  ragi serve --demo")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    svc = _service()
    svc.bootstrap()
    scope = Scope(tenant=args.tenant) if args.tenant else None
    result = svc.run_audit(scope=scope, trigger="cli", probe=not args.no_probe, resume=args.resume)
    if args.json:
        print(json.dumps({"run_id": result.run_id, "status": result.status, "stats": result.stats}, indent=2, default=str))
    else:
        print("Audit complete:" if result.status == "completed" else "Audit PARTIAL (the scan stopped part-way):")
        _print_summary(result.stats, result.run_id)
        scan = result.stats.get("scan") or {}
        if scan.get("status") == "partial":
            print(f"  checked           : {scan.get('documents_done')} of {scan.get('documents_total')} documents "
                  f"({scan.get('percent')}%); the rest is NOT reported")
            print(f"  stopped because   : {scan.get('stopped_because')}")
            print("  next step         : run `ragi audit --resume` to continue from the last checkpoint")
    if result.status == "partial":
        return 3
    if args.fail_on:
        floor = SEVERITY_RANK[args.fail_on]
        bad = [f for f in svc.ledger.open_issues() if SEVERITY_RANK[f["severity"]] >= floor]
        if bad:
            print(f"\nFAIL: {len(bad)} open issue(s) at or above '{args.fail_on}'", file=sys.stderr)
            return 2
    return 0


def cmd_verify_deletions(args: argparse.Namespace) -> int:
    svc = _service()
    docs = []
    for ref in args.document or []:
        tenant, _, doc = ref.partition("/") if "/" in ref and args.tenant is None else (args.tenant or svc.settings.default_tenant, "", ref)
        docs.append((tenant, doc))
    report = svc.verify_deletions(docs or None, record=not args.no_record)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        s = report["summary"]
        if not s["documents_checked"]:
            print(report.get("note", "Nothing to verify."))
        for d in report["documents"]:
            print(f"{d['title'].upper():<22}{d['tenant_id']}/{d['document_id']}  ({d['reason']})")
            for chk in d["checks"]:
                print(f"    {chk['check']:<22}{chk['result']}")
            if d["verdict"] != "verified_deleted":
                print(f"    -> {d['recommended_action']}")
        print(f"\n{s['documents_checked']} document(s) checked: {s['verified_deleted']} verified deleted, "
              f"{s['deletion_mismatch']} with vectors remaining ({s['retrievable']} retrievable), "
              f"{s['manifest_not_updated']} manifest not updated, {s['not_deleted']} still in the source")
    return 1 if report["summary"]["deletion_mismatch"] else 0


def cmd_issues(args: argparse.Namespace) -> int:
    svc = _service()
    rows, total = svc.ledger.list_issues(status=args.status, severity=args.severity, type=args.type, tenant=args.tenant,
                                         limit=args.limit)
    for r in rows:
        print(f"{r['severity'].upper():<9}{r['type']:<22}{r['tenant_id']}/{r['document_id']}  - {r['title']}")
    print(f"\n{len(rows)} of {total} issue(s)")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    svc = _service()
    out = svc.report(args.format, include_healthy=args.all)
    text = json.dumps(out, indent=2, default=str) if args.format == "json" else out
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


def cmd_connections(_: argparse.Namespace) -> int:
    svc = _service()
    ok = True
    for c in svc.connections():
        ok &= c["ok"]
        print(f"[{'OK' if c['ok'] else 'FAIL':<4}] {c['name']:<24} {c['detail']}")
    return 0 if ok else 1


def cmd_setup_check(args: argparse.Namespace) -> int:
    from .engine.coverage import to_text

    report = _service().setup_check()
    print(json.dumps(report, indent=2, default=str) if args.json else to_text(report))
    return 1 if report["status"] == "not_ready" else 0


def cmd_init_db(_: argparse.Namespace) -> int:
    svc = _service()
    ok, detail = svc.ledger.ping()
    print(("ledger ready: " if ok else "ledger NOT reachable: ") + detail)
    return 0 if ok else 1


def cmd_users(args: argparse.Namespace) -> int:
    """Operator tools for the multi-user app (RAGI_DATABASE_URL and RAGI_SECRET_KEY must be set)."""
    from .accounts import Accounts
    from .config import get_settings
    from .ledger import Ledger
    from .security import Vault

    s = get_settings()
    ledger = Ledger(s.database_url)
    ledger.init()
    accounts = Accounts(ledger, Vault(s.secret_key) if s.secret_key else None)
    if args.action == "delete":
        if not args.yes:
            print(f"This permanently deletes {args.email} and EVERYTHING in their workspace (issues, documents, settings, keys).")
            print("Re-run with --yes to confirm.")
            return 2
        print("deleted" if accounts.delete_user(args.email) else "no such user")
    else:
        u = ledger.t["users"]
        from sqlalchemy import select

        with ledger.engine.connect() as c:
            for r in c.execute(select(u.c.email, u.c.created_at, u.c.last_login_at).order_by(u.c.created_at)):
                print(f"{r[0]:<40} created {r[1]:%Y-%m-%d}  last login {r[2] or '-'}")
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    svc = _service()
    if args.action == "plan":
        plan = svc.repairs.create_plan(min_severity=args.min_severity, tenant=args.tenant)
    elif args.action == "trigger":
        plan = svc.repairs.trigger(args.plan_id)
    elif args.action == "verify":
        plan = svc.repairs.verify(args.plan_id)
    else:
        plan = svc.repairs.approve_cleanup(args.plan_id)
    s = plan["summary"]
    print(f"plan {plan['id']}  status={plan['status']}")
    print(f"  documents to reprocess: {s['documents_to_reprocess']}  chunks: {s['chunks_to_regenerate']}  "
          f"est. cost: ${s['estimated_cost_usd']}  (saves {s['savings_vs_full_reindex_pct']}% vs full reindex)")
    for it in plan["items"][:20]:
        print(f"  {it['status']:<17}{it['tenant_id']}/{it['document_id']}  {','.join(it['actions']) or 'cleanup'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ragi", description="Know when your RAG index is wrong - before your users do.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the API and dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--demo", action="store_true", help="use the built-in synthetic world")
    s.add_argument("--app", action="store_true", help="multi-user mode: sign-up / login, each workspace connects its own infrastructure")
    s.set_defaults(fn=cmd_serve)

    d = sub.add_parser("demo", help="seed the demo world and audit it")
    d.add_argument("--seed", type=int, default=7)
    d.set_defaults(fn=cmd_demo)

    a = sub.add_parser("audit", help="run an audit now (suitable for cron / CI)")
    a.add_argument("--tenant")
    a.add_argument("--no-probe", action="store_true", help="skip retrieval probes")
    a.add_argument("--resume", action="store_true", help="continue the last interrupted (partial) audit from its checkpoint; exits 3 when an audit ends partial")
    a.add_argument("--json", action="store_true")
    a.add_argument("--fail-on", choices=SEV_ORDER, help="exit 2 if open issues at/above this severity remain")
    a.set_defaults(fn=cmd_audit)

    i = sub.add_parser("issues", help="list issues from the ledger")
    i.add_argument("--status", default="open", choices=["open", "resolved", "ignored", "all"])
    i.add_argument("--severity", choices=SEV_ORDER)
    i.add_argument("--type")
    i.add_argument("--tenant")
    i.add_argument("--limit", type=int, default=50)
    i.set_defaults(fn=cmd_issues)

    r = sub.add_parser("report", help="document-level integrity report")
    r.add_argument("--format", choices=["md", "json", "csv"], default="md")
    r.add_argument("--all", action="store_true", help="include healthy documents")
    r.add_argument("-o", "--output")
    r.set_defaults(fn=cmd_report)

    c = sub.add_parser("connections", help="test connectivity to S3, the manifest database, Qdrant and the ledger")
    c.set_defaults(fn=cmd_connections)

    vd = sub.add_parser("verify-deletions", help="were deleted documents really removed from the index, and can a search still return them? (read-only; exits 1 when vectors remain)")
    vd.add_argument("--document", action="append", metavar="ID", help="also verify this document (repeatable; TENANT/ID or, with --tenant, just the id)")
    vd.add_argument("--tenant", help="the tenant of the --document ids that have none")
    vd.add_argument("--no-record", action="store_true", help="look only: do not write the findings to the issue list")
    vd.add_argument("--json", action="store_true")
    vd.set_defaults(fn=cmd_verify_deletions)

    sc = sub.add_parser("setup-check", help="check that S3, the manifest and Qdrant use the same document IDs (read-only, takes seconds)")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(fn=cmd_setup_check)

    init = sub.add_parser("init-db", help="create the ledger tables (idempotent) and check connectivity")
    init.set_defaults(fn=cmd_init_db)

    us = sub.add_parser("users", help="list or delete users of the multi-user app")
    us.add_argument("action", choices=["list", "delete"])
    us.add_argument("email", nargs="?")
    us.add_argument("--yes", action="store_true", help="confirm a delete")
    us.set_defaults(fn=cmd_users)

    rp = sub.add_parser("repair", help="plan / trigger / verify / approve-cleanup")
    rp.add_argument("action", choices=["plan", "trigger", "verify", "approve-cleanup"])
    rp.add_argument("plan_id", nargs="?")
    rp.add_argument("--min-severity", choices=SEV_ORDER)
    rp.add_argument("--tenant")
    rp.set_defaults(fn=cmd_repair)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "repair" and args.action != "plan" and not args.plan_id:
        print("plan_id is required", file=sys.stderr)
        return 2
    if args.cmd == "users" and args.action == "delete" and not args.email:
        print("an email is required", file=sys.stderr)
        return 2
    try:
        return args.fn(args)
    except Exception as exc:  # friendly CLI errors; the full traceback is one RAGI_DEBUG away
        if os.environ.get("RAGI_DEBUG"):
            raise
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
