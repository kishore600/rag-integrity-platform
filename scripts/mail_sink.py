"""A mail catcher for the practice lab and the tests: it accepts every email and shows it in a web page instead of delivering it.

    python scripts/mail_sink.py                  # SMTP on 1025, web page on http://localhost:8025

It speaks just enough SMTP for RAGGuard (and any normal mail library): no sign-in, no encryption, never forwards anything. Mail is
kept in memory only, so restarting it empties the inbox. Standard library only, so it runs in the lab's image with nothing to install.
"""

from __future__ import annotations

import argparse
import email
import socketserver
import threading
from datetime import datetime, timezone
from email import policy
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_MESSAGE_BYTES = 25_000_000
MAX_MESSAGES = 200


class Inbox:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def add(self, mail_from: str, rcpt_to: list[str], raw: bytes) -> int:
        with self._lock:
            mid = (self.messages[-1]["id"] + 1) if self.messages else 1
            self.messages.append({"id": mid, "at": datetime.now(timezone.utc), "from": mail_from, "to": list(rcpt_to), "raw": raw})
            del self.messages[:-MAX_MESSAGES]
            return mid

    def get(self, mid: int) -> dict[str, Any] | None:
        with self._lock:
            return next((m for m in self.messages if m["id"] == mid), None)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.messages)


INBOX = Inbox()


class SmtpHandler(socketserver.StreamRequestHandler):
    """The few SMTP commands a sender needs. Anything else gets 502, which real clients treat as 'not supported'."""

    inbox = INBOX
    timeout = 30

    def reply(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        self.reply("220 lab-mail ready (the RAGGuard practice lab mail catcher)")
        mail_from, rcpt_to = "", []
        try:
            while True:
                line = self.rfile.readline(2048)
                if not line:
                    return
                cmd = line.decode("utf-8", "replace").strip()
                verb = cmd.split(" ", 1)[0].upper()
                if verb in ("EHLO", "HELO"):
                    self.reply("250-lab-mail")
                    self.reply(f"250-SIZE {MAX_MESSAGE_BYTES}")
                    self.reply("250 8BITMIME")
                elif verb == "MAIL":
                    mail_from, rcpt_to = cmd[10:].strip().split(" ")[0].strip("<>"), []
                    self.reply("250 ok")
                elif verb == "RCPT":
                    rcpt_to.append(cmd[8:].strip().split(" ")[0].strip("<>"))
                    self.reply("250 ok")
                elif verb == "DATA":
                    if not rcpt_to:
                        self.reply("503 need a recipient first")
                        continue
                    self.reply("354 end with <CRLF>.<CRLF>")
                    raw = self._read_data()
                    if raw is None:
                        self.reply("552 message too large")
                        return
                    mid = self.inbox.add(mail_from, rcpt_to, raw)
                    self.reply(f"250 ok, caught as message {mid}")
                    mail_from, rcpt_to = "", []
                elif verb == "RSET":
                    mail_from, rcpt_to = "", []
                    self.reply("250 ok")
                elif verb == "NOOP":
                    self.reply("250 ok")
                elif verb == "QUIT":
                    self.reply("221 bye")
                    return
                else:
                    self.reply("502 not supported by the lab mail catcher")
        except (ConnectionError, TimeoutError, OSError):
            return

    def _read_data(self) -> bytes | None:
        chunks, size = [], 0
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return b"".join(chunks)
            if line in (b".\r\n", b".\n"):
                return b"".join(chunks)
            if line.startswith(b".."):  # dot-stuffing
                line = line[1:]
            size += len(line)
            if size > MAX_MESSAGE_BYTES:
                return None
            chunks.append(line)


class ThreadedSmtp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ------------------------------------------------------------------------------------------------ the web page
def _parts(raw: bytes) -> tuple[email.message.EmailMessage, list[Any]]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    return msg, list(msg.iter_attachments())  # type: ignore[arg-type]


PAGE = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Lab mail</title>"
        "<style>body{font:15px/1.5 system-ui,Arial,sans-serif;margin:24px auto;max-width:880px;padding:0 16px;color:#0f172a}"
        "a{color:#4338ca}table{border-collapse:collapse;width:100%}td,th{padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:left}"
        "iframe{width:100%;height:520px;border:1px solid #cbd5e1;border-radius:8px}.m{color:#64748b;font-size:13px}</style>")


class Web(BaseHTTPRequestHandler):
    inbox = INBOX

    def log_message(self, *_a: Any) -> None:
        pass

    def send(self, body: bytes, ctype: str = "text/html; charset=utf-8", status: int = 200, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]
        if path == "/":
            rows = "".join(
                f"<tr><td>{m['id']}</td><td class=m>{m['at']:%Y-%m-%d %H:%M:%S} UTC</td><td>{escape(', '.join(m['to']))}</td>"
                f"<td><a href='/mail/{m['id']}'>{escape(str(email.message_from_bytes(m['raw'], policy=policy.default)['Subject'] or '(no subject)'))}</a></td></tr>"
                for m in reversed(self.inbox.all()))
            body = (f"{PAGE}<h1>Lab mail catcher</h1><p class=m>Every email the lab sends lands here and goes nowhere else. "
                    f"{len(self.inbox.all())} message(s). <a href='/'>Refresh</a></p>"
                    f"<table><tr><th>#</th><th>Received</th><th>To</th><th>Subject</th></tr>{rows or '<tr><td colspan=4>Nothing yet.</td></tr>'}</table>")
            return self.send(body.encode())
        if len(parts) >= 2 and parts[0] in ("mail", "raw", "body") and parts[1].isdigit():
            m = self.inbox.get(int(parts[1]))
            if m is None:
                return self.send(b"No such message.", "text/plain", 404)
            msg, attachments = _parts(m["raw"])
            if parts[0] == "raw":
                return self.send(m["raw"], "message/rfc822", extra={"Content-Disposition": f'attachment; filename="mail-{m["id"]}.eml"'})
            if parts[0] == "body":
                html = msg.get_body(preferencelist=("html", "plain"))
                text = html.get_content() if html is not None else ""
                ctype = "text/html; charset=utf-8" if html is not None and html.get_content_type() == "text/html" else "text/plain; charset=utf-8"
                return self.send(str(text).encode(), ctype)
            if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) < len(attachments):
                a = attachments[int(parts[2])]
                return self.send(a.get_payload(decode=True) or b"", a.get_content_type(),
                                 extra={"Content-Disposition": f'attachment; filename="{a.get_filename() or "attachment"}"'})
            links = "".join(f"<li><a href='/mail/{m['id']}/{i}'>{escape(a.get_filename() or 'attachment')}</a> "
                            f"<span class=m>({a.get_content_type()}, {len(a.get_payload(decode=True) or b'')} bytes)</span></li>"
                            for i, a in enumerate(attachments))
            body = (f"{PAGE}<p><a href='/'>&larr; All mail</a> &middot; <a href='/raw/{m['id']}'>Download .eml</a></p>"
                    f"<h2>{escape(str(msg['Subject'] or ''))}</h2><p class=m>From {escape(str(msg['From']))} to {escape(str(msg['To']))}</p>"
                    f"<h3>Attachments</h3><ul>{links or '<li>None</li>'}</ul><iframe src='/body/{m['id']}' sandbox></iframe>")
            return self.send(body.encode())
        self.send(b"Not found.", "text/plain", 404)


def serve(host: str = "0.0.0.0", smtp_port: int = 1025, http_port: int = 8025) -> tuple[ThreadedSmtp, ThreadingHTTPServer]:
    smtp = ThreadedSmtp((host, smtp_port), SmtpHandler)
    web = ThreadingHTTPServer((host, http_port), Web)
    for server in (smtp, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return smtp, web


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--smtp-port", type=int, default=1025)
    ap.add_argument("--http-port", type=int, default=8025)
    args = ap.parse_args()
    serve(args.host, args.smtp_port, args.http_port)
    print(f"Lab mail catcher: SMTP on {args.smtp_port}, web page on port {args.http_port}", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
