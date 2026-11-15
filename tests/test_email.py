"""Emailing a repair plan, the spreadsheet export, and one plan for everything at once.

Mail is delivered over real SMTP to the lab's mail catcher (scripts/mail_sink.py), so what is checked is what a mail server would
really receive: the headers, both bodies and both attachments.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import socket
import sys
import threading
import urllib.request
from email import message_from_bytes, policy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ragintegrity import plan_mail
from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.repair import RepairError
from ragintegrity.security import UnsafeTarget
from tests.test_service import make_service

ROOT = Path(__file__).parent.parent
KEY = "k" * 40
PW = "a-long-unusual-passphrase"


def load_sink():
    spec = importlib.util.spec_from_file_location("mail_sink_for_tests", ROOT / "scripts" / "mail_sink.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def sink():
    mod = load_sink()
    smtp = mod.ThreadedSmtp(("127.0.0.1", 0), mod.SmtpHandler)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    yield mod, smtp.server_address[1]
    smtp.shutdown()
    smtp.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def mailing(tmp_path, port, **extra):
    """A demo-world service that is set up to send mail to the catcher on `port`."""
    svc = make_service(tmp_path, smtp_host="127.0.0.1", smtp_port=port, smtp_security="none", smtp_from="ragguard@lab.test",
                       allow_private_hosts=True, **extra)
    svc.bootstrap()
    return svc


def received(mod, n=1):
    msgs = mod.INBOX.all()
    assert len(msgs) == n, f"{len(msgs)} message(s) arrived, expected {n}"
    return [message_from_bytes(m["raw"], policy=policy.default) for m in msgs]


# ------------------------------------------------------------------------------------------------ recipients
def test_recipients_are_split_validated_deduplicated_and_capped():
    assert plan_mail.parse_recipients("a@x.com, b@x.com; c@x.com  A@X.com") == ["a@x.com", "b@x.com", "c@x.com"]
    assert plan_mail.parse_recipients(["dev@example.org"]) == ["dev@example.org"]
    for bad in ("", "   ", "not-an-address", "a@b", "<a@x.com>", "a@x.com\nBcc: spy@evil.test", "a b@x.com", "x" * 300 + "@x.com"):
        with pytest.raises(plan_mail.MailError) as e:
            plan_mail.parse_recipients(bad)
        assert e.value.status == 422
    with pytest.raises(plan_mail.MailError, match="At most 10"):
        plan_mail.parse_recipients([f"p{i}@x.com" for i in range(11)])


# ------------------------------------------------------------------------------------------------ the spreadsheet
def test_the_csv_lists_every_document_and_cannot_run_a_formula(tmp_path):
    svc = make_service(tmp_path)
    svc.bootstrap()
    plan = svc.repairs.create_plan()
    plan["items"][0]["document_id"] = "=HYPERLINK(\"http://evil.test\",\"click\")"
    rows = list(csv.reader(io.StringIO(plan_mail.plan_csv(plan))))
    assert rows[0][:4] == ["tenant_id", "document_id", "severity", "what_to_do"]
    assert len(rows) == len(plan["items"]) + 1
    assert rows[1][1].startswith("'=HYPERLINK")  # stays text in Excel and Sheets
    assert all(r[3] for r in rows[1:])  # every document says what to do


# ------------------------------------------------------------------------------------------------ the message
def test_the_message_is_readable_escaped_and_cannot_inject_headers(tmp_path):
    svc = mailing(tmp_path, 25)
    plan = svc.repairs.create_plan()
    plan["items"][0]["document_id"] = "<script>alert(1)</script>.md"
    note = "Please fix today\nBcc: spy@evil.test\n<b>bold</b>"
    msg = plan_mail.build_plan_message(plan_mail.require_account(svc.settings), plan, ["dev@example.org"], note=note,
                                       link="https://app.example.com/issues?plan=x", payload=svc.repairs.payload(plan, "reindex"))
    assert msg["Subject"].startswith("RAGGuard repair plan: ") and "\n" not in msg["Subject"]
    assert msg["To"] == "dev@example.org" and msg["From"] == "ragguard@lab.test" and msg["Bcc"] is None
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert "Please fix today" in text and "Verify now" in text and "https://app.example.com/issues?plan=x" in text
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;bold&lt;/b&gt;" in html  # escaped, not interpreted
    assert [a.get_filename() for a in msg.iter_attachments()] == [f"repair-plan-{plan['id'][:8]}.csv", f"repair-plan-{plan['id'][:8]}-payload.json"]
    csv_part, json_part = list(msg.iter_attachments())
    assert csv_part.get_payload(decode=True).startswith(b"\xef\xbb\xbf")  # a BOM, so Excel reads it as UTF-8
    assert json.loads(json_part.get_payload(decode=True))["plan_id"] == plan["id"]


def test_a_big_plan_shows_a_few_rows_in_the_message_and_all_of_them_in_the_csv(tmp_path):
    svc = mailing(tmp_path, 25)
    plan = svc.repairs.create_plan()
    plan["items"] = plan["items"] * 12
    msg = plan_mail.build_plan_message(plan_mail.require_account(svc.settings), plan, ["dev@example.org"])
    assert "The attached CSV lists every document" in msg.get_body(("plain",)).get_content()
    assert len(list(csv.reader(io.StringIO(list(msg.iter_attachments())[0].get_payload(decode=True).decode("utf-8-sig"))))) == len(plan["items"]) + 1


# ------------------------------------------------------------------------------------------------ delivery
def test_emailing_a_plan_delivers_it_and_records_who_got_it(tmp_path, sink):
    mod, port = sink
    svc = mailing(tmp_path, port)
    plan = svc.repairs.create_plan()
    after = svc.repairs.email_plan(plan["id"], to="dev@example.org, lead@example.org", note="Please fix by Friday.",
                                   base_url="https://app.example.com")
    [msg] = received(mod)
    assert msg["To"] == "dev@example.org, lead@example.org" and mod.INBOX.all()[0]["to"] == ["dev@example.org", "lead@example.org"]
    assert "Please fix by Friday." in msg.get_body(("plain",)).get_content()
    assert f"https://app.example.com/issues?view=plans&plan={plan['id']}" in msg.get_body(("plain",)).get_content()
    names = [a.get_filename() for a in msg.iter_attachments()]
    assert len(names) == 2 and names[0].endswith(".csv") and names[1].endswith("-payload.json")
    event = next(e for e in after["events"] if e["event"] == "emailed")
    assert event["details"]["to"] == ["dev@example.org", "lead@example.org"] and event["details"]["count"] == 2
    assert after["status"] == "draft"  # emailing a plan changes nothing about the plan


def test_the_link_in_the_email_uses_the_configured_address_not_the_request(tmp_path, sink):
    mod, port = sink
    svc = mailing(tmp_path, port, app_url="https://rag.example.com")
    plan = svc.repairs.create_plan()
    svc.repairs.email_plan(plan["id"], to="dev@example.org", base_url="https://evil.test")  # what a forged Host header would give
    [msg] = received(mod)
    text = msg.get_body(("plain",)).get_content()
    assert f"https://rag.example.com/issues?view=plans&plan={plan['id']}" in text and "evil.test" not in text


def test_the_payload_attachment_can_be_left_out(tmp_path, sink):
    mod, port = sink
    svc = mailing(tmp_path, port)
    svc.repairs.email_plan(svc.repairs.create_plan()["id"], to="dev@example.org", attach_payload=False)
    [msg] = received(mod)
    assert [a.get_filename().rsplit(".", 1)[1] for a in msg.iter_attachments()] == ["csv"]


def test_email_needs_a_mail_server_and_a_valid_recipient(tmp_path, sink):
    _mod, port = sink
    bare = make_service(tmp_path)  # no mail server configured
    bare.bootstrap()
    plan = bare.repairs.create_plan()
    with pytest.raises(RepairError) as e:
        bare.repairs.email_plan(plan["id"], to="dev@example.org")
    assert e.value.status == 409 and "Email is not set up" in str(e.value)
    (tmp_path / "b").mkdir()
    ok = mailing(tmp_path / "b", port)
    with pytest.raises(RepairError) as e:
        ok.repairs.email_plan(ok.repairs.create_plan()["id"], to="nonsense")
    assert e.value.status == 422
    with pytest.raises(RepairError) as e:
        ok.repairs.email_plan("no-such-plan", to="dev@example.org")
    assert e.value.status == 404


def test_a_mail_server_that_is_down_gives_a_plain_message_without_the_password(tmp_path):
    svc = mailing(tmp_path, free_port(), smtp_password="hunter2-very-secret", smtp_user="me")
    with pytest.raises(RepairError) as e:
        svc.repairs.email_plan(svc.repairs.create_plan()["id"], to="dev@example.org")
    assert e.value.status == 502 and str(e.value).startswith("Could not send the email")
    assert "hunter2-very-secret" not in str(e.value)
    assert plan_mail._redact("login failed for hunter2-very-secret", plan_mail.require_account(svc.settings)) == "login failed for ***"


# ------------------------------------------------------------------------------------------------ which mail account sends
def test_a_workspaces_own_mail_server_wins_and_the_deployments_account_is_a_single_user_fallback():
    both = Settings(_env_file=None, smtp_host="mail.deploy.test", smtp_from="RAGGuard <alerts@deploy.test>", smtp_user="op", smtp_password="x",
                    plan_mail_host="smtp.mine.test", plan_mail_from="me@mine.test")
    mine = plan_mail.account(both)
    assert mine is not None and mine.host == "smtp.mine.test" and mine.own is True and mine.address == "me@mine.test"
    fallback = plan_mail.account(Settings(_env_file=None, smtp_host="mail.deploy.test", smtp_from="RAGGuard <alerts@deploy.test>", smtp_user="op"))
    assert fallback is not None and fallback.host == "mail.deploy.test" and fallback.own is False and fallback.username == "op"
    assert fallback.sender == "RAGGuard <alerts@deploy.test>" and fallback.address == "alerts@deploy.test"  # a display name is fine
    assert plan_mail.account(Settings(_env_file=None, smtp_host="mail.deploy.test", smtp_from="a@deploy.test"), deployment_account=False) is None
    assert plan_mail.account(Settings(_env_file=None, smtp_host="mail.deploy.test")) is None  # no From address, not usable
    assert plan_mail.account(Settings(_env_file=None)) is None


def test_the_platforms_mail_account_never_sends_a_workspaces_plan(tmp_path, sink):
    """In app mode anyone can sign up, so the platform's own address must not mail their recipients: no Email settings, no email."""
    mod, port = sink
    svc = mailing(tmp_path, port)  # the deployment's account is set up and reachable ...
    svc._guard = lambda settings, kind: None  # ... but this service belongs to a workspace (the workspace manager sets _guard)
    plan = svc.repairs.create_plan()
    with pytest.raises(RepairError) as e:
        svc.repairs.email_plan(plan["id"], to="stranger@example.org")
    assert e.value.status == 409 and "Email is not set up" in str(e.value)
    assert svc.repairs.preview()["email_configured"] is False and svc.overview()["email_configured"] is False
    assert mod.INBOX.all() == []


# ------------------------------------------------------------------------------------------------ safety on a hosted deployment
def hosted(**kw) -> Settings:
    base = dict(_env_file=None, plan_mail_host="8.8.8.8", plan_mail_port=587, plan_mail_security="starttls", plan_mail_from="r@example.com",
                allow_private_hosts=False)
    return Settings(**{**base, **kw})


def test_a_hosted_deployment_refuses_private_unencrypted_and_odd_mail_servers():
    plan_mail.guard(hosted())  # a public server, a submission port, encrypted
    plan_mail.guard(hosted(plan_mail_port=465, plan_mail_security="ssl"))
    for bad in (dict(plan_mail_host="10.0.0.5"), dict(plan_mail_host="127.0.0.1"), dict(plan_mail_host="169.254.169.254"),
                dict(plan_mail_host="localhost"), dict(plan_mail_port=22), dict(plan_mail_port=5432), dict(plan_mail_security="none")):
        with pytest.raises(UnsafeTarget):
            plan_mail.guard(hosted(**bad))
    plan_mail.guard(hosted(plan_mail_host="10.0.0.5", plan_mail_port=1025, plan_mail_security="none", allow_private_hosts=True))  # your own network


def test_check_settings_connects_and_sends_nothing(tmp_path, sink):
    mod, port = sink
    checks = {c["name"]: c for c in plan_mail.diagnose(mailing(tmp_path, port).settings, deployment_account=True)}
    assert checks["Mail server"]["status"] == "ok" and checks["Encryption"]["status"] == "warn" and checks["Sign in"]["status"] == "warn"
    assert mod.INBOX.all() == []
    (tmp_path / "d").mkdir()
    down = plan_mail.diagnose(mailing(tmp_path / "d", free_port()).settings, deployment_account=True)  # nothing is listening there
    assert len(down) == 1 and down[0]["name"] == "Mail server" and down[0]["status"] == "fail"


# ------------------------------------------------------------------------------------------------ the HTTP API (single user)
def api(svc):
    return TestClient(create_app(settings=svc.settings, service=svc))


def test_export_preview_email_and_bulk_over_http(tmp_path, sink):
    mod, port = sink
    svc = mailing(tmp_path, port)
    client = api(svc)
    ov = client.get("/api/overview").json()
    assert ov["email_configured"] is True

    pre = client.post("/api/repairs/preview", json={"min_severity": "high"}).json()
    assert pre["documents"] > 0 and pre["email_configured"] is True and pre["webhook_configured"] is True
    assert pre["to_reprocess"] + pre["cleanup_only"] == pre["documents"] and sum(pre["by_severity"].values()) == pre["documents"]
    assert client.get("/api/repairs").json() == []  # a preview creates nothing

    plan = client.post("/api/repairs", json={"min_severity": "critical"}).json()
    export = client.get(f"/api/repairs/{plan['id']}/export")
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    assert export.headers["content-disposition"] == f'attachment; filename="repair-plan-{plan["id"][:8]}.csv"'
    assert export.content.startswith(b"\xef\xbb\xbf") and export.text.count("\n") >= len(plan["items"])

    sent = client.post(f"/api/repairs/{plan['id']}/email", json={"to": ["dev@example.org"], "note": "hi"})
    assert sent.status_code == 200 and any(e["event"] == "emailed" for e in sent.json()["events"])
    assert client.post(f"/api/repairs/{plan['id']}/email", json={"to": "nonsense"}).status_code == 422
    assert client.post("/api/repairs/nope/email", json={"to": "dev@example.org"}).status_code == 404
    assert len(received(mod)) == 1


def test_a_bulk_repair_makes_one_plan_sends_it_and_mails_it(tmp_path, sink):
    mod, port = sink
    svc = mailing(tmp_path, port)
    client = api(svc)
    r = client.post("/api/repairs/bulk", json={"min_severity": "high", "send": True, "email_to": "dev@example.org", "note": "bulk"})
    assert r.status_code == 201
    body = r.json()
    assert body["problems"] == [] and body["sent"] is True and body["emailed"] == ["dev@example.org"]
    plan = body["plan"]
    assert plan["status"] != "draft" and len(plan["items"]) > 1  # many documents, one plan, one send
    assert len([c for c in svc.connectors.world.worker_calls if c["phase"] == "reindex"]) == 1
    assert len(client.get("/api/repairs").json()) == 1
    assert [e["event"] for e in plan["events"]].count("emailed") == 1
    [msg] = received(mod)
    assert f"{len(plan['items'])} document" in msg["Subject"]


def test_bulk_steps_fail_independently(tmp_path):
    svc = make_service(tmp_path)  # no mail server
    svc.bootstrap()
    client = api(svc)
    r = client.post("/api/repairs/bulk", json={"min_severity": "critical", "send": True, "email_to": "dev@example.org"})
    assert r.status_code == 201  # the plan exists and was sent; only the email could not be
    body = r.json()
    assert body["sent"] is True and body["emailed"] is None
    assert [p["step"] for p in body["problems"]] == ["email"] and "Email is not set up" in body["problems"][0]["message"]
    assert client.post("/api/repairs/bulk", json={"types": ["manifest_orphan"], "tenant": "no-such-tenant"}).status_code == 404


def test_a_bulk_repair_without_a_worker_still_creates_the_plan(tmp_path):
    svc = make_service(tmp_path)
    svc.bootstrap()
    svc.settings = svc.settings.model_copy(update={"mode": "live", "repair_webhook_url": None})  # demo mode has a stand-in worker; live does not
    out = svc.repairs.bulk(min_severity="critical", send=True)
    assert out["sent"] is False and out["plan"]["status"] == "draft"
    assert [p["step"] for p in out["problems"]] == ["send"] and "No repair webhook configured" in out["problems"][0]["message"]


# ------------------------------------------------------------------------------------------------ the multi-user app
def app_client(tmp_path, **kw):
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'app.db'}", secret_key=KEY, **kw)
    client = TestClient(create_app(settings=settings))
    return client


def signup(client, email="alice@example.com"):
    r = client.post("/api/auth/register", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    client.headers.update({"Origin": "http://testserver"})


def email_group(client):
    return next(k for k in client.get("/api/settings").json()["kinds"] if k["kind"] == "email")


def test_email_settings_are_stored_like_other_credentials_and_checked_for_safety(tmp_path, sink):
    mod, port = sink
    with app_client(tmp_path, allow_private_hosts=True) as client:
        signup(client)
        g = email_group(client)
        assert g["title"] == "Email" and g["configured"] is False and {f["name"] for f in g["fields"]} == {
            "host", "port", "security", "username", "password", "from_address"}
        saved = client.put("/api/settings/email", json={"values": {"host": "127.0.0.1", "port": port, "security": "none", "username": "me",
                                                                  "password": "s3cret-pass", "from_address": "ragguard@lab.test"}})
        assert saved.status_code == 200
        g = next(k for k in saved.json()["kinds"] if k["kind"] == "email")
        pw = next(f for f in g["fields"] if f["name"] == "password")
        assert g["configured"] is True and pw["value"] is None and pw["has_value"] is True
        assert "s3cret-pass" not in json.dumps(saved.json())  # never shown again
        # "Check settings" on the saved values connects (the catcher takes no sign-in, so the sign-in step is refused politely)
        t = client.post("/api/settings/email/test", json={"values": {"username": "", "password": ""}}).json()
        assert t["checks"][0]["name"] == "Mail server" and t["checks"][0]["status"] == "ok"
        assert client.put("/api/settings/email", json={"values": {"from_address": "not an address"}}).status_code == 422
        assert client.put("/api/settings/email", json={"values": {"port": 70000}}).status_code == 422


def test_a_hosted_app_refuses_unsafe_mail_settings_when_they_are_saved(tmp_path):
    with app_client(tmp_path) as client:  # allow_private_hosts is off, as on the hosted site
        signup(client)
        ok = {"host": "8.8.8.8", "port": 587, "security": "starttls", "from_address": "r@example.com"}
        assert client.put("/api/settings/email", json={"values": ok}).status_code == 200
        for patch in ({"host": "10.1.2.3"}, {"host": "localhost"}, {"host": "http://smtp.example.com"}, {"port": 22}, {"security": "none"}):
            r = client.put("/api/settings/email", json={"values": {**ok, **patch}})
            assert r.status_code == 422, (patch, r.text)


def test_only_a_signed_in_person_can_email_and_only_so_often(tmp_path):
    with app_client(tmp_path) as client:
        assert client.post("/api/repairs/x/email", json={"to": "a@b.co"}).status_code == 401
        signup(client)
        token = client.post("/api/keys", json={"name": "ci"}).json()["token"]
        with TestClient(client.app) as machine:  # an API key, not a session
            r = machine.post("/api/repairs/x/email", json={"to": "a@b.co"}, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 403
            assert machine.post("/api/repairs/bulk", json={"email_to": "a@b.co"}, headers={"Authorization": f"Bearer {token}"}).status_code == 403
        codes = [client.post("/api/repairs/x/email", json={"to": "a@b.co"}).status_code for _ in range(22)]
        assert codes[:20] == [404] * 20 and codes[20:] == [429, 429]  # 20 an hour per workspace


# ------------------------------------------------------------------------------------------------ the lab's mail catcher
def test_the_mail_catcher_shows_mail_and_attachments_in_a_web_page(tmp_path):
    mod = load_sink()
    smtp, web = mod.serve("127.0.0.1", 0, 0)
    try:
        svc = mailing(tmp_path, smtp.server_address[1])
        svc.repairs.email_plan(svc.repairs.create_plan()["id"], to="dev@example.org")
        base = f"http://127.0.0.1:{web.server_address[1]}"
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "RAGGuard repair plan" in page and "dev@example.org" in page
        detail = urllib.request.urlopen(base + "/mail/1").read().decode()
        assert "repair-plan-" in detail and ".csv" in detail
        att = urllib.request.urlopen(base + "/mail/1/0")
        assert att.headers["Content-Disposition"].startswith("attachment") and att.read().startswith(b"\xef\xbb\xbf")
        assert b"repair plan" in urllib.request.urlopen(base + "/body/1").read().lower()
        assert urllib.request.urlopen(base + "/raw/1").headers["Content-Type"] == "message/rfc822"
    finally:
        smtp.shutdown()
        web.shutdown()
