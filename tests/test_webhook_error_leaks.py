"""Where a failed delivery could still show the webhook address after ``redact_urls`` (tests/test_webhook_errors.py).

The alert webhook is an encrypted write-only secret (often a Slack URL whose path *is* the credential). These tests
deliver to a real local server (404, 500, redirects with absolute, relative and scheme-relative targets) and to a
closed port, then look for the address, its host, path, query, user info and the redirect target in everything a user
can see: the recorded error, the ledger, the API (``GET /api/audits``), the log and the repair error. They also cover
runs that an older version stored with the address still in them.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from ragintegrity import alerts
from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.connectors.factory import build_connectors
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger, RunDiff
from ragintegrity.models import Action, Finding, IssueType, Severity
from ragintegrity.security import redact_urls
from ragintegrity.service import IntegrityService

TOKEN = "T0K3N-ALERT-SECRET"
QUERY = "QUERYSECRET-9f8e7d"
USER, PASSWORD = "hookuser", "HUNTER2-PW"
REDIRECT_TOKEN = "REDIRECT-TARGET-TOKEN"
SIGNING = "whsec-SIGNING-SECRET-VALUE"

LOCATIONS = {  # what the webhook's server answers with in the Location header of a 302
    "redirect-abs": lambda port: f"http://127.0.0.1:{port}/elsewhere/{REDIRECT_TOKEN}?k=1",
    "redirect-rel": lambda port: f"/services/T000/B000/{REDIRECT_TOKEN}",
    "redirect-relhost": lambda port: f"//other.example/{REDIRECT_TOKEN}",
}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        for kind, location in LOCATIONS.items():
            if f"/{kind}/" in self.path:
                self.send_response(302)
                self.send_header("Location", location(self.server.server_port))
                self.end_headers()
                return
        code = 404 if "/missing/" in self.path else 500 if "/broken/" in self.path else 200
        body = b'{"ok": true}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the test output quiet
        pass


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def closed_port() -> int:
    with socket.socket() as s:  # a port that was free a moment ago and has nothing listening
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_service(tmp_path, **overrides) -> tuple[TestClient, IntegrityService]:
    settings = Settings(
        _env_file=None, mode="demo", database_url=f"sqlite:///{tmp_path / 'd.db'}", grace_minutes=0,
        **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()}, **overrides)
    svc = IntegrityService(settings, Ledger(settings.database_url),
                           build_connectors(settings, DemoWorld(seed=5, docs_per_tenant=40)))
    return TestClient(create_app(svc, settings)), svc


def assert_clean(text: str, url: str, extra: tuple[str, ...] = ()) -> None:
    """The whole address and every part of it, and the redirect targets, must be absent."""
    for piece in (url, "127.0.0.1", "/hooks/", TOKEN, QUERY, PASSWORD, USER, REDIRECT_TOKEN, "other.example", "://", *extra):
        assert piece not in text, f"{piece!r} leaked into: {text!r}"


def first_run(c: TestClient) -> dict:
    """The bootstrap audit: the only one in a demo that finds new issues, so the only one that calls the webhook."""
    runs = c.get("/api/audits").json()
    assert runs and runs[0]["status"] == "completed", runs  # a failed alert never fails the audit
    return runs[0]


def finding() -> Finding:
    return Finding(IssueType.MISSING_EMBEDDING, Severity.HIGH, "acme", "doc-1", None, "A document has no vectors", "detail", {},
                   Action.REINDEX_FULL)


# ------------------------------------------------------------------------------------- alerts, end to end
@pytest.mark.parametrize("kind,status", [("missing", "404"), ("broken", "500"), ("redirect-abs", "302"),
                                         ("redirect-rel", "302"), ("redirect-relhost", "302")])
def test_a_failed_alert_shows_the_status_and_nothing_of_the_address(tmp_path, server, kind, status):
    url = f"http://{USER}:{PASSWORD}@127.0.0.1:{server}/hooks/{kind}/{TOKEN}?key={QUERY}"
    c, svc = make_service(tmp_path, alert_webhook_url=url)
    with c:
        run = first_run(c)
        alert = run["stats"]["alerts"]
        assert alert["sent"] == 0 and alert["error"].startswith("HTTPStatusError") and status in alert["error"]
        # what the interface reads (Alerts > Recent deliveries, the audit run page) and what the API returns
        for text in (json.dumps(run), c.get("/api/audits").text, c.get(f"/api/audits/{run['id']}").text,
                     json.dumps(svc.ledger.get_run(run["id"]))):
            assert_clean(text, url)


def test_an_unreachable_webhook_shows_nothing_of_the_address(tmp_path, closed_port):
    url = f"http://{USER}:{PASSWORD}@127.0.0.1:{closed_port}/hooks/{TOKEN}?key={QUERY}"
    c, svc = make_service(tmp_path, alert_webhook_url=url)
    with c:
        run = first_run(c)
        assert run["stats"]["alerts"]["sent"] == 0 and run["stats"]["alerts"]["error"].startswith("ConnectError")
        assert_clean(c.get("/api/audits").text, url)
        assert_clean(c.get(f"/api/audits/{run['id']}").text, url)


def test_the_log_does_not_carry_a_relative_redirect_target(tmp_path, server, caplog):
    url = f"http://127.0.0.1:{server}/hooks/redirect-rel/{TOKEN}?key={QUERY}"
    c, svc = make_service(tmp_path, alert_webhook_url=url)
    with caplog.at_level(logging.DEBUG), c:  # entering the app runs the bootstrap audit, which alerts
        pass
    lines = [r.getMessage() for r in caplog.records if r.name == "ragintegrity.alerts"]
    assert lines and "302" in lines[0]
    assert_clean("\n".join(lines), url)


def test_a_failed_alert_still_does_not_fail_the_audit_and_a_good_one_is_sent(tmp_path, server):
    c, svc = make_service(tmp_path, alert_webhook_url=f"http://127.0.0.1:{server}/hooks/ok/{TOKEN}")
    with c:
        alert = first_run(c)["stats"]["alerts"]
        assert alert["sent"] == 1 and "error" not in alert


def test_a_tls_failure_does_not_name_the_webhook_host(tmp_path, monkeypatch):
    host = "internal-hooks.corp.example"
    settings = Settings(_env_file=None, alert_webhook_url=f"https://{host}/hooks/{TOKEN}", alert_min_severity="low")

    def boom(*a, **k):
        raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, "
                                 f"certificate is not valid for '{host}'. (_ssl.c:1006)")

    monkeypatch.setattr(alerts.httpx, "post", boom)
    out = alerts.notify(settings, "run-1", RunDiff(opened=[finding()]), {"health_score": 90.0})
    assert out["error"].startswith("ConnectError") and "CERTIFICATE_VERIFY_FAILED" in out["error"]  # still diagnosable
    assert host not in out["error"] and TOKEN not in out["error"]


# ------------------------------------------------------------------------------------- repair webhook
@pytest.mark.parametrize("kind", ["broken", "redirect-rel", "refused"])
def test_a_failed_repair_delivery_shows_nothing_of_the_address_or_the_signing_secret(tmp_path, server, closed_port, kind):
    url = (f"http://{USER}:{PASSWORD}@127.0.0.1:{closed_port}/hooks/{TOKEN}?key={QUERY}" if kind == "refused"
           else f"http://127.0.0.1:{server}/hooks/{kind}/{TOKEN}?key={QUERY}")
    c, svc = make_service(tmp_path, repair_webhook_url=url, repair_webhook_secret=SIGNING)
    with c:
        plan = c.post("/api/repairs", json={"types": ["stale_embedding"]}).json()
        r = c.post(f"/api/repairs/{plan['id']}/trigger")
        assert r.status_code == 502
        detail = r.json()["detail"]
        assert detail.startswith("Repair webhook delivery failed: ") and ("ConnectError" if kind == "refused" else "HTTPStatusError") in detail
        assert_clean(r.text, url, (SIGNING, "whsec"))


# ------------------------------------------------------------------------------------- rows stored by older versions
def test_runs_recorded_before_the_redaction_are_cleaned_on_the_way_out(tmp_path):
    c, svc = make_service(tmp_path)
    old_status = ("HTTPStatusError: Client error '404 Not Found' for url 'https://hooks.slack.com/services/T000/B000/"
                  f"{TOKEN}'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404")
    old_redirect = ("HTTPStatusError: Redirect response '302 Found' for url 'https://hooks.slack.com/services/T000/B000/"
                    f"{TOKEN}'\nRedirect location: '/services/T000/B000/{REDIRECT_TOKEN}'")
    ids = []
    for error in (old_status[:160], old_redirect[:160], old_redirect):  # the old code cut the text at 160 characters
        run_id = svc.ledger.start_run("full", "manual", None)
        svc.ledger.finish_run(run_id, "completed", {"alerts": {"sent": 0, "error": error}, "health_score": 91.5})
        ids.append(run_id)
    with c:
        runs = [svc.ledger.get_run(i) for i in ids] + [r for r in svc.ledger.list_runs() if r["id"] in ids]
        runs += [c.get(f"/api/audits/{i}").json() for i in ids] + [r for r in c.get("/api/audits").json() if r["id"] in ids]
        assert len(runs) == 12
        for run in runs:
            text = json.dumps(run)
            assert TOKEN not in text and REDIRECT_TOKEN not in text and "hooks.slack.com" not in text and "://" not in text
            assert run["stats"]["alerts"]["error"].startswith("HTTPStatusError")  # the type and status stay readable
            assert run["stats"]["health_score"] == 91.5 and run["stats"]["alerts"]["sent"] == 0


# ------------------------------------------------------------------------------------- redact_urls itself
def test_redact_urls_removes_a_redirect_target_with_or_without_a_scheme():
    assert redact_urls("x\nRedirect location: '/services/T0/B0/tok'\ny") == "x\nRedirect location: '<url>'\ny"
    assert redact_urls("Redirect location: '//other.example/tok'") == "Redirect location: '<url>'"
    assert redact_urls("Redirect location: 'https://other.example/tok'") == "Redirect location: '<url>'"


def test_redact_urls_removes_the_parts_of_the_configured_address_wherever_they_appear():
    url = f"https://{USER}:{PASSWORD}@hooks.corp.example/services/T0/B0/{TOKEN}?key={QUERY}"
    text = f"not valid for 'hooks.corp.example'; path /services/T0/B0/{TOKEN}; query key={QUERY}"
    out = redact_urls(text, url)
    for piece in ("hooks.corp.example", TOKEN, QUERY):
        assert piece not in out
    assert out.startswith("not valid for '<webhook>'")
    assert redact_urls("the api rejected the call", "https://hooks.example.com/api") == "the api rejected the call"
    assert redact_urls("boom", None, "") == "boom"
