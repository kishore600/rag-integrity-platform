"""The background worker: a queue, a loop and a step call that carry the resumable audit through to the end.

The audit itself (slices, checkpoints, ``partial`` when it stops part-way, resuming from the last checkpoint) is tested in
``test_scan_reliability.py``. Here the worker is the one that comes back to a stopped audit, so these tests check that
whatever stops it, the audit ends with exactly the ledger of one that was never interrupted, and that a person is told what is
going on: queued, working, silent, or waiting for a worker that is not there.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.connectors.factory import Connectors
from ragintegrity.ledger import MAX_STALLS, Ledger, iso, utcnow
from ragintegrity.models import Scope
from ragintegrity.service import AuditBusy, IntegrityService
from ragintegrity.worker import Worker
from tests.test_scan_reliability import (
    DOCS,
    KEY,
    PointIndex,
    ledger_state,
    manifest_rows,
    service,
    source_docs,
    world_points,
)
from tests.test_source_only import FakeManifest, FakeSource


def clean_ledger(tmp_path):
    """The ledger of an audit that was never interrupted: the answer every interrupted audit must end with."""
    reference = service(tmp_path, PointIndex(world_points()), name="clean")
    reference.run_audit()
    return ledger_state(reference), reference


def age_heartbeat(svc: IntegrityService, run_id: str, seconds: int = 600) -> None:
    svc.ledger._edit_stats(run_id, lambda s: s["worker"].update(heartbeat_at=iso(utcnow() - timedelta(seconds=seconds))))


def runs(svc: IntegrityService) -> list[dict]:
    return list(reversed(svc.ledger.list_runs(limit=20)))  # oldest first


# ------------------------------------------------------------------------------------- the queue and one stretch of work
def test_a_queued_audit_that_fits_is_done_in_one_stretch(tmp_path):
    expected, _ = clean_ledger(tmp_path)
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    run_id = svc.enqueue_audit()
    assert svc.audit_running and svc.audit_progress()["state"] == "queued" and svc.ledger.get_run(run_id)["status"] == "queued"
    out = svc.work("w1")
    assert out["status"] == "completed" and out["run_id"] == run_id and "next" not in out
    assert not svc.audit_running and svc.audit_progress() is None and svc.work("w1") is None  # nothing left to do
    assert svc.ledger.get_run(run_id)["status"] == "completed" and ledger_state(svc) == expected


def test_a_stopped_audit_queues_its_next_stretch_and_the_worker_finishes_it(tmp_path):
    expected, reference = clean_ledger(tmp_path)
    index = PointIndex(world_points(), fail={1: (2, TimeoutError("timed out"))})  # the second slice stops part-way
    svc = service(tmp_path, index, audit_queue=True)
    svc.enqueue_audit()
    first = svc.work("w1")
    assert first["status"] == "partial" and first["documents_done"] == 4 and first["next"]
    assert svc.audit_running  # the next stretch is waiting in the queue
    progress = svc.audit_progress()
    assert progress["state"] == "queued" and progress["done_documents"] == 4 and progress["total_documents"] == 12
    assert "Paused at a checkpoint: 4 of 12 documents" in progress["message"]
    index.fail.clear()  # the index answers again
    second = svc.work("w2")
    assert second["status"] == "completed" and svc.work("w2") is None
    done = svc.ledger.get_run(second["run_id"])
    assert done["stats"]["scan"]["resumed_from"] == first["run_id"] and done["stats"]["documents_total"] == 12
    assert [r["status"] for r in runs(svc)] == ["partial", "completed"]  # the history keeps what happened
    assert ledger_state(svc) == expected
    assert done["stats"]["health_score"] == reference.ledger.get_run(reference.ledger.list_runs(limit=1)[0]["id"])["stats"]["health_score"]


def test_a_worker_that_dies_is_replaced_and_the_audit_carries_on(tmp_path):
    expected, _ = clean_ledger(tmp_path)
    index = PointIndex(world_points(), fail={1: (3, KeyboardInterrupt())})  # not an Exception: nothing in the audit can catch it
    svc = service(tmp_path, index, audit_queue=True)
    svc.enqueue_audit()
    with pytest.raises(KeyboardInterrupt):
        svc.work("doomed")
    [run] = runs(svc)
    assert run["status"] == "running" and run["stats"]["worker"]["id"] == "doomed"  # it never got to say goodbye
    age_heartbeat(svc, run["id"])
    assert svc.audit_progress()["state"] == "silent"
    index.fail.clear()
    out = svc.work("replacement")  # takes the audit back (the heartbeat stopped) and goes on from the last checkpoint
    assert out["status"] == "completed"
    assert [r["status"] for r in runs(svc)] == ["partial", "completed"]
    assert runs(svc)[0]["stats"]["scan"]["checkpoint"] == [KEY, "d03"] and runs(svc)[1]["stats"]["scan"]["resumed_from"] == run["id"]
    assert ledger_state(svc) == expected


def test_a_dead_worker_with_no_checkpoint_is_failed_and_retried_only_a_few_times(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    run_id = svc.enqueue_audit()
    for attempt in range(MAX_STALLS):
        claimed = svc.ledger.claim_run("doomed")
        assert claimed["id"] == run_id
        age_heartbeat(svc, run_id)
        assert svc.ledger.retire_stale_runs() == 1
        assert svc.ledger.get_run(run_id)["status"] == "failed" and "abandoned" in svc.ledger.get_run(run_id)["error"]
        queued = [r for r in svc.ledger.active_runs() if r["status"] == "queued"]
        if attempt < MAX_STALLS - 1:  # nothing was ever checked, so it counts as a stall; a few are retried
            assert len(queued) == 1
            run_id = queued[0]["id"]
        else:
            assert queued == []  # three in a row: it is left for a person, not retried for ever


def test_an_outage_that_never_ends_stops_after_a_few_stretches_with_no_progress(tmp_path):
    index = PointIndex(world_points(), fail={1: (2, TimeoutError("timed out"))})
    svc = service(tmp_path, index, audit_queue=True)
    svc.enqueue_audit()
    assert svc.work("w")["status"] == "partial"  # got 4 documents done
    index.fail = {i: (0, TimeoutError("still down")) for i in range(50)}  # now nothing can be read
    index.scans.clear()
    nexts = []
    for _ in range(MAX_STALLS + 1):
        out = svc.work("w")
        if out is None:
            break
        assert out["status"] == "partial" and out["documents_done"] == 4  # the checkpoint did not move
        nexts.append(out["next"])
    assert nexts[-1] is None and not svc.audit_running  # it gave up queueing more, and says so by leaving a resumable audit
    assert svc.overview()["resumable_audit"]["documents_done"] == 4
    index.fail.clear()
    assert svc.run_audit(resume=True).status == "completed"  # a person can still resume it


# ------------------------------------------------------------------------------------- what people see
def test_the_queue_over_http_end_to_end(tmp_path):
    expected, _ = clean_ledger(tmp_path)
    index = PointIndex(world_points(), fail={1: (2, TimeoutError("timed out"))})
    svc = service(tmp_path, index, audit_queue=True)
    client = TestClient(create_app(service=svc))
    r = client.post("/api/audits", json={"probe": False})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    ov = client.get("/api/overview").json()
    assert ov["audit_running"] is True and ov["audit_queue"] is True and ov["audit_progress"]["state"] == "queued"
    assert ov["latest_run"]["status"] == "queued" and "options" not in ov["latest_run"]["stats"]  # the request's details stay inside
    assert client.post("/api/audits", json={}).status_code == 409  # one audit at a time, queued or not
    first = client.post("/api/worker/step").json()
    assert first["status"] == "partial" and first["documents_done"] == 4
    assert client.get("/api/overview").json()["audit_progress"]["done_documents"] == 4
    index.fail.clear()
    assert client.post("/api/worker/step").json()["status"] == "completed"
    ov = client.get("/api/overview").json()
    assert ov["audit_running"] is False and ov["audit_progress"] is None and ov["latest_full_run"]["status"] == "completed"
    assert client.post("/api/worker/step").json()["status"] == "idle"
    assert ledger_state(svc) == expected


def test_an_audit_of_one_tenant_still_runs_in_the_request_in_queue_mode(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    client = TestClient(create_app(service=svc))
    r = client.post("/api/audits", json={"tenant": KEY, "wait": True})
    assert r.status_code == 202 and r.json()["status"] == "completed"  # small and scoped: no reason to wait for a worker


def test_nobody_picking_the_audit_up_is_said_out_loud(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    run_id = svc.enqueue_audit()
    assert svc.audit_progress()["state"] == "queued"
    svc.ledger._edit_stats(run_id, lambda s: s.update(queued_at=iso(utcnow() - timedelta(minutes=12))), statuses=("queued",))
    p = svc.audit_progress()
    assert p["state"] == "waiting_for_worker" and "ragi worker" in p["message"] and "/api/worker/step" in p["message"]
    assert "dashboard runs it" in p["message"]  # the page is the worker of last resort, and says so


def drive_like_the_dashboard(client):
    """The loop in frontend/src/hooks/use-queue-driver.ts: step again while a stretch stops part-way and queues the next one."""
    answers = []
    for _ in range(20):
        out = client.post("/api/worker/step").json()
        answers.append(out)
        if not (out["status"] == "partial" and out.get("next")):
            break
    return answers


def test_an_audit_nobody_picked_up_is_finished_by_a_page_that_asks_for_steps(tmp_path):
    expected, _ = clean_ledger(tmp_path)
    svc = service(tmp_path, PointIndex(world_points(), fail={1: (2, TimeoutError("timed out"))}), audit_queue=True)
    client = TestClient(create_app(service=svc))
    run_id = client.post("/api/audits", json={"probe": False}).json()["run_id"]
    svc.ledger._edit_stats(run_id, lambda s: s.update(queued_at=iso(utcnow() - timedelta(minutes=12))), statuses=("queued",))
    assert client.get("/api/overview").json()["audit_progress"]["state"] == "waiting_for_worker"  # this is what makes the page start
    answers = drive_like_the_dashboard(client)
    assert [a["status"] for a in answers] == ["partial", "completed"] and answers[0]["next"]  # the stop was carried on, not left
    ov = client.get("/api/overview").json()
    assert ov["audit_running"] is False and ov["audit_progress"] is None and ledger_state(svc) == expected
    assert client.post("/api/worker/step").json()["status"] == "idle"  # and the page stops by itself


def test_a_page_and_a_worker_never_carry_out_the_same_audit(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    client = TestClient(create_app(service=svc))
    svc.enqueue_audit()
    claimed = svc.ledger.claim_run("real-worker")  # the worker got there first
    assert claimed is not None
    assert client.post("/api/worker/step").json()["status"] == "idle"  # the page finds nothing to take
    assert svc.ledger.get_run(claimed["id"])["status"] == "running" and svc.ledger.claim_run("another-page") is None


def test_a_signed_in_page_can_only_carry_out_its_own_workspaces_audit(tmp_path, monkeypatch):
    from sqlalchemy import select

    from ragintegrity import workspaces

    inner = Settings(_env_file=None, mode="live", source_documents_only=True, audit_slice_documents=4, probe_retrieval=False)
    monkeypatch.setattr(workspaces.WorkspaceManager, "service", lambda self, ws: IntegrityService(
        inner, self.ledger.for_workspace(ws),
        Connectors(FakeSource(source_docs()), FakeManifest(manifest_rows()), PointIndex(world_points())), init_schema=False))
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{(tmp_path / 'pages.db').as_posix()}", secret_key="k" * 40)
    app = create_app(settings=settings)
    origin = {"Origin": "http://testserver"}  # a cookie-authenticated write must say where it comes from
    with TestClient(app) as alice:
        bob = TestClient(app)
        for client, email in ((alice, "alice@example.com"), (bob, "bob@example.com")):
            assert client.post("/api/auth/register", json={"email": email, "password": "a-long-unusual-passphrase"}).status_code == 201
            client.headers.update(origin)
        led = app.state.app_state.ledger
        with led.engine.connect() as conn:
            users = led.t["users"]
            mine = {e: conn.execute(select(users.c.workspace_id).where(users.c.email == e)).scalar_one() for e in ("alice@example.com", "bob@example.com")}
        run_id = led.for_workspace(mine["alice@example.com"]).queue_run("full", "api", None, {"probe": False, "auto": True})
        assert bob.post("/api/worker/step").json()["status"] == "idle"  # not his audit: he cannot carry it out
        assert led.for_workspace(mine["alice@example.com"]).get_run(run_id)["status"] == "queued"
        out = alice.post("/api/worker/step").json()
        assert out["status"] == "completed" and out["run_id"] == run_id


def test_a_second_whole_audit_waits_but_a_repair_check_goes_ahead(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    svc.enqueue_audit()
    with pytest.raises(AuditBusy):
        svc.run_audit()
    with pytest.raises(AuditBusy):
        svc.enqueue_audit()
    svc.run_audit(scope=Scope(keys=frozenset({(KEY, "d03")})), trigger="repair-verify")  # named documents: small, goes ahead


def test_a_queued_audit_is_not_history_and_progress_notes_do_not_overwrite_the_heartbeat(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    run_id = svc.enqueue_audit()
    assert not [e for e in svc.ledger.history() if e["kind"] == "audit"]  # it has not happened yet
    svc.ledger.claim_run("w")
    svc.ledger.touch_run(run_id, "w")
    svc.ledger.set_progress(run_id, "reading the vector index", documents_done=3)
    stats = svc.ledger.list_runs(limit=1)[0]["stats"]
    assert stats["progress"]["documents_done"] == 3 and stats["worker"]["id"] == "w"  # both survive each other


# ------------------------------------------------------------------------------------- the worker process
def test_the_worker_takes_audits_one_after_another_and_then_waits(tmp_path):
    svc = service(tmp_path, PointIndex(world_points()), audit_queue=True)
    worker = Worker(svc.settings, worker_id="w-1", service=svc)
    assert worker.run_once() is None  # nothing waiting
    svc.enqueue_audit()
    assert worker.run_once()["status"] == "completed" and worker.run_once() is None


def test_one_worker_serves_every_workspace_of_the_multi_user_app(tmp_path, monkeypatch):
    from ragintegrity import workspaces

    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}", secret_key="k" * 40)
    ledger = Ledger(settings.database_url)
    ledger.init()
    inner = Settings(_env_file=None, mode="live", source_documents_only=True, audit_slice_documents=4, probe_retrieval=False)
    monkeypatch.setattr(workspaces.WorkspaceManager, "service", lambda self, ws: IntegrityService(
        inner, self.ledger.for_workspace(ws),
        Connectors(FakeSource(source_docs()), FakeManifest(manifest_rows()), PointIndex(world_points())), init_schema=False))
    ids = {ws: ledger.for_workspace(ws).queue_run("full", "api", None, {"probe": False, "auto": True}) for ws in ("ws-one", "ws-two")}
    worker = Worker(settings, worker_id="w-app")
    done = [worker.run_once(), worker.run_once()]
    assert {d["workspace_id"] for d in done} == set(ids) and all(d["status"] == "completed" for d in done)
    assert worker.run_once() is None
    for ws, run_id in ids.items():  # each workspace has its own result, and nothing leaked across
        assert ledger.for_workspace(ws).get_run(run_id)["status"] == "completed"
        assert [r["id"] for r in ledger.for_workspace(ws).list_runs(limit=5)] == [run_id]


def test_a_workspace_that_cannot_be_built_fails_its_audit_visibly(tmp_path, monkeypatch):
    from ragintegrity import workspaces

    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{(tmp_path / 'app2.db').as_posix()}", secret_key="k" * 40)
    ledger = Ledger(settings.database_url)
    ledger.init()
    monkeypatch.setattr(workspaces.WorkspaceManager, "service", lambda self, ws: (_ for _ in ()).throw(ValueError("no connections set")))
    run_id = ledger.for_workspace("ws-x").queue_run("full", "api", None, {"auto": True})
    out = Worker(settings, worker_id="w").run_once()
    assert out["status"] == "failed" and "no connections set" in out["error"]
    run = ledger.for_workspace("ws-x").get_run(run_id)
    assert run["status"] == "failed" and "no connections set" in run["error"]


def test_the_worker_command_exists():
    from ragintegrity.cli import build_parser

    args = build_parser().parse_args(["worker", "--once", "--budget", "120", "--id", "nightly"])
    assert args.once and args.budget == 120 and args.id == "nightly" and args.poll == 10.0


def test_the_documents_in_the_fixture_are_what_the_tests_count_on():
    assert len(DOCS) == 12 and len(source_docs()) == 12  # three slices of four: a partial audit of 4 is one slice done
