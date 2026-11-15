"""Email delivery over SMTP: the platform's own mail account sends the audit alerts.

One account, set by the operator in the environment (``RAGI_SMTP_*``), sends every workspace's emails. A workspace can
only choose *whether* it gets them; it never supplies a mail server, a sender or a recipient (the recipients are the
addresses of the workspace's own users), so this cannot be used to send mail to anyone else.

Delivery is best effort and bounded: it never raises, waits a few seconds at most, and says in plain words why it did not send.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import Settings

log = logging.getLogger("ragintegrity.mailer")

TIMEOUT_SECONDS = 8
SECURITY_MODES = ("starttls", "ssl", "none")
# deliberately stricter than the sign-up check: no quotes, no spaces, no angle brackets, so no address can smuggle a header or a second recipient
ADDRESS = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}$")


def configured(s: Settings) -> bool:
    return bool(s.smtp_host and s.smtp_from)


def valid_address(address: str) -> bool:
    return len(address) <= 254 and bool(ADDRESS.match(address))


def build_message(settings: Settings, to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()  # raises ValueError for a header value with a line break: nothing here can inject a header
    msg["Subject"] = " ".join(subject.split())[:200]
    msg["From"] = settings.smtp_from or ""
    msg["To"] = to
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=(settings.smtp_from or "").rpartition("@")[2].strip("> ") or None)
    msg["Auto-Submitted"] = "auto-generated"  # an automatic message: auto-replies and out-of-office notices should not answer it
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _redact(settings: Settings, message: str) -> str:
    for secret in (settings.smtp_password, settings.smtp_user):
        if secret and len(secret) >= 4:
            message = message.replace(secret, "***")
    return message[:200]


def send(settings: Settings, recipients: list[str], subject: str, text: str, html: str | None = None) -> dict[str, object]:
    """Send one message to each address. Returns ``{"sent": n, "failed": n, "error": str | None}`` and never raises."""
    if not configured(settings):
        return {"sent": 0, "failed": 0, "error": "no mail server is configured (RAGI_SMTP_HOST and RAGI_SMTP_FROM)"}
    good = [r for r in dict.fromkeys(a.strip() for a in recipients) if valid_address(r)]
    if not good:
        return {"sent": 0, "failed": 0, "error": "no valid recipient address"}
    mode = (settings.smtp_security or "starttls").lower()
    if mode not in SECURITY_MODES:
        return {"sent": 0, "failed": len(good), "error": f"RAGI_SMTP_SECURITY must be one of {', '.join(SECURITY_MODES)}"}
    sent = failed = 0
    error: str | None = None
    try:
        messages = [build_message(settings, to, subject, text, html) for to in good]
        host, port = settings.smtp_host or "", settings.smtp_port
        if mode == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS)
        with server:
            if mode == "starttls":
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password or "")
            for msg in messages:
                try:
                    server.send_message(msg)
                    sent += 1
                except smtplib.SMTPRecipientsRefused as exc:
                    failed += 1
                    error = _redact(settings, f"the mail server refused {msg['To']}: {exc}")
    except Exception as exc:  # delivery must never fail an audit
        failed = len(good) - sent
        error = _redact(settings, f"{type(exc).__name__}: {exc}")
        log.warning("alert email not sent: %s", error)
    return {"sent": sent, "failed": failed, "error": error}
