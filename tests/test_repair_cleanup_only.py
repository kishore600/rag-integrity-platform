"""A plan that only removes vectors (orphans, duplicates, superseded, wrong tenant) must be able to progress.

It has nothing to send to the customer's worker, so it used to be stuck: trigger refused it, verify wanted a trigger first, and
approve-cleanup wanted a verified plan.
"""

from __future__ import annotations

import pytest

from ragintegrity.repair import RepairError
from tests.test_service import make_service


@pytest.fixture()
def svc(tmp_path):
    s = make_service(tmp_path)
    s.bootstrap()
    return s


def test_a_cleanup_only_plan_goes_from_draft_to_completed(svc):
    plan = svc.repairs.create_plan(types=["orphan_vector"])
    assert plan["status"] == "draft" and plan["items"] and all(not it["actions"] for it in plan["items"])
    world = svc.connectors.world
    points_before = len(world.points)

    plan = svc.repairs.trigger(plan["id"])  # nothing to send to a worker: it goes straight to verification
    assert plan["status"] == "cleanup_pending" and world.worker_calls == []
    assert any(e["event"] == "nothing_to_reindex" for e in plan["events"])
    assert all(it["status"] == "awaiting_cleanup" for it in plan["items"])
    assert len(world.points) == points_before  # nothing is removed before the operator approves

    plan = svc.repairs.approve_cleanup(plan["id"])
    assert plan["status"] == "cleanup_triggered" and len(world.points) < points_before  # the worker removed the orphans
    assert [c["phase"] for c in world.worker_calls] == ["cleanup"]

    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "completed"


def test_verify_can_be_the_first_step_of_a_cleanup_only_plan(svc):
    plan = svc.repairs.create_plan(types=["orphan_vector"])
    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "cleanup_pending"


def test_a_plan_with_reindex_work_still_needs_a_trigger_before_verify(svc):
    plan = svc.repairs.create_plan(types=["missing_embedding"])
    assert any(it["actions"] for it in plan["items"])
    with pytest.raises(RepairError, match="Trigger the plan before verifying"):
        svc.repairs.verify(plan["id"])
    with pytest.raises(RepairError, match="Cleanup can only be approved"):
        svc.repairs.approve_cleanup(plan["id"])


def test_the_automatic_policy_still_removes_after_verification(tmp_path):
    s = make_service(tmp_path, cleanup_policy="auto")
    s.bootstrap()
    world = s.connectors.world
    before = len(world.points)
    plan = s.repairs.trigger(s.repairs.create_plan(types=["orphan_vector"])["id"])
    assert plan["status"] == "cleanup_triggered" and len(world.points) < before


def test_a_finished_cleanup_only_plan_cannot_be_triggered_again(svc):
    plan = svc.repairs.create_plan(types=["orphan_vector"])
    plan = svc.repairs.trigger(plan["id"])
    with pytest.raises(RepairError, match="only draft, partial or failed"):
        svc.repairs.trigger(plan["id"])  # it is cleanup_pending now
