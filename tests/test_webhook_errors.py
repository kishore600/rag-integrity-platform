"""A webhook address is a secret (Slack puts the token in the path). A failed delivery must never record or show it."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from ragintegrity import alerts, repair
from ragintegrity.config import Settings
from ragintegrity.ledger import RunDiff
from ragintegrity.models import Action, Finding, IssueType, Severity
from ragintegrity.repair import RepairError
from ragintegrity.security import redact_urls
from tests.test_service import make_service

TOKEN = "s3cr3tTOKEN0123456789"
URL = f"https://hooks.slack.com/services/T000/B000/{TOKEN}"


def finding() -> Finding:
    return Finding(IssueType.MISSING_EMBEDDING, Severity.HIGH, "acme", "doc-1", None, "A document has no vectors", "detail", {},
                   Action.REINDEX_FULL)


def raising(exc: Exception):
    def post(*args, **kwargs):
        raise exc

    return post


def status_error(code: int = 404) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", URL)
    return httpx.HTTPStatusError(
        f"Client error '{code} Not Found' for url '{URL}'\nFor more information check: "
        f"https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/{code}",
        request=request, response=httpx.Response(code, request=request))


def test_redact_urls_removes_addresses_and_known_secrets():
    # (it would rather take a trailing bracket with an address than leave the tail of a secret one behind)
    assert redact_urls(f"failed for url '{URL}' (see https://example.com/x?y=1)") == "failed for url '<url>' (see <url>"
    assert redact_urls(f"boom {URL}", URL) == "boom <webhook>"
    assert redact_urls("no address here") == "no address here"


@pytest.mark.parametrize("exc", [
    status_error(404),
    httpx.ConnectError(f"cannot connect to {URL}"),
    RuntimeError(f"unexpected failure posting to {URL}"),
])
def test_a_failed_alert_never_records_or_logs_the_webhook_address(monkeypatch, caplog, exc):
    settings = Settings(_env_file=None, alert_webhook_url=URL, alert_min_severity="low")
    monkeypatch.setattr(alerts.httpx, "post", raising(exc))
    with caplog.at_level(logging.WARNING, logger="ragintegrity.alerts"):
        out = alerts.notify(settings, "run-1", RunDiff(opened=[finding()]), {"health_score": 90.0})
    assert out["sent"] == 0 and out["error"]  # the failure is still reported, with its type
    assert TOKEN not in json.dumps(out) and "hooks.slack.com" not in json.dumps(out)
    assert TOKEN not in caplog.text and "hooks.slack.com" not in caplog.text


def test_the_status_code_stays_visible_so_the_error_is_still_useful(monkeypatch):
    settings = Settings(_env_file=None, alert_webhook_url=URL, alert_min_severity="low")
    monkeypatch.setattr(alerts.httpx, "post", raising(status_error(410)))
    out = alerts.notify(settings, "run-1", RunDiff(opened=[finding()]), {"health_score": 90.0})
    assert "410" in out["error"] and out["error"].startswith("HTTPStatusError")


def test_a_failed_repair_delivery_never_shows_the_webhook_address(tmp_path, monkeypatch):
    svc = make_service(tmp_path, repair_webhook_url=URL, repair_webhook_secret="x" * 32)
    monkeypatch.setattr(repair.httpx, "post", raising(status_error(502)))
    with pytest.raises(RepairError) as exc:
        svc.repairs._deliver({"event": "repair.requested"})
    assert exc.value.status == 502 and "502" in str(exc.value)
    assert TOKEN not in str(exc.value) and "hooks.slack.com" not in str(exc.value)
