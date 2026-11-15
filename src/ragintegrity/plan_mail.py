"""Email a repair plan to the people who will fix it.

RAGGuard never changes your systems; a repair plan is a work order for your own pipeline. This module turns a plan into an email a
developer can act on without opening RAGGuard: a readable summary and table in the message itself, the full list as a CSV
(opens in Excel and Google Sheets), and the exact JSON the repair webhook would receive.

It speaks plain SMTP, through one of two mail accounts (see ``account``):
* a workspace's own **Email** settings (app mode): the user's own mail server or SMTP relay, stored like every other credential
  (encrypted, never shown again). The platform's mail account is never used for this, so nobody can send mail to strangers from the
  platform's address;
* in single-user modes (live, demo) the deployment's own mail account, ``RAGI_SMTP_*``, the one that also sends the audit alerts.

Nothing is sent unless a person presses **Email plan** and types the recipients; there is no automatic or scheduled mail.

Safety, because this opens outbound connections on behalf of a user:
* a workspace's mail server must be public, on the usual submission ports, and encrypted (unless private hosts are allowed);
* recipients are validated (no spaces, no header tricks), at most ``MAX_RECIPIENTS`` per message;
* every user-supplied text is escaped in the HTML part and stripped of line breaks in headers;
* the password never appears in an error message.
"""

from __future__ import annotations

import csv
import io
import json
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
from typing import Any

from . import mailer
from .config import Settings
from .security import UnsafeTarget, assert_public_host

MAX_RECIPIENTS = 10
MAX_NOTE = 1000
MAX_HTML_ROWS = 40  # the message shows this many documents; the CSV has all of them
MAX_ATTACHMENT_BYTES = 8_000_000
HOSTED_PORTS = (25, 465, 587, 2525)  # when private hosts are not allowed (a hosted deployment), these are the only mail ports
SMTP_TIMEOUT_S = 20

ACTION_TEXT = {
    "reindex_full": "Re-index the whole document from the latest source",
    "reindex_chunks": "Re-embed the missing chunks",
    "fix_metadata": "Fix the metadata (no re-embedding needed)",
    "investigate": "Needs a person to look at it",
}
ISSUE_TEXT = {
    "missing_embedding": "no embeddings", "partial_index": "partly indexed", "stale_embedding": "out of date",
    "superseded_active": "old version still searchable", "orphan_vector": "deleted but still searchable",
    "duplicate_chunk": "duplicate chunks", "metadata_inconsistent": "records disagree", "pipeline_drift": "built with an old pipeline",
    "empty_embedding": "empty vectors", "tenant_mismatch": "wrong customer label", "manifest_orphan": "leftover manifest row",
}
SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


class MailError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------------------------------------ which mail account
@dataclass(frozen=True)
class Account:
    host: str
    port: int
    security: str  # starttls | ssl | none
    username: str | None
    password: str | None
    sender: str  # the From header: "a@b.c" or "Name <a@b.c>"
    own: bool  # True: a mail server the user chose (a workspace's Email settings). False: the deployment's own mail account

    @property
    def address(self) -> str:
        return parseaddr(self.sender)[1]


def account(settings: Settings, *, deployment_account: bool = True) -> Account | None:
    """The mail server a plan is sent through.

    A workspace's own Email settings win. Otherwise the deployment's mail account (``RAGI_SMTP_*``) is used, but only where
    ``deployment_account`` is true: single-user modes, where its owner is the only person who can press Email plan. In app mode
    it is false, because anyone can sign up and the platform's address must not send their mail to strangers."""
    if settings.plan_mail_host and settings.plan_mail_from:
        return Account(settings.plan_mail_host, settings.plan_mail_port, settings.plan_mail_security, settings.plan_mail_username,
                       settings.plan_mail_password, settings.plan_mail_from, own=True)
    if deployment_account and mailer.configured(settings):
        return Account(str(settings.smtp_host), settings.smtp_port, (settings.smtp_security or "starttls").lower(), settings.smtp_user,
                       settings.smtp_password, str(settings.smtp_from), own=False)
    return None


def is_configured(settings: Settings, *, deployment_account: bool = True) -> bool:
    return account(settings, deployment_account=deployment_account) is not None


def require_account(settings: Settings, *, deployment_account: bool = True) -> Account:
    acct = account(settings, deployment_account=deployment_account)
    if acct is None:
        raise MailError("Email is not set up. Add your mail server and a From address first (Integrations, Email; or RAGI_SMTP_HOST "
                        "and RAGI_SMTP_FROM).", 409)
    return acct


def guard(settings: Settings) -> None:
    """Refuse a workspace mail server a hosted deployment must not be pointed at. Raises ``UnsafeTarget``."""
    if settings.allow_private_hosts or not settings.plan_mail_host:
        return
    assert_public_host(settings.plan_mail_host, settings.plan_mail_port, False)
    if settings.plan_mail_port not in HOSTED_PORTS:
        raise UnsafeTarget(f"Mail port {settings.plan_mail_port} is not allowed here. Use one of {', '.join(map(str, HOSTED_PORTS))}.")
    if settings.plan_mail_security == "none":
        raise UnsafeTarget("An unencrypted mail connection is not allowed here. Choose starttls or ssl.")


def check_address(address: str) -> str:
    a = (address or "").strip()
    if not mailer.valid_address(a):
        raise MailError(f"'{a[:60]}' is not a valid email address.", 422)
    return a


def parse_recipients(raw: str | list[str] | None) -> list[str]:
    """Split on commas, semicolons and spaces; validate each; keep the first spelling of each address; at most MAX_RECIPIENTS."""
    parts = re.split(r"[,;\s]+", raw) if isinstance(raw, str) else [str(x) for x in (raw or [])]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        a = check_address(p)
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    if not out:
        raise MailError("Type at least one email address to send the plan to.", 422)
    if len(out) > MAX_RECIPIENTS:
        raise MailError(f"At most {MAX_RECIPIENTS} recipients per message.", 422)
    return out


# ------------------------------------------------------------------------------------------------ the plan as rows
def _what_to_do(item: dict[str, Any]) -> str:
    steps = [ACTION_TEXT.get(a, a) for a in item.get("actions") or []]
    if item.get("actions") and "reindex_chunks" in item["actions"] and item.get("missing_count"):
        steps = [f"Re-embed the {item['missing_count']} missing chunk{'s' if item['missing_count'] != 1 else ''}" if s == ACTION_TEXT["reindex_chunks"] else s
                 for s in steps]
    if item.get("cleanup"):
        n = int(item.get("cleanup_vectors") or 0)
        steps.append(f"Remove {n} leftover vector{'s' if n != 1 else ''} once the replacements are verified (needs approval)")
    return "; ".join(steps) or ACTION_TEXT["investigate"]


def plan_rows(plan: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for it in plan.get("items") or []:
        rows.append({
            "tenant_id": str(it.get("tenant_id") or ""), "document_id": str(it.get("document_id") or ""),
            "severity": str(it.get("worst_severity") or ""), "what_to_do": _what_to_do(it),
            "problems": ", ".join(ISSUE_TEXT.get(t, t.replace("_", " ")) for t in it.get("issue_types") or []),
            "vectors_to_remove": str(int(it.get("cleanup_vectors") or 0)), "source_uri": str(it.get("source_uri") or ""),
            "status": str(it.get("status") or ""),
        })
    return rows


def _csv_cell(value: str) -> str:
    """A spreadsheet runs a cell that starts with = + - @ as a formula: a document called '=HYPERLINK(...)' must stay text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def plan_csv(plan: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tenant_id", "document_id", "severity", "what_to_do", "problems", "vectors_to_remove", "source_uri", "status"])
    for r in plan_rows(plan):
        w.writerow([_csv_cell(r[k]) for k in ("tenant_id", "document_id", "severity", "what_to_do", "problems", "vectors_to_remove",
                                                "source_uri", "status")])
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ the message
def _single_line(text: str, limit: int = 200) -> str:
    return re.sub(r"[\r\n\t]+", " ", text).strip()[:limit]


def _severity_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["severity"]] = counts.get(r["severity"], 0) + 1
    return {s: counts[s] for s in SEVERITY_ORDER if s in counts}


def subject_for(plan: dict[str, Any]) -> str:
    rows = plan_rows(plan)
    n = len(rows)
    counts = _severity_counts(rows)
    worst = ", ".join(f"{c} {s}" for s, c in counts.items() if s in ("critical", "high"))
    return _single_line(f"RAGGuard repair plan: {n} document{'s' if n != 1 else ''} to fix" + (f" ({worst})" if worst else ""))


def _steps(link: str | None) -> list[str]:
    where = f"Open the plan in RAGGuard: {link}" if link else "Open the plan in RAGGuard (Integrity Issues, Repair plans)."
    return [
        "Fix the documents listed below in your pipeline. The attached JSON is exactly what RAGGuard would send to your repair worker.",
        "If your repair worker is connected to RAGGuard, press Trigger repair on the plan. If not, fix them by hand.",
        f"Then press Verify now on the plan. RAGGuard re-checks the real systems and shows what is fixed. {where}",
    ]


def build_plan_message(acct: Account, plan: dict[str, Any], recipients: list[str], *, note: str | None = None,
                       link: str | None = None, payload: dict[str, Any] | None = None) -> EmailMessage:
    rows = plan_rows(plan)
    s = plan.get("summary") or {}
    note = (note or "").strip()[:MAX_NOTE]
    msg = EmailMessage()
    msg["Subject"] = subject_for(plan)
    msg["From"] = acct.sender
    msg["To"] = ", ".join(recipients)
    msg["X-RAGGuard-Plan"] = _single_line(str(plan.get("id", "")), 64)

    counts = _severity_counts(rows)
    facts = [f"{len(rows)} document{'s' if len(rows) != 1 else ''}"]
    if counts:
        facts.append(", ".join(f"{c} {sev}" for sev, c in counts.items()))
    if s.get("chunks_to_regenerate"):
        facts.append(f"{s['chunks_to_regenerate']} chunks to regenerate (about ${s.get('estimated_cost_usd', 0)})")
    if s.get("vectors_to_remove"):
        facts.append(f"{s['vectors_to_remove']} leftover vectors to remove after approval")
    shown = rows[:MAX_HTML_ROWS]
    more = len(rows) - len(shown)

    # plain text
    lines = ["RAGGuard repair plan", "", "; ".join(facts) + ".", ""]
    if note:
        lines += ["Note from the sender:", note, ""]
    lines += ["What to do:"] + [f"  {i}. {t}" for i, t in enumerate(_steps(link), 1)] + ["", "Documents:"]
    for r in shown:
        lines.append(f"- [{r['severity'].upper()}] {r['tenant_id']}/{r['document_id']}: {r['what_to_do']} ({r['problems']})")
    if more > 0:
        lines.append(f"... and {more} more. The attached CSV lists every document.")
    msg.set_content("\n".join(lines) + "\n")

    # html
    th = "style=\"text-align:left;padding:6px 10px;border-bottom:2px solid #cbd5e1;font-size:12px;color:#475569\""
    td = "style=\"padding:6px 10px;border-bottom:1px solid #e2e8f0;font-size:13px;vertical-align:top\""
    body_rows = "".join(
        f"<tr><td {td}><b>{escape(r['severity'])}</b></td><td {td}>{escape(r['tenant_id'])}/{escape(r['document_id'])}</td>"
        f"<td {td}>{escape(r['what_to_do'])}</td><td {td}>{escape(r['problems'])}</td></tr>" for r in shown)
    steps_html = "".join(f"<li style=\"margin-bottom:4px\">{escape(t)}</li>" for t in _steps(link))
    note_html = (f"<p style=\"background:#f1f5f9;padding:10px 12px;border-radius:6px\"><b>Note from the sender:</b><br>"
                 f"{escape(note).replace(chr(10), '<br>')}</p>") if note else ""
    link_html = f"<p><a href=\"{escape(link, quote=True)}\">Open the plan in RAGGuard</a></p>" if link else ""
    more_html = f"<p style=\"color:#475569;font-size:13px\">... and {more} more. The attached CSV lists every document.</p>" if more > 0 else ""
    msg.add_alternative(
        "<div style=\"font-family:Arial,Helvetica,sans-serif;color:#0f172a;max-width:760px\">"
        "<h2 style=\"margin:0 0 6px\">RAGGuard repair plan</h2>"
        f"<p style=\"margin:0 0 14px;color:#334155\">{escape('; '.join(facts))}.</p>{note_html}"
        f"<h3 style=\"margin:16px 0 6px\">What to do</h3><ol style=\"padding-left:20px\">{steps_html}</ol>{link_html}"
        "<h3 style=\"margin:16px 0 6px\">Documents</h3>"
        f"<table style=\"border-collapse:collapse;width:100%\"><tr><th {th}>Severity</th><th {th}>Document</th><th {th}>What to do</th>"
        f"<th {th}>Problems</th></tr>{body_rows}</table>{more_html}"
        "<p style=\"color:#64748b;font-size:12px;margin-top:18px\">Sent by RAGGuard. RAGGuard never changes your systems; "
        "your own pipeline does the repair and RAGGuard then checks the result.</p></div>", subtype="html")

    # attachments: the whole list as CSV (BOM so Excel reads UTF-8), and the exact webhook payload
    short = _single_line(str(plan.get("id", "plan")), 8) or "plan"
    msg.add_attachment(("﻿" + plan_csv(plan)).encode("utf-8"), maintype="text", subtype="csv", filename=f"repair-plan-{short}.csv")
    if payload is not None:
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        if len(raw) <= MAX_ATTACHMENT_BYTES:
            msg.add_attachment(raw, maintype="application", subtype="json", filename=f"repair-plan-{short}-payload.json")
    return msg


# ------------------------------------------------------------------------------------------------ talking SMTP
def _redact(text: str, acct: Account) -> str:
    if acct.password:
        text = text.replace(acct.password, "***")
    return text[:200]


def _connect(acct: Account) -> smtplib.SMTP:
    """Open the connection, encrypt it and sign in. The caller sends or just checks, then closes."""
    ctx = ssl.create_default_context()
    smtp: smtplib.SMTP = (smtplib.SMTP_SSL(acct.host, acct.port, timeout=SMTP_TIMEOUT_S, context=ctx) if acct.security == "ssl"
                          else smtplib.SMTP(acct.host, acct.port, timeout=SMTP_TIMEOUT_S))
    try:
        smtp.ehlo()
        if acct.security == "starttls":
            smtp.starttls(context=ctx)
            smtp.ehlo()
        if acct.username and acct.password:
            smtp.login(acct.username, acct.password)
    except Exception:
        try:
            smtp.close()
        except Exception:
            pass
        raise
    return smtp


def _explain(exc: Exception, acct: Account) -> MailError:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return MailError("The mail server refused the username or password.", 502)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return MailError("The mail server refused these recipients: " + ", ".join(sorted(exc.recipients)[:5]) + ".", 502)
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return MailError("The mail server refused the From address. Use an address it lets you send from.", 502)
    if isinstance(exc, ssl.SSLError):
        return MailError(f"The secure connection to the mail server failed: {_redact(str(exc), acct)}", 502)
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return MailError(f"The mail server does not support what was asked ({_redact(str(exc), acct)}). Check the connection security setting.", 502)
    return MailError(f"Could not send the email: {type(exc).__name__}: {_redact(str(exc), acct)}", 502)


def send(acct: Account, msg: EmailMessage) -> None:
    recipients = [a.strip() for a in str(msg["To"]).split(",") if a.strip()]
    try:
        smtp = _connect(acct)
        try:
            smtp.send_message(msg, from_addr=acct.address, to_addrs=recipients)
        finally:
            try:
                smtp.quit()
            except Exception:
                smtp.close()
    except (smtplib.SMTPException, OSError) as exc:
        raise _explain(exc, acct) from exc


def diagnose(settings: Settings, *, deployment_account: bool = False) -> list[dict[str, str]]:
    """What 'Check settings' runs: connect, encrypt, sign in. No message is sent."""
    def chk(name: str, status: str, detail: str) -> dict[str, str]:
        return {"name": name, "status": status, "detail": detail}

    acct = account(settings, deployment_account=deployment_account)
    if acct is None:
        return [chk("Mail server", "fail", "Add a mail server and a From address first.")]
    try:
        guard(settings)
    except UnsafeTarget as exc:
        return [chk("Mail server", "fail", str(exc))]
    try:
        smtp = _connect(acct)
    except (smtplib.SMTPException, OSError) as exc:
        return [chk("Mail server", "fail", _explain(exc, acct).args[0])]
    out = [chk("Mail server", "ok", f"reached {acct.host}:{acct.port}"),
           chk("Encryption", "ok" if acct.security != "none" else "warn",
               {"starttls": "STARTTLS", "ssl": "SSL/TLS"}.get(acct.security, "none: the connection is not encrypted"))]
    out.append(chk("Sign in", "ok", f"signed in as {acct.username}") if acct.username and acct.password else
               chk("Sign in", "warn", "no username and password: only works for a server that accepts mail from this address without signing in"))
    try:
        smtp.quit()
    except Exception:
        smtp.close()
    return out
