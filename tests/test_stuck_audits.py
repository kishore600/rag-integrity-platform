"""A killed serverless function never records a result.

The run then stays 'running'. It must not keep the Run audit button disabled forever, and a single slow Qdrant request
must fail with a clear message before the platform kills the whole function.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from ragintegrity.config import Settings
from ragintegrity.connectors.qdrant import _explain_qdrant, client_timeout
from ragintegrity.ledger import STALE_RUN_SECONDS, utcnow
from tests.test_service import make_service


def test_an_abandoned_run_stops_disabling_the_audit_button(tmp_path):
    svc = make_service(tmp_path)
    svc.ledger.init()
    stuck = svc.ledger.start_run("full", "api", None)
    assert svc.audit_running is True  # a fresh run really is running

    runs = svc.ledger.t["audit_runs"]
    with svc.ledger.engine.begin() as c:
        c.execute(update(runs).where(runs.c.id == stuck).values(started_at=utcnow() - timedelta(seconds=STALE_RUN_SECONDS + 60)))

    assert svc.audit_running is False  # retired without anyone having to start a new audit
    run = svc.ledger.get_run(stuck)
    assert run["status"] == "failed" and "abandoned" in run["error"] and run["finished_at"]


def test_a_recent_run_is_left_alone(tmp_path):
    svc = make_service(tmp_path)
    svc.ledger.init()
    run_id = svc.ledger.start_run("full", "api", None)
    assert svc.ledger.retire_stale_runs() == 0
    assert svc.ledger.get_run(run_id)["status"] == "running" and svc.audit_running is True


def test_one_qdrant_request_is_bounded_well_inside_the_time_budget():
    quick = Settings(_env_file=None)
    assert client_timeout(quick, fast=False) == 60  # no budget (a long-lived server): the old behaviour
    assert client_timeout(quick, fast=True) == 8  # diagnostics give up quickly
    assert client_timeout(Settings(_env_file=None, max_audit_seconds=50), fast=False) == 30  # serverless: 20 s of headroom
    assert client_timeout(Settings(_env_file=None, max_audit_seconds=15), fast=False) == 10  # never below a sane minimum


def test_a_timeout_explains_the_missing_payload_index():
    msg = _explain_qdrant(TimeoutError("The read operation timed out"))
    assert "timed out" in msg and "payload index" in msg and "source_id" in msg
