"""After an audit: a notification in the app and an email, each with the next step.

What is proved here: the right words and the right actions for every way an audit can end; the email really goes out over SMTP (a real
local mail server) and only to the people it should; nothing a notification or an email does can fail an audit; notifications stay
inside their workspace; and no data reaches the HTML of an email unescaped.
"""

from __future__ import annotations

import email
import socketserver
import threading
from email import policy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ragintegrity import mailer, notifications
from ragintegrity.config import Settings
from ragintegrity.ledger import Ledger, RunDiff
from ragintegrity.notifications import POST_TARGETS, compose, render_email
from ragintegrity.workspaces import overlay
from tests.test_app_mode import make, signup
from tests.test_scan_reliability import DOCS, PointIndex, point, service, world_points


# ------------------------------------------------------------------------------------------------ a real mail server (SMTP)
class FakeSMTP:
    """A small but real SMTP server on a free local port: it speaks the protocol and keeps every message it is given."""

    def __init__(self) -> None:
        self.messages: list[email.message.EmailMessage] = []
        self.envelopes: list[tuple[str, list[str]]] = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                def say(line: str) -> None:
                    self.wfile.write((line + "\r\n").encode())
                    self.wfile.flush()

                say("220 fake ESMTP ready")
                sender, rcpts, data, body = "", [], [], False
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    if body:
                        if raw == b".\r\n":
                            outer.messages.append(email.message_from_bytes(b"".join(data), policy=policy.default))
                            outer.envelopes.append((sender, list(rcpts)))
                            body, data, rcpts = False, [], []
                            say("250 queued")
                        else:
                            data.append(raw[1:] if raw.startswith(b"..") else raw)
                        continue
                    cmd = raw.decode(errors="replace").strip()
                    up = cmd.upper()
                    if up.startswith(("EHLO", "HELO")):
                        say("250 fake")
                    elif up.startswith("MAIL FROM"):
                        sender = cmd.split(":", 1)[1].strip()
                        say("250 ok")
                    elif up.startswith("RCPT TO"):
                        rcpts.append(cmd.split(":", 1)[1].strip().strip("<>"))
                        say("250 ok")
                    elif up == "DATA":
                        body = True
                        say("354 go ahead")
                    elif up == "QUIT":
                        say("221 bye")
                        return
                    else:
                        say("250 ok")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def settings(self) -> dict:
        return {"smtp_host": "127.0.0.1", "smtp_port": self.port, "smtp_from": "RAGGuard <alerts@example.com>", "smtp_security": "none"}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def smtp():
    s = FakeSMTP()
    yield s
    s.close()


def workspace_of(settings, address):
    ledger = Ledger(settings.database_url)
    users = ledger.t["users"]
    with ledger.engine.connect() as c:
        return c.execute(select(users.c.workspace_id).where(users.c.email == address)).scalar_one()


def clean_points():
    return [point(d, k) for d in DOCS for k in range(3)]


def titles(svc):
    return [n["title"] for n in svc.ledger.list_notifications()[0]]


# ------------------------------------------------------------------------------------------------ what each result says
def diff_of(**counts) -> RunDiff:
    return RunDiff(unchanged=counts.get("unchanged", 0))


def test_a_clean_audit_says_so_and_offers_only_the_run():
    n = compose(run_id="r1", kind="full", trigger="manual", status="completed", diff=diff_of(),
                stats={"documents_total": 12, "findings_total": 0, "health_score": 100.0, "diff": {}})
    assert (n.kind, n.tone, n.title) == ("audit_completed", "success", "Audit complete: no integrity issues")
    assert "Checked 12 documents. Health score 100.0%." in n.body
    assert [a["id"] for a in n.actions] == ["open_run"] and n.actions[0]["target"] == "/audit-history/r1"


def test_issues_found_lead_with_the_worst_and_offer_review_and_verify_deletions_when_deleted_documents_are_involved():
    stats = {"documents_total": 400, "findings_total": 9, "health_score": 80.5, "findings_by_severity": {"critical": 2, "high": 3, "low": 4},
             "findings_by_type": {"orphan_vector": 2, "stale_embedding": 7}, "diff": {"opened": 3, "resolved": 1}}
    n = compose(run_id="r2", kind="full", trigger="api", status="completed", diff=None, stats=stats)
    assert n.title == "Audit complete: 2 critical, 3 high, 4 low issues" and n.tone == "critical"
    assert [a["id"] for a in n.actions] == ["review_issues", "verify_deletions", "open_run"]
    review, verify = n.actions[0], n.actions[1]
    assert review["primary"] and review["kind"] == "link" and review["target"] == "/issues?severity=critical" and review["label"] == "Review critical issues"
    assert verify["kind"] == "post" and verify["target"] == "/api/deletion-check" and verify["body"] == {}
    assert "Since the last audit: 3 new; 1 fixed." in n.details[0]
    without = compose(run_id="r2", kind="full", trigger="api", status="completed", diff=None,
                      stats={**stats, "findings_by_type": {"stale_embedding": 9}})
    assert "verify_deletions" not in [a["id"] for a in without.actions]  # no deleted document involved: no such button


def test_only_medium_and_low_issues_are_info_not_an_alarm():
    n = compose(run_id="r", kind="full", trigger="cli", status="completed", diff=None,
                stats={"findings_total": 5, "findings_by_severity": {"medium": 2, "low": 3}, "documents_total": 50})
    assert n.tone == "info" and n.title == "Audit complete: 2 medium, 3 low issues" and n.actions[0]["label"] == "Review the issues"
    assert n.actions[0]["target"] == "/issues"


def test_an_audit_that_stopped_part_way_leads_with_resume_and_says_what_is_and_is_not_reported():
    stats = {"findings_total": 3, "findings_by_severity": {"high": 1, "low": 2}, "diff": {"opened": 3},
             "scan": {"documents_done": 4000, "documents_total": 12000, "stopped_because": "the vector index did not answer: timed out"}}
    n = compose(run_id="r3", kind="full", trigger="schedule", status="partial", diff=None, stats=stats)
    assert (n.kind, n.tone, n.attention) == ("audit_partial", "warning", True)
    assert n.title == "Audit stopped part-way: 4,000 of 12,000 documents checked"
    assert "did not answer" in n.body and "the rest is not" in n.body and "Resume it" in n.body
    first = n.actions[0]
    assert first["id"] == "resume_audit" and first["kind"] == "post" and first["target"] == "/api/audits" and first["body"] == {"resume": True}
    assert first["primary"] and n.actions[1]["target"] == "/issues?severity=high"


def test_a_failed_audit_leads_with_run_it_again_and_never_shows_a_password():
    n = compose(run_id="r4", kind="full", trigger="manual", status="failed", diff=None, stats={},
                error="ConnectionError: could not connect to postgresql://admin:hunter2@db.example.com:5432/x")
    assert (n.kind, n.tone, n.attention, n.title) == ("audit_failed", "critical", True, "Audit failed")
    assert "hunter2" not in n.body and "could not connect" in n.body
    assert [a["id"] for a in n.actions] == ["run_audit", "open_connections", "open_run"]
    assert n.actions[0]["kind"] == "post" and n.actions[0]["body"] == {} and n.actions[1]["target"] == "/data-sources"


@pytest.mark.parametrize("trigger,kind", [("repair-verify", "verify"), ("cleanup-prep", "verify"), ("bootstrap", "full"), ("manual", "verify")])
def test_steps_inside_another_action_do_not_notify(trigger, kind):
    assert compose(run_id="r", kind=kind, trigger=trigger, status="completed", diff=None, stats={"findings_total": 1}) is None


def test_every_action_is_a_page_of_the_app_or_an_endpoint_on_the_allow_list():
    outcomes = [
        compose(run_id="r", kind="full", trigger="api", status=s, diff=None, error="x", stats={
            "findings_total": 4, "findings_by_severity": {"critical": 1, "high": 1, "low": 2}, "findings_by_type": {"orphan_vector": 1},
            "scan": {"documents_done": 1, "documents_total": 2}})
        for s in ("completed", "partial", "failed")]
    for n in outcomes:
        for a in n.actions:
            assert a["kind"] in ("link", "post") and a["label"] and a["id"]
            assert a["target"] in POST_TARGETS if a["kind"] == "post" else a["target"].startswith("/") and "//" not in a["target"]
    with pytest.raises(AssertionError):
        notifications.action("evil", "Go", "link", "https://evil.example.com")
    with pytest.raises(AssertionError):
        notifications.action("evil", "Go", "post", "/api/settings/s3")


# ------------------------------------------------------------------------------------------------ the email text
def test_the_email_has_the_actions_as_links_and_never_a_one_click_change():
    n = compose(run_id="r9", kind="full", trigger="api", status="partial", diff=None,
                stats={"scan": {"documents_done": 1, "documents_total": 3, "stopped_because": "timed out"}})
    subject, text, html = render_email(n, "https://ragguard.example.com")
    assert subject == "[RAGGuard] Audit stopped part-way: 1 of 3 documents checked"
    # Resume changes something, so the email points to the page where the button is; viewing a link must never do anything
    assert "Resume audit: https://ragguard.example.com/notifications" in text
    assert "See the run: https://ragguard.example.com/audit-history/r9" in text
    assert 'href="https://ragguard.example.com/notifications"' in html and "https://ragguard.example.com/alerts" in text
    assert "/api/" not in text and "/api/" not in html


def test_an_email_without_a_configured_address_has_no_links_but_still_says_what_to_do():
    n = compose(run_id="r9", kind="full", trigger="api", status="failed", diff=None, stats={}, error="boom")
    subject, text, html = render_email(n, None)
    assert "Run it again (open RAGGuard to do this)" in text and "<a " not in html


def test_everything_that_came_from_data_is_escaped_in_the_html_of_an_email():
    n = notifications.Notification("audit_completed", "info", 'Audit <script>alert(1)</script>', 'body "quoted" & <b>bold</b>',
                                   details=['[HIGH] <img src=x onerror=alert(1)>: t/<doc>'],
                                   actions=[notifications.action("open_run", 'See <run>', "link", "/audit-history/x")])
    subject, text, html = render_email(n, "https://ragguard.example.com")
    assert "<script>" not in html and "<img" not in html and "<b>bold" not in html and "<run>" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html and "&lt;img" in html


def test_a_header_cannot_be_injected_through_the_subject_or_a_recipient(smtp):
    s = Settings(_env_file=None, **smtp.settings)
    msg = mailer.build_message(s, "a@example.com", "Hello\r\nBcc: evil@example.com", "text")
    assert "\r" not in msg["Subject"] and "\n" not in msg["Subject"] and msg["Bcc"] is None
    for bad in ("a@example.com\r\nBcc: x@example.com", "a b@example.com", "<a@example.com>", "a@example.com,b@example.com", "no-at-sign", ""):
        assert not mailer.valid_address(bad), bad
    result = mailer.send(s, ["a@example.com\r\nBcc: evil@example.com"], "s", "t")
    assert result["sent"] == 0 and "no valid recipient" in result["error"] and smtp.messages == []


# ------------------------------------------------------------------------------------------------ the mail goes out for real
def test_the_email_really_goes_out_over_smtp_as_text_and_html(smtp):
    s = Settings(_env_file=None, **smtp.settings)
    result = mailer.send(s, ["owner@example.com", "owner@example.com", "second@example.com", "not an address"], "[RAGGuard] Hi", "plain body", "<p>html body</p>")
    assert result == {"sent": 2, "failed": 0, "error": None}  # a duplicate and an invalid address are dropped
    assert [e[1] for e in smtp.envelopes] == [["owner@example.com"], ["second@example.com"]]  # one message each: nobody sees the others
    m = smtp.messages[0]
    assert m["Subject"] == "[RAGGuard] Hi" and m["From"] == "RAGGuard <alerts@example.com>" and m["To"] == "owner@example.com"
    assert m["Auto-Submitted"] == "auto-generated" and m["Message-ID"].endswith("@example.com>")
    assert m.get_body(("plain",)).get_content().strip() == "plain body" and m.get_body(("html",)).get_content().strip() == "<p>html body</p>"


def test_delivery_problems_are_reported_in_words_and_never_raise(smtp, monkeypatch):
    s = Settings(_env_file=None, **smtp.settings)
    assert mailer.send(Settings(_env_file=None), ["a@example.com"], "s", "t")["error"].startswith("no mail server is configured")
    assert mailer.send(Settings(_env_file=None, **{**smtp.settings, "smtp_security": "carrier-pigeon"}), ["a@example.com"], "s", "t")["failed"] == 1
    smtp.close()  # the server goes away
    down = mailer.send(s, ["a@example.com"], "s", "t")
    assert down["sent"] == 0 and down["failed"] == 1 and down["error"]


def test_the_connection_is_made_secure_and_logged_in_in_the_right_order(monkeypatch):
    calls: list[str] = []

    class Recorder:
        def __init__(self, host, port, timeout=None, context=None):
            calls.append(f"connect {host}:{port} timeout={timeout}" + (" ssl" if context is not None else ""))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            calls.append("quit")

        def starttls(self, context=None):
            calls.append("starttls")

        def login(self, user, password):
            calls.append(f"login {user}")
            raise OSError(f"535 bad credentials for {user}/{password}")

        def send_message(self, msg):
            calls.append("send")

    monkeypatch.setattr(mailer.smtplib, "SMTP", Recorder)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", Recorder)
    base = {"smtp_host": "mail.example.com", "smtp_port": 587, "smtp_from": "a@example.com", "smtp_user": "mailer", "smtp_password": "s3cret-pass"}
    result = mailer.send(Settings(_env_file=None, **base), ["to@example.com"], "s", "t")
    assert calls == ["connect mail.example.com:587 timeout=8", "starttls", "login mailer", "quit"]  # encrypted first, only then the password
    assert result["sent"] == 0 and "s3cret-pass" not in result["error"] and "mailer/" not in result["error"]  # credentials never echoed
    calls.clear()
    mailer.send(Settings(_env_file=None, **{**base, "smtp_security": "ssl", "smtp_port": 465}), ["to@example.com"], "s", "t")
    assert calls[0] == "connect mail.example.com:465 timeout=8 ssl" and "starttls" not in calls


# ------------------------------------------------------------------------------------------------ through the audit itself
def test_a_finished_audit_creates_the_notification_and_sends_the_email_with_the_actions(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", app_url="https://ragguard.example.com", **smtp.settings)
    result = svc.run_audit()
    [row], unread = svc.ledger.list_notifications()
    assert unread == 1 and row["kind"] == "audit_completed" and row["run_id"] == result.run_id and row["read_at"] is None
    assert row["title"].startswith("Audit complete:") and row["actions"][0]["id"] == "review_issues" and row["emailed_at"] is not None
    assert row["details"][0].startswith("Since the last audit:") and any(d.startswith("[") for d in row["details"])
    assert result.stats["notifications"] == {"in_app": row["id"], "email": {"sent": 1, "to": 1}}
    assert svc.ledger.get_run(result.run_id)["stats"]["notifications"]["email"]["sent"] == 1
    [m] = smtp.messages
    assert m["To"] == "ops@example.com" and m["Subject"].startswith("[RAGGuard] Audit complete:")
    text = m.get_body(("plain",)).get_content()
    assert f"https://ragguard.example.com/audit-history/{result.run_id}" in text and "Review" in text


def test_an_email_is_not_sent_when_the_workspace_turned_it_off_but_the_notification_is_still_made(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", alert_email_when="never", **smtp.settings)
    result = svc.run_audit()
    assert smtp.messages == [] and len(svc.ledger.list_notifications()[0]) == 1
    assert "switched off" in result.stats["notifications"]["email"]["reason"]


def test_attention_only_stays_quiet_for_a_clean_audit_and_speaks_for_a_partial_one(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(clean_points()), alert_email_to="ops@example.com", alert_email_when="attention", **smtp.settings)
    clean = svc.run_audit()
    assert clean.stats["findings_total"] == 0 and smtp.messages == [] and titles(svc) == ["Audit complete: no integrity issues"]
    assert "only gets email when something does" in clean.stats["notifications"]["email"]["reason"]

    index = PointIndex(world_points(), fail={1: (2, TimeoutError("timed out"))})
    svc2 = service(tmp_path, index, name="second", alert_email_to="ops@example.com", alert_email_when="attention", **smtp.settings)
    partial = svc2.run_audit()
    assert partial.status == "partial" and len(smtp.messages) == 1
    assert smtp.messages[0]["Subject"] == "[RAGGuard] Audit stopped part-way: 4 of 12 documents checked"
    [row], _ = svc2.ledger.list_notifications()
    assert row["kind"] == "audit_partial" and row["actions"][0] == {"id": "resume_audit", "label": "Resume audit", "kind": "post",
                                                                      "target": "/api/audits", "primary": True, "body": {"resume": True}}


def test_a_new_serious_issue_is_attention_even_when_the_audit_completed(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", alert_email_when="attention", alert_min_severity="low", **smtp.settings)
    svc.run_audit()
    assert len(smtp.messages) == 1  # new issues at or above the minimum severity: the same rule as the Slack webhook
    again = svc.run_audit()  # nothing new now
    assert again.diff.opened == [] and len(smtp.messages) == 1 and len(svc.ledger.list_notifications()[0]) == 2


def test_a_failed_audit_notifies_with_the_reason_and_run_it_again(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points(), fail={0: (1, ConnectionError("connection refused"))}), alert_email_to="ops@example.com", **smtp.settings)
    with pytest.raises(ConnectionError):
        svc.run_audit()
    [row], _ = svc.ledger.list_notifications()
    assert row["kind"] == "audit_failed" and "connection refused" in row["body"] and row["actions"][0]["id"] == "run_audit"
    assert [m["Subject"] for m in smtp.messages] == ["[RAGGuard] Audit failed"]
    [run] = svc.ledger.list_runs(limit=5)
    assert run["status"] == "failed" and run["stats"]["notifications"]["email"]["sent"] == 1


def test_a_mail_server_that_is_down_never_fails_or_slows_the_audit_and_the_notification_survives(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", smtp_host="127.0.0.1", smtp_port=1,
                  smtp_from="a@example.com", smtp_security="none")
    result = svc.run_audit()
    assert result.status == "completed" and svc.ledger.get_run(result.run_id)["status"] == "completed"
    assert result.stats["notifications"]["email"]["sent"] == 0 and result.stats["notifications"]["email"]["error"]
    assert len(svc.ledger.list_notifications()[0]) == 1 and svc.ledger.list_notifications()[0][0]["emailed_at"] is None


def test_without_a_mail_server_the_notification_is_made_and_the_run_says_why_no_email_went(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com")
    result = svc.run_audit()
    assert "no mail server is configured" in result.stats["notifications"]["email"]["reason"] and len(titles(svc)) == 1


def test_a_database_without_the_notifications_table_never_fails_an_audit(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", **smtp.settings)
    svc.ledger.t["notifications"].drop(svc.ledger.engine)  # a deployment whose database has not been updated
    result = svc.run_audit()
    assert result.status == "completed" and svc.ledger.get_run(result.run_id)["status"] == "completed"
    assert "in_app_error" in result.stats["notifications"] and result.stats["notifications"]["in_app"] is None
    # the hourly email limit is kept in that table: when it cannot be checked, the safe answer is no email (never an unlimited one)
    assert smtp.messages == [] and "could not be checked" in result.stats["notifications"]["email"]["reason"]


def test_a_step_inside_another_action_is_not_announced(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", **smtp.settings)
    result = svc.run_audit(trigger="bootstrap")
    assert svc.ledger.list_notifications() == ([], 0) and smtp.messages == [] and "skipped" in result.stats["notifications"]


def test_a_workspace_cannot_make_the_platform_send_more_than_the_hourly_cap(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(world_points()), alert_email_to="ops@example.com", **smtp.settings)
    for _ in range(notifications.EMAILS_PER_HOUR):
        nid = svc.ledger.add_notification(kind="audit_completed", tone="info", title="t", body="b", run_id=None, actions=[])
        svc.ledger.mark_notification_emailed(nid)
    result = svc.run_audit()
    assert smtp.messages == [] and "already sent 12 emails in the last hour" in result.stats["notifications"]["email"]["reason"]
    assert svc.ledger.list_notifications()[1] == 13 and len(svc.ledger.list_notifications(limit=50)[0]) == 13  # the new one is still shown in the app


def test_only_the_newest_two_hundred_notifications_are_kept(tmp_path):
    ledger = Ledger(f"sqlite:///{(tmp_path / 'n.db').as_posix()}")
    ledger.init()
    ids = [ledger.add_notification(kind="audit_completed", tone="info", title=f"n{i}", body="b", run_id=None, actions=[]) for i in range(Ledger.NOTIFICATIONS_KEPT + 5)]
    rows, unread = ledger.list_notifications(limit=100)
    assert unread == Ledger.NOTIFICATIONS_KEPT and rows[0]["id"] == ids[-1] and ledger.get_notification(ids[0]) is None


# ------------------------------------------------------------------------------------------------ who gets the email in app mode
def test_in_app_mode_the_email_goes_to_the_workspaces_own_users_and_never_to_the_operators_address(tmp_path):
    base = Settings(_env_file=None, mode="app", alert_email_to="platform-admin@example.com", smtp_host="mail.example.com", smtp_from="a@example.com")
    assert base.alert_email_to == "platform-admin@example.com"
    ws = overlay(base, {})
    assert ws.alert_email_to is None and ws.smtp_host == "mail.example.com"  # the platform's mail account is shared; its address list is not

    c, app, settings = make(tmp_path)
    with c:
        alice, bob = TestClient(c.app), TestClient(c.app)
        signup(alice, "alice@example.com")
        signup(bob, "bob@example.com")
        ledger = Ledger(settings.database_url)
        ids = {"alice": workspace_of(settings, "alice@example.com"), "bob": workspace_of(settings, "bob@example.com")}
        assert ledger.for_workspace(ids["alice"]).workspace_emails() == ["alice@example.com"]
        assert ledger.for_workspace(ids["bob"]).workspace_emails() == ["bob@example.com"]
        assert notifications._recipients(ws, ledger.for_workspace(ids["alice"])) == ["alice@example.com"]  # not the operator's address
        assert ledger.for_workspace("no-such-workspace").workspace_emails() == []


# ------------------------------------------------------------------------------------------------ the API
def seed(settings, ws, **kw):
    ledger = Ledger(settings.database_url).for_workspace(ws)
    return ledger.add_notification(kind=kw.get("kind", "audit_partial"), tone="warning", title=kw.get("title", "Audit stopped part-way"), body="b",
                                   run_id="run-1", details=["d"], actions=[
                                       {"id": "resume_audit", "label": "Resume audit", "kind": "post", "target": "/api/audits", "primary": True, "body": {"resume": True}},
                                       {"id": "open_run", "label": "See the run", "kind": "link", "target": "/audit-history/run-1", "primary": False}])


def test_notifications_over_http_list_read_and_record_the_action_taken(tmp_path):
    c, app, settings = make(tmp_path)
    with c:
        signup(c)
        ws = workspace_of(settings, "alice@example.com")
        assert c.get("/api/notifications").json() == {"items": [], "unread": 0}
        first, second = seed(settings, ws, title="one"), seed(settings, ws, title="two")
        body = c.get("/api/notifications").json()
        assert body["unread"] == 2 and [n["title"] for n in body["items"]] == ["two", "one"] and body["items"][0]["actions"][0]["id"] == "resume_audit"
        assert c.get("/api/notifications?limit=1").json()["items"][0]["title"] == "two" and c.get("/api/notifications?limit=0").status_code == 422

        assert c.post(f"/api/notifications/{first}/read").json() == {"ok": True}
        assert c.get("/api/notifications?unread=true").json()["unread"] == 1 and [n["id"] for n in c.get("/api/notifications?unread=true").json()["items"]] == [second]
        assert c.post(f"/api/notifications/{second}/done", json={"action": "resume_audit"}).json() == {"ok": True}
        done = [n for n in c.get("/api/notifications").json()["items"] if n["id"] == second][0]
        assert done["done_action"] == "resume_audit" and done["read_at"] is not None
        assert c.get("/api/notifications").json()["unread"] == 0

        assert c.post(f"/api/notifications/{second}/done", json={"action": "delete_everything"}).status_code == 422  # not one of its actions
        assert c.post("/api/notifications/no-such-id/read").status_code == 404 and c.post("/api/notifications/no-such-id/done", json={"action": "x"}).status_code == 404
        seed(settings, ws)
        assert c.post("/api/notifications/read-all").json() == {"marked": 1} and c.get("/api/notifications").json()["unread"] == 0


def test_a_workspace_only_ever_sees_and_changes_its_own_notifications(tmp_path):
    c, app, settings = make(tmp_path)
    with c:
        alice, bob = TestClient(c.app), TestClient(c.app)
        signup(alice, "alice@example.com")
        signup(bob, "bob@example.com")
        a_ws = workspace_of(settings, "alice@example.com")
        mine = seed(settings, a_ws, title="alice only")
        assert alice.get("/api/notifications").json()["unread"] == 1
        assert bob.get("/api/notifications").json() == {"items": [], "unread": 0}
        assert bob.post(f"/api/notifications/{mine}/read").status_code == 404
        assert bob.post(f"/api/notifications/{mine}/done", json={"action": "resume_audit"}).status_code == 404
        assert bob.post("/api/notifications/read-all").json() == {"marked": 0}
        n = alice.get("/api/notifications").json()["items"][0]
        assert n["read_at"] is None and n["done_action"] is None  # Bob changed nothing of Alice's


def test_notifications_need_a_signed_in_user_and_changes_need_the_same_origin(tmp_path):
    c, app, settings = make(tmp_path)
    with c:
        anonymous = TestClient(c.app)
        assert anonymous.get("/api/notifications").status_code == 401
        assert anonymous.post("/api/notifications/read-all").status_code in (401, 403)
        signup(c)
        assert c.post("/api/notifications/read-all", headers={"Origin": "http://evil.example.com"}).status_code == 403


# ------------------------------------------------------------------------------------------------ the Send test email button
def test_the_test_email_goes_to_the_signed_in_workspaces_own_address_and_to_nobody_else(tmp_path, smtp):
    c, app, settings = make(tmp_path, **smtp.settings)
    with c:
        alice, bob = TestClient(c.app), TestClient(c.app)
        signup(alice, "alice@example.com")
        signup(bob, "bob@example.com")
        first = alice.post("/api/alerts/test-email")
        assert first.status_code == 200 and first.json() == {"ok": True, "sent": 1, "to": ["alice@example.com"]}
        assert [e[1] for e in smtp.envelopes] == [["alice@example.com"]]  # not Bob, and not the operator
        m = smtp.messages[0]
        assert m["Subject"] == "[RAGGuard] This is a test email from RAGGuard" and m["To"] == "alice@example.com"
        text = m.get_body(("plain",)).get_content()
        assert "test" in text.lower() and "Nothing was found or changed" in text and "Open Alert settings" in text
        assert bob.post("/api/alerts/test-email").json()["to"] == ["bob@example.com"]
        assert [e[1] for e in smtp.envelopes] == [["alice@example.com"], ["bob@example.com"]]
        # a test email is not an audit result: no notification is created and the hourly cap is untouched
        assert alice.get("/api/notifications").json() == {"items": [], "unread": 0}


def test_without_a_mail_account_the_test_email_says_what_is_missing_and_sends_nothing(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        signup(c)
        body = c.post("/api/alerts/test-email").json()
        assert body["ok"] is False and body["sent"] == 0 and body["to"] == []
        assert "RAGI_SMTP_HOST" in body["reason"] and "RAGI_SMTP_FROM" in body["reason"]


def test_a_mail_server_that_refuses_the_test_email_is_reported_without_echoing_the_password(tmp_path):
    c, *_ = make(tmp_path, smtp_host="127.0.0.1", smtp_port=1, smtp_from="a@example.com", smtp_security="none",
                 smtp_user="mailer", smtp_password="s3cret-pass-word")
    with c:
        signup(c)
        r = c.post("/api/alerts/test-email")
        body = r.json()
        assert r.status_code == 200 and body["ok"] is False and body["sent"] == 0 and body["reason"].startswith("The mail server did not accept it")
        assert "s3cret-pass-word" not in r.text


def test_the_test_email_cannot_be_used_to_flood_an_inbox(tmp_path, smtp):
    c, *_ = make(tmp_path, **smtp.settings)
    with c:
        signup(c)
        codes = [c.post("/api/alerts/test-email").status_code for _ in range(6)]
        assert codes == [200, 200, 200, 200, 200, 429] and len(smtp.messages) == 5


def test_the_test_email_needs_a_signed_in_user_and_the_same_origin(tmp_path, smtp):
    c, *_ = make(tmp_path, **smtp.settings)
    with c:
        assert TestClient(c.app).post("/api/alerts/test-email").status_code in (401, 403)
        signup(c)
        assert c.post("/api/alerts/test-email", headers={"Origin": "http://evil.example.com"}).status_code == 403
        assert smtp.messages == []


def test_in_single_user_mode_the_test_email_goes_to_the_configured_addresses_and_is_limited_per_process(tmp_path, smtp):
    svc = service(tmp_path, PointIndex(clean_points()), alert_email_to="ops@example.com, not an address", **smtp.settings)
    first = svc.send_test_email()
    assert first == {"ok": True, "sent": 1, "to": ["ops@example.com"]} and smtp.messages[0]["To"] == "ops@example.com"
    for _ in range(notifications.TEST_EMAILS - 1):
        assert svc.send_test_email()["ok"] is True
    limited = svc.send_test_email()
    assert limited["ok"] is False and limited["rate_limited"] is True and len(smtp.messages) == notifications.TEST_EMAILS
    nobody = service(tmp_path, PointIndex(clean_points()), name="nobody", **smtp.settings).send_test_email()
    assert nobody["ok"] is False and "RAGI_ALERT_EMAIL_TO" in nobody["reason"]
