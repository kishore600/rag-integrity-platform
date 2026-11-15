"""An index too big to read within the host's time limit: the alert says what to change, and the audit pauses instead of failing again.

A whole-index read on the hosted site stops at its time limit (``AuditTimeout``). Running it again fails the same way, after
reading the customer's whole index for minutes. So the failed run says so (``stats.failure``), the notification and email spell
out what to change, and a new whole audit waits until the setup changes: the "only audit documents found in the source" switch
turned on (the audit then runs in pieces), or ``force`` for a worker on a server, which has no time limit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.connectors.base import AuditTimeout
from ragintegrity.connectors.factory import Connectors
from ragintegrity.ledger import Ledger
from ragintegrity.models import Scope
from ragintegrity.notifications import TOO_LARGE, too_large_steps
from ragintegrity.service import AuditPaused, IntegrityService
from tests.test_scan_reliability import DOCS, KEY, PointIndex, manifest_rows, source_docs, world_points
from tests.test_source_only import FakeManifest, FakeSource

TOO_BIG = AuditTimeout("The audit ran out of time while reading the vector index (after 555,000 items). This corpus is too large "
                       "to audit in one go here: audit one tenant at a time, narrow the source, or run `ragi audit` on a machine "
                       "without a request time limit.")


def make(tmp_path, *, source_only: bool = False, limit: int | None = 270, too_big: bool = True, **extra):
    """A service on a host with a time limit (``limit``), whose first read of the index runs out of time (``too_big``)."""
    s = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{(tmp_path / 'pause.db').as_posix()}",
                 source_documents_only=source_only, audit_slice_documents=4, probe_retrieval=False,
                 **({"max_audit_seconds": limit} if limit else {}), **extra)
    index = PointIndex(world_points(), fail={0: (2, TOO_BIG)} if too_big else None)
    svc = IntegrityService(s, Ledger(s.database_url), Connectors(FakeSource(source_docs(DOCS)), FakeManifest(manifest_rows(DOCS)), index))
    return svc, index


def fail_once(svc) -> None:
    with pytest.raises(AuditTimeout):
        svc.run_audit()


def latest_notification(svc) -> dict:
    return svc.ledger.list_notifications(limit=5)[0][0]


# ------------------------------------------------------------------------------------------------- the message
def test_a_too_big_index_fails_with_a_message_that_says_what_to_change(tmp_path):
    svc, _ = make(tmp_path)
    fail_once(svc)
    run = svc.ledger.list_runs(limit=1)[0]
    assert run["status"] == "failed" and run["stats"]["failure"] == {"kind": TOO_LARGE, "source_only": False, "paused": True}
    n = latest_notification(svc)
    assert n["kind"] == "audit_failed" and n["title"] == "Audit paused: your index is too big to read in one go"
    assert "after 555,000 items" in n["body"] and "paused" in n["body"] and "fail the same way" in n["body"]
    text = " ".join(n["details"])
    assert "keyword index" in text and "Only audit documents found in the source (S3)" in text and "ragi worker" in text
    assert n["actions"][0]["target"] == "/settings?tab=policy" and n["actions"][0]["primary"]
    assert all(a["id"] != "run_audit" for a in n["actions"])  # "Run it again" would fail the same way


def test_the_email_carries_the_same_steps(tmp_path):
    from ragintegrity.notifications import Notification, render_email

    steps = too_large_steps(False)
    subject, text, html = render_email(Notification("audit_failed", "critical", "Audit paused: your index is too big to read in one go",
                                                    "body", details=steps), None)
    assert "Audit paused" in subject and "keyword index" in text and "<li>Step 1:" in html and "Only audit documents found" in html


def test_with_the_switch_already_on_the_message_is_about_the_index_and_nothing_is_paused(tmp_path):
    svc, _ = make(tmp_path, source_only=True)
    fail_once(svc)
    assert svc.ledger.list_runs(limit=1)[0]["stats"]["failure"] == {"kind": TOO_LARGE, "source_only": True, "paused": False}
    n = latest_notification(svc)
    assert n["title"] == "Audit failed: your index is too big to read in one go" and "paused" not in n["body"]
    assert "RAGI_AUDIT_SLICE_DOCUMENTS" in " ".join(n["details"]) and "Only audit documents" not in " ".join(n["details"])
    assert svc.audit_pause() is None


def test_other_failures_keep_their_ordinary_message(tmp_path):
    svc, index = make(tmp_path, too_big=False)
    index.fail = {0: (2, RuntimeError("something else broke"))}
    with pytest.raises(RuntimeError):
        svc.run_audit()
    n = latest_notification(svc)
    assert n["title"] == "Audit failed" and "something else broke" in n["body"] and "failure" not in svc.ledger.list_runs(limit=1)[0]["stats"]
    assert svc.audit_pause() is None


# ------------------------------------------------------------------------------------------------- the pause
def test_a_new_whole_audit_waits_while_paused_and_the_overview_says_why(tmp_path):
    svc, index = make(tmp_path)
    fail_once(svc)
    pause = svc.audit_pause()
    assert pause and pause["run_id"] == svc.ledger.list_runs(limit=1)[0]["id"] and pause["steps"] == too_large_steps(False)
    assert "Audit paused" in pause["message"] and "keyword index" in pause["message"]
    with pytest.raises(AuditPaused):
        svc.run_audit()
    with pytest.raises(AuditPaused):
        svc.start_audit_async()
    assert index.scans and len(index.scans) == 1  # the paused audit never touched the customer's index
    assert svc.overview()["audit_pause"]["steps"] == pause["steps"]


def test_the_pause_over_http_is_a_409_with_the_steps_and_force_goes_ahead(tmp_path):
    svc, index = make(tmp_path)
    client = TestClient(create_app(service=svc))
    fail_once(svc)
    r = client.post("/api/audits", json={"wait": True})
    assert r.status_code == 409 and "keyword index" in r.json()["detail"] and "Only audit documents found in the source" in r.json()["detail"]
    assert client.get("/api/overview").json()["audit_pause"]["steps"]
    index.fail.clear()
    r = client.post("/api/audits", json={"wait": True, "force": True})  # a worker on a server has no time limit
    assert r.status_code == 202 and r.json()["status"] == "completed"
    assert client.get("/api/overview").json()["audit_pause"] is None  # a good whole audit lifts the pause


def test_turning_the_switch_on_lifts_the_pause(tmp_path):
    svc, index = make(tmp_path)
    fail_once(svc)
    assert svc.audit_pause() is not None
    svc.settings = svc.settings.model_copy(update={"source_documents_only": True})  # the person turns the setting on
    index.fail.clear()
    assert svc.audit_pause() is None
    assert svc.run_audit().status == "completed"  # and the audit now runs in pieces


def test_a_tenant_or_a_few_documents_still_runs_while_paused(tmp_path):
    svc, index = make(tmp_path)
    fail_once(svc)
    index.fail.clear()
    assert svc.run_audit(scope=Scope(tenant=KEY)).status == "completed"  # the workaround the message used to suggest
    assert svc.audit_pause() is not None  # and it did not change the verdict on the whole index (the last whole audit failed)
    svc.run_audit(scope=Scope(keys=frozenset({(KEY, "d03")})), trigger="repair-verify")


def test_a_machine_without_a_time_limit_never_pauses(tmp_path):
    svc, index = make(tmp_path, limit=None)  # ragi audit on a laptop or a server
    assert not svc.settings.audit_seconds_limit
    fail_once(svc)
    assert svc.ledger.list_runs(limit=1)[0]["stats"]["failure"]["paused"] is False
    assert latest_notification(svc)["title"] == "Audit failed: your index is too big to read in one go"
    assert svc.audit_pause() is None
    index.fail.clear()
    assert svc.run_audit().status == "completed"


def test_the_queue_is_paused_too_and_force_queues_it_for_a_worker(tmp_path):
    svc, index = make(tmp_path, audit_queue=True)
    client = TestClient(create_app(service=svc))
    fail_once(svc)
    assert client.post("/api/audits", json={}).status_code == 409
    assert not [r for r in svc.ledger.active_runs()]  # nothing was queued
    index.fail.clear()
    r = client.post("/api/audits", json={"force": True})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert svc.work("on-a-server")["status"] == "completed"  # a worker with no time limit carries it out
    assert svc.audit_pause() is None


def test_a_partial_audit_is_not_a_pause(tmp_path):
    svc, _ = make(tmp_path, source_only=True, too_big=False)
    svc.connectors.index.fail = {1: (2, TimeoutError("timed out"))}  # stops part-way: resumable, nothing to pause
    assert svc.run_audit().status == "partial"
    assert svc.audit_pause() is None
