"""What to tell people when an audit finishes, and what they can do about it: a notification in the app and an email.

Both are made from the same content. Every notification carries *actions*: the next step, as a button in the app (and a link in
the email). An action is either a ``link`` (open a page of the app) or a ``post`` (do something through the API, for example
resume an audit that stopped part-way). Actions only ever name pages and endpoints of this application; the browser runs a
``post`` through the same signed-in session as any other click, so a notification can never do anything its reader could not.

Nothing here can fail an audit: ``announce`` catches everything and reports what happened in plain words.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from . import alerts, mailer
from .config import Settings
from .ledger import Ledger, RunDiff, utcnow
from .security import scrub

log = logging.getLogger("ragintegrity.notifications")

SEVERITIES = ("critical", "high", "medium", "low", "info")
SILENT_TRIGGERS = frozenset({"bootstrap", "repair-verify", "cleanup-prep"})  # steps inside something else: the result is shown there
DELETION_TYPES = ("orphan_vector", "tenant_mismatch")  # open issues of these types say vectors remain for a deleted document
EMAILS_PER_HOUR = 12  # per workspace: a loop of API-started audits cannot become a flood of email
EMAIL_WHEN = ("always", "attention", "never")
PRODUCT = "RAGGuard"
# the only endpoints a "post" action may call, and what each does (the app's buttons rely on this list)
POST_TARGETS = {"/api/audits": "start or resume an audit", "/api/deletion-check": "check that deleted documents are really gone"}
TOO_LARGE = "too_large_for_one_go"  # a whole-index read that ran out of the host's time limit: the audit's `failure.kind`


def too_large_steps(source_only: bool) -> list[str]:
    """What a person does about an index too big to read within the host's time limit, in plain words and in order."""
    index = ("Step 1: Ask whoever runs your Qdrant to add a keyword index on the field that holds the document ID "
             "(without it, every piece of the audit reads the whole index).")
    if source_only:
        return [index,
                "Step 2: If that index is already there, the pieces are too big for the time limit: ask the operator of this RAGGuard "
                "to lower the piece size (RAGI_AUDIT_SLICE_DOCUMENTS).",
                "Step 3: Run the audit again and keep the page open."]
    return [index,
            "Step 2: Open Settings, then Policy, and turn on 'Only audit documents found in the source (S3)'. The audit then runs in "
            "small pieces and saves after each one.",
            "Step 3: Run the audit again and keep the page open. It carries on by itself until it is done.",
            "Or, if you run RAGGuard yourself: start `ragi worker` on a server. It has no time limit and needs neither step 1 nor step 2."]


@dataclass
class Notification:
    kind: str  # audit_completed | audit_partial | audit_failed
    tone: str  # success | info | warning | critical
    title: str
    body: str
    details: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    attention: bool = False  # the kind of result an "email only when it matters" setting still sends


def action(id: str, label: str, kind: str, target: str, *, body: dict[str, Any] | None = None, primary: bool = False) -> dict[str, Any]:
    assert kind in ("link", "post")
    assert kind == "link" and target.startswith("/") or kind == "post" and target in POST_TARGETS, target
    out: dict[str, Any] = {"id": id, "label": label, "kind": kind, "target": target, "primary": primary}
    if body is not None:
        out["body"] = body
    return out


def _n(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _counts_sentence(diff: dict[str, Any]) -> str:
    parts = [(_n(diff.get("opened")), "new"), (_n(diff.get("reopened")), "came back"), (_n(diff.get("escalated")), "got worse")]
    said = [f"{n:,} {word}" for n, word in parts if n]
    fixed = _n(diff.get("resolved"))
    if not said and not fixed:
        return "Nothing changed since the last audit."
    text = ("Since the last audit: " + ", ".join(said)) if said else "Since the last audit: nothing new"
    return text + (f"; {fixed:,} fixed." if fixed else ".")


def compose(*, run_id: str, kind: str, trigger: str, status: str, stats: dict[str, Any], diff: RunDiff | None,
            error: str | None = None) -> Notification | None:
    """The notification for a finished audit (status completed, partial or failed), or None for a step inside something else."""
    if trigger in SILENT_TRIGGERS or kind == "verify":
        return None
    run_link = action("open_run", "See the run", "link", f"/audit-history/{run_id}")
    if status == "failed":
        reason = scrub(error or "the audit could not finish", 300)
        failure = stats.get("failure") or {}
        if failure.get("kind") == TOO_LARGE:  # running it again would fail the same way: say what to change instead
            source_only, paused = bool(failure.get("source_only")), bool(failure.get("paused"))
            read = re.search(r"after ([\d,]+) items", reason)
            body = (f"The audit ran out of time while reading your vector index{f' (after {read.group(1)} items)' if read else ''}: "
                    "it is too big to read in one go here. "
                    + ("Running it again would fail the same way, so the audit is paused until you change the setup below."
                       if paused else "Running it again will not help until the setup changes."))
            first = (action("open_connections", "Check connections", "link", "/data-sources", primary=True) if source_only
                     else action("open_policy", "Open audit policy settings", "link", "/settings?tab=policy", primary=True))
            return Notification(
                "audit_failed", "critical",
                ("Audit paused" if paused else "Audit failed") + ": your index is too big to read in one go", body,
                details=too_large_steps(source_only), actions=[first, run_link], attention=True)
        return Notification(
            "audit_failed", "critical", "Audit failed", f"{reason} Run it again, or check that your connections still work.",
            actions=[action("run_audit", "Run it again", "post", "/api/audits", body={}, primary=True),
                     action("open_connections", "Check connections", "link", "/data-sources"), run_link],
            attention=True)
    scan = stats.get("scan") or {}
    by_sev = {k: _n(v) for k, v in (stats.get("findings_by_severity") or {}).items()}
    by_type = stats.get("findings_by_type") or {}
    total = _n(stats.get("findings_total"))
    counts = diff.to_json() if diff is not None else (stats.get("diff") or {})
    if status == "partial":
        done, of = scan.get("documents_done"), scan.get("documents_total")
        title = f"Audit stopped part-way: {_n(done):,} of {_n(of):,} documents checked" if of else "Audit stopped part-way"
        why = scrub(str(scan.get("stopped_because") or "the scan was interrupted"), 200)
        acts = [action("resume_audit", "Resume audit", "post", "/api/audits", body={"resume": True}, primary=True)]
        if by_sev.get("critical") or by_sev.get("high"):
            acts.append(action("review_issues", "Review the issues found so far", "link",
                               "/issues?severity=" + ("critical" if by_sev.get("critical") else "high")))
        acts.append(run_link)
        return Notification(
            "audit_partial", "warning", title,
            f"Why it stopped: {why}. What it checked is reported; the rest is not, so nothing is claimed about it. "
            "Resume it to continue from where it stopped.", details=[_counts_sentence(counts)] if total else [],
            actions=acts, attention=True)
    # completed
    docs, health = _n(stats.get("documents_total")), stats.get("health_score")
    head = f"Checked {_plural(docs, 'document')}" + (f". Health score {health}%." if health is not None else ".")
    if total == 0:
        return Notification("audit_completed", "success", "Audit complete: no integrity issues", head,
                            details=[_counts_sentence(counts)], actions=[run_link])
    parts = [f"{by_sev[s]:,} {s}" for s in SEVERITIES if by_sev.get(s)][:3]
    title = "Audit complete: " + (", ".join(parts) + (" issues" if parts else f"{total:,} issues"))
    tone = "critical" if by_sev.get("critical") else "warning" if by_sev.get("high") else "info"
    worst = "critical" if by_sev.get("critical") else "high" if by_sev.get("high") else None
    acts = [action("review_issues", f"Review {worst} issues" if worst else "Review the issues", "link", "/issues?severity=" + worst if worst else "/issues",
                   primary=True)]
    if any(_n(by_type.get(t)) for t in DELETION_TYPES):
        acts.append(action("verify_deletions", "Verify deletions", "post", "/api/deletion-check", body={}))
    acts.append(run_link)
    return Notification("audit_completed", tone, title, f"{head} {_plural(total, 'open issue')}.", details=[_counts_sentence(counts)],
                        actions=acts, attention=False)


def highlights(diff: RunDiff | None, limit: int = 5) -> list[str]:
    """The newest and worst issues, one line each (ids only: no document contents ever reach a notification)."""
    if diff is None:
        return []
    fresh = [*diff.opened, *diff.reopened, *diff.escalated]
    fresh.sort(key=lambda f: SEVERITIES.index(f.severity.value) if f.severity.value in SEVERITIES else 9)
    seen: set[str] = set()
    out: list[str] = []
    for f in fresh:
        if f.issue_id in seen:
            continue
        seen.add(f.issue_id)
        out.append(f"[{f.severity.value.upper()}] {f.title}: {f.tenant_id}/{f.document_id}")
        if len(out) == limit:
            break
    return out


# ---------------------------------------------------------------------------------------------------- the email
def _url(base: str | None, target: str) -> str | None:
    return f"{base}{target}" if base else None


def email_actions(n: Notification, base: str | None) -> list[tuple[str, str | None, bool]]:
    """(label, address, primary). A button that does something (resume, verify) cannot be one click in an email: mail scanners
    open links, and a link must never change anything. It points to the notification page, where the button is."""
    out = []
    for a in n.actions:
        target = a["target"] if a["kind"] == "link" else "/notifications"
        out.append((a["label"], _url(base, target), bool(a.get("primary"))))
    return out


def render_email(n: Notification, base: str | None) -> tuple[str, str, str]:
    """(subject, plain text, html). Everything that came from data is escaped before it reaches the HTML."""
    subject = f"[{PRODUCT}] {n.title}"
    acts = email_actions(n, base)
    lines = [n.title, "", n.body, *([""] + [f"- {d}" for d in n.details] if n.details else [])]
    if acts:
        lines += ["", "What to do next:"]
        lines += [f"- {label}: {url}" if url else f"- {label} (open {PRODUCT} to do this)" for label, url, _ in acts]
    settings_url = _url(base, "/alerts")
    lines += ["", "You get this email because an audit finished in your " + PRODUCT + " workspace."
              + (f" Change when you get it: {settings_url}" if settings_url else " Change it under Alerts in the app.")]
    text = "\n".join(lines)

    e = html_lib.escape
    tone = {"success": "#0a7d33", "info": "#2b5fd9", "warning": "#b45309", "critical": "#b42318"}.get(n.tone, "#2b5fd9")
    buttons = "".join(
        (f'<a href="{e(url, quote=True)}" style="display:inline-block;margin:0 8px 8px 0;padding:10px 16px;border-radius:8px;'
         f'text-decoration:none;font-weight:600;font-size:14px;'
         + ("background:#5b3fd6;color:#ffffff;" if primary else "background:#f1eefb;color:#3b2a99;") + f'">{e(label)}</a>')
        if url else f'<span style="display:inline-block;margin:0 8px 8px 0;color:#555;font-size:14px;">{e(label)}</span>'
        for label, url, primary in acts)
    detail_html = "".join(f"<li>{e(d)}</li>" for d in n.details)
    html = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:0 auto;color:#1c1c28;">'
        f'<p style="margin:0 0 4px;font-size:12px;letter-spacing:.04em;color:#6b6b80;">{e(PRODUCT.upper())}</p>'
        f'<h1 style="margin:0 0 12px;font-size:20px;color:{tone};">{e(n.title)}</h1>'
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.5;">{e(n.body)}</p>'
        + (f'<ul style="margin:0 0 16px;padding-left:20px;font-size:14px;line-height:1.5;">{detail_html}</ul>' if detail_html else "")
        + (f'<p style="margin:16px 0 8px;font-size:13px;color:#6b6b80;">What to do next</p><div>{buttons}</div>' if buttons else "")
        + '<p style="margin:24px 0 0;font-size:12px;color:#6b6b80;">You get this email because an audit finished in your '
        + e(PRODUCT) + " workspace."
        + (f' <a href="{e(settings_url, quote=True)}" style="color:#6b6b80;">Change when you get it</a>.' if settings_url else " Change it under Alerts in the app.")
        + "</p></div>")
    return subject, text, html


# ---------------------------------------------------------------------------------------------------- the test email
TEST_EMAILS = 5  # per 10 minutes, per process (the hosted app also limits per workspace)
TEST_WINDOW_SECONDS = 600


def test_notification() -> Notification:
    """The message of the "Send test email" button: it says what it is, so nobody mistakes it for an audit result."""
    return Notification(
        "test", "success", "This is a test email from RAGGuard",
        "If you can read this, RAGGuard can email you after each audit. Nothing was found or changed: this message was sent only because "
        "someone pressed Send test email on the Alerts page.",
        details=["It was sent with the mail account the operator of this RAGGuard set up.",
                 "After an audit finishes you get a message like this one with the next step as buttons."],
        actions=[action("open_alerts", "Open Alert settings", "link", "/alerts")])


def send_test_email(settings: Settings, ledger: Ledger) -> dict[str, Any]:
    """Send one test message to the people an alert would go to, and say in plain words what happened. Never raises."""
    if not mailer.configured(settings):
        return {"ok": False, "sent": 0, "to": [],
                "reason": "No mail account is set up on this deployment. The operator sets RAGI_SMTP_HOST and RAGI_SMTP_FROM "
                          "(and RAGI_SMTP_USER, RAGI_SMTP_PASSWORD) in the server's environment."}
    try:
        to = _recipients(settings, ledger)
    except Exception as exc:
        log.warning("could not read the recipients of the test email: %s", type(exc).__name__)
        return {"ok": False, "sent": 0, "to": [], "reason": "The addresses to send it to could not be read."}
    good = [a for a in to if mailer.valid_address(a)]
    if not good:
        return {"ok": False, "sent": 0, "to": [], "reason": "There is no address to send it to. In single-user mode set RAGI_ALERT_EMAIL_TO."}
    subject, text, html = render_email(test_notification(), settings.link_base)
    result = mailer.send(settings, good, subject, text, html)
    out: dict[str, Any] = {"ok": bool(result["sent"]) and not result["failed"], "sent": result["sent"], "to": good}
    if result["error"]:
        out["reason"] = f"The mail server did not accept it: {result['error']}"
    return out


# ---------------------------------------------------------------------------------------------------- delivery
def _recipients(settings: Settings, ledger: Ledger) -> list[str]:
    own = ledger.workspace_emails()  # app mode: the workspace's own users. Nobody else can ever be a recipient there.
    if own:
        return own
    return [a.strip() for a in (settings.alert_email_to or "").split(",") if a.strip()]


def _wants_email(settings: Settings, n: Notification, run_id: str, diff: RunDiff | None, stats: dict[str, Any]) -> tuple[bool, str]:
    when = (settings.alert_email_when or "always").lower()
    if when not in EMAIL_WHEN:
        when = "always"
    if when == "never":
        return False, "email is switched off for this workspace (Alerts > Email me)"
    if when == "attention" and not n.attention:
        fresh = diff is not None and alerts.build_message(settings, run_id, diff, stats) is not None
        if not fresh:
            return False, "nothing needed attention, and this workspace only gets email when something does"
    return True, ""


def announce(settings: Settings, ledger: Ledger, *, run_id: str, kind: str, trigger: str, status: str, stats: dict[str, Any],
             diff: RunDiff | None, error: str | None = None) -> dict[str, Any]:
    """Record the notification in the app and email it. Always returns a small report and never raises."""
    report: dict[str, Any] = {"in_app": None, "email": {"sent": 0}}
    try:
        n = compose(run_id=run_id, kind=kind, trigger=trigger, status=status, stats=stats, diff=diff, error=error)
        if n is None:
            return {"skipped": "a step inside another action: its result is shown there"}
        n.details = [*n.details, *highlights(diff)][:8]
    except Exception as exc:
        log.warning("could not compose the notification for %s: %s", run_id, type(exc).__name__)
        return {"in_app": None, "email": {"sent": 0}, "error": f"{type(exc).__name__}: could not compose the notification"}
    nid: str | None = None
    try:
        nid = ledger.add_notification(kind=n.kind, tone=n.tone, title=n.title, body=n.body, run_id=run_id, actions=n.actions, details=n.details)
        report["in_app"] = nid
    except Exception as exc:  # for example a database that has not been migrated yet: the audit result must still be saved
        log.warning("could not save the notification for %s: %s", run_id, type(exc).__name__)
        report["in_app_error"] = f"{type(exc).__name__}: the notification could not be saved"
    try:
        report["email"] = _email(settings, ledger, n, nid, run_id, diff, stats)
    except Exception as exc:
        log.warning("could not email the notification for %s: %s", run_id, type(exc).__name__)
        report["email"] = {"sent": 0, "reason": f"{type(exc).__name__}: could not send the email"}
    return report


def _email(settings: Settings, ledger: Ledger, n: Notification, nid: str | None, run_id: str, diff: RunDiff | None,
           stats: dict[str, Any]) -> dict[str, Any]:
    wanted, why = _wants_email(settings, n, run_id, diff, stats)
    if not wanted:
        return {"sent": 0, "reason": why}
    if not mailer.configured(settings):
        return {"sent": 0, "reason": "no mail server is configured on this deployment (the operator sets RAGI_SMTP_HOST and RAGI_SMTP_FROM)"}
    to = _recipients(settings, ledger)
    if not to:
        return {"sent": 0, "reason": "there is no address to send it to"}
    try:
        recent = ledger.notification_emails_since(utcnow() - timedelta(hours=1))
    except Exception as exc:  # fail closed: when the limit cannot be checked, no email goes out
        log.warning("could not check the hourly email limit: %s", type(exc).__name__)
        return {"sent": 0, "reason": "the hourly email limit could not be checked, so no email was sent"}
    if recent >= EMAILS_PER_HOUR:
        return {"sent": 0, "reason": f"already sent {EMAILS_PER_HOUR} emails in the last hour for this workspace"}
    subject, text, html = render_email(n, settings.link_base)
    result = mailer.send(settings, to, subject, text, html)
    if result["sent"] and nid:
        ledger.mark_notification_emailed(nid)
    out: dict[str, Any] = {"sent": result["sent"], "to": len(to)}
    if result["error"]:
        out["error"] = result["error"]
    return out
