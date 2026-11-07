"""End to end through the service: audit -> ledger -> plan -> worker -> verify -> approved cleanup."""

from __future__ import annotations

import pytest

from ragintegrity.config import Settings
from ragintegrity.connectors.factory import build_connectors
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.models import Scope
from ragintegrity.repair import RepairError
from ragintegrity.service import AuditBusy, IntegrityService


def make_service(tmp_path, **overrides) -> IntegrityService:
    settings = Settings(
        _env_file=None, mode="demo", database_url=f"sqlite:///{tmp_path / 'ragi.db'}", grace_minutes=0,
        **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()}, **overrides,
    )
    world = DemoWorld(seed=21, docs_per_tenant=50)
    return IntegrityService(settings, Ledger(settings.database_url), build_connectors(settings, world))


@pytest.fixture()
def svc(tmp_path):
    s = make_service(tmp_path)
    s.bootstrap()
    return s


def test_bootstrap_audit_populates_ledger(svc):
    ov = svc.overview()
    assert ov["documents"]["total"] > 100
    assert ov["issues"]["open"] == sum(ov["issues"]["by_severity"].values()) > 0
    assert ov["latest_full_run"]["stats"]["findings_total"] == ov["issues"]["open"]
    assert ov["query_log_size"] > 0
    docs, total = svc.ledger.list_documents(status="broken")
    assert total > 0 and docs[0]["worst_severity"] in ("critical", "high")


def test_second_audit_is_idempotent_and_resolves_nothing(svc):
    before = svc.ledger.issue_counts()["open"]
    r = svc.run_audit()
    assert r.diff.opened == [] and r.diff.resolved == [] and r.diff.reopened == []
    assert svc.ledger.issue_counts()["open"] == before
    issues, _ = svc.ledger.list_issues(limit=1000)
    assert all(i["occurrences"] == 2 for i in issues)  # same issue ids, not duplicates


def test_issue_resolves_when_fixed_and_reopens_when_it_regresses(svc):
    world = svc.connectors.world
    key = next(k for k, v in world.faults.items() if v["fault"] == "partial")
    iid = next(i["id"] for i in svc.ledger.issues_for_document(*key))
    world._worker_reindex(key)  # someone fixes it out of band
    assert svc.run_audit().diff.resolved == [iid]
    assert svc.ledger.get_issue(iid)["status"] == "resolved"

    world._fault_partial(key)  # regression
    diff = svc.run_audit().diff
    assert [f.issue_id for f in diff.reopened] == [iid]
    issue = svc.ledger.get_issue(iid)
    assert issue["status"] == "open" and issue["reopened_count"] == 1
    events = [e["event"] for e in svc.ledger.issue_events(iid)]
    assert events[:2] == ["reopened", "resolved"] and events[-1] == "opened"


def test_ignored_issue_stays_ignored(svc):
    issue = svc.ledger.list_issues(limit=1)[0][0]
    assert svc.ledger.set_issue_status(issue["id"], "ignored", "known, tracked in JIRA-1")
    svc.run_audit()
    assert svc.ledger.get_issue(issue["id"])["status"] == "ignored"
    assert svc.ledger.get_issue(issue["id"])["ignored_reason"] == "known, tracked in JIRA-1"


def test_scoped_run_does_not_resolve_unrelated_issues(svc):
    before = svc.ledger.issue_counts()["open"]
    key = next(iter(svc.connectors.world.sources))
    svc.run_audit(scope=Scope(keys=frozenset({key})))
    assert svc.ledger.issue_counts()["open"] == before


def test_concurrent_audit_is_rejected(svc):
    assert svc._lock.acquire(blocking=False)
    try:
        with pytest.raises(AuditBusy):
            svc.run_audit()
    finally:
        svc._lock.release()


def test_failed_audit_is_recorded(tmp_path):
    s = make_service(tmp_path)
    s.connectors.world.sources = None  # type: ignore[assignment]  # sabotage
    with pytest.raises(AttributeError):
        s.run_audit()
    run = s.ledger.list_runs(limit=1)[0]
    assert run["status"] == "failed" and run["error"]


def test_full_repair_lifecycle_with_safe_cleanup(svc):
    world = svc.connectors.world
    plan = svc.repairs.create_plan()
    assert plan["status"] == "draft" and plan["summary"]["documents_to_reprocess"] > 0
    s = plan["summary"]
    assert 0 < s["savings_vs_full_reindex_pct"] < 100  # targeted repair, strictly smaller than a blanket re-embed
    assert s["chunks_to_regenerate"] < s["full_corpus"]["chunks"]

    # verifying before triggering is refused
    with pytest.raises(RepairError):
        svc.repairs.verify(plan["id"])

    # two documents have a worker that reports success but writes only half of the chunks
    flaky = [k for k, v in world.faults.items() if v["fault"] == "stale"][:2]
    for k in flaky:
        world.flaky[k] = 1
    points_before = len(world.points)

    plan = svc.repairs.trigger(plan["id"])
    assert plan["status"] == "triggered"
    assert len(world.points) > points_before  # reindex only ADDS vectors; nothing was deleted yet
    stale_key = next(k for k, v in world.faults.items() if v["fault"] == "stale" and k not in flaky)
    old_points = [p for p in world.points_of(stale_key) if world.points[p].payload["source_hash"] != world.sources[stale_key].source_hash]
    assert old_points, "old-version vectors must still exist until cleanup is approved"

    plan = svc.repairs.verify(plan["id"])
    statuses = {(i["tenant_id"], i["document_id"]): i for i in plan["items"]}
    for k in flaky:  # the lying worker is caught by independent verification
        assert statuses[k]["status"] == "failed"
        assert statuses[k]["checks"]["expected_chunks_present"] is False
    assert plan["status"] == "partial"

    # cleanup is blocked for documents that failed verification
    plan = svc.repairs.approve_cleanup(plan["id"])
    assert plan["status"] == "cleanup_triggered"
    for k in flaky:
        # failed documents keep their old vectors: no removal was requested for them
        assert any(world.points[p].payload["source_hash"] != world.sources[k].source_hash for p in world.points_of(k))
    assert not [p for p in old_points if p in world.points]  # verified documents were cleaned

    # retry: the flaky worker succeeds the second time
    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "partial"
    plan = svc.repairs.trigger(plan["id"])
    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] in ("cleanup_pending", "completed")
    if plan["status"] == "cleanup_pending":
        plan = svc.repairs.approve_cleanup(plan["id"])
        plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "completed", [(i["document_id"], i["status"], i["remaining_types"]) for i in plan["items"] if i["status"] != "completed"]

    # the full audit now only has what the plan deliberately did not cover
    svc.run_audit()
    remaining = svc.ledger.issue_counts()
    assert remaining["open"] == 0, svc.ledger.list_issues(limit=50)[0]
    events = [e["event"] for e in svc.repairs.get(plan["id"])["events"]]
    assert events[0] == "created" and "cleanup_triggered" in events and events[-1] == "verified"


def test_cleanup_requires_verification_first(svc):
    plan = svc.repairs.create_plan()
    with pytest.raises(RepairError):
        svc.repairs.approve_cleanup(plan["id"])


def test_plan_selection_and_empty_selection(svc):
    plan = svc.repairs.create_plan(min_severity="critical")
    assert all(i["worst_severity"] == "critical" for i in plan["items"])
    with pytest.raises(RepairError):
        svc.repairs.create_plan(issue_ids=["nope"])


def test_manual_cleanup_policy_never_auto_deletes(tmp_path):
    s = make_service(tmp_path)
    s.bootstrap()
    world = s.connectors.world
    plan = s.repairs.create_plan(types=["stale_embedding"])
    s.repairs.trigger(plan["id"])
    plan = s.repairs.verify(plan["id"])
    assert plan["status"] == "cleanup_pending"
    assert not any(c["phase"] == "cleanup" for c in world.worker_calls)  # waits for an operator


def test_auto_cleanup_policy_removes_after_verification(tmp_path):
    s = make_service(tmp_path, cleanup_policy="auto")
    s.bootstrap()
    plan = s.repairs.create_plan(types=["stale_embedding"])
    s.repairs.trigger(plan["id"])
    plan = s.repairs.verify(plan["id"])
    assert plan["status"] == "cleanup_triggered"
    plan = s.repairs.verify(plan["id"])
    assert plan["status"] == "completed"


def test_recommendations_blast_radius_and_report(svc):
    rec = svc.recommendations()
    assert rec["summary"]["documents_affected"] > 0 and rec["summary"]["estimated_cost_usd"] >= 0

    blast = svc.blast_radius({"type": "config_change", "target": {"embedding_model": "demo-embed-v3"}})
    assert blast["documents"]["affected"] > 100  # nearly every live document uses an older model
    assert blast["queries"]["affected_queries"] > 0 and blast["queries"]["top_documents"]

    current = svc.blast_radius({"type": "open_issues"})
    assert 0 < current["documents"]["affected"] < blast["documents"]["affected"]
    with pytest.raises(ValueError):
        svc.blast_radius({"type": "config_change"})

    md = svc.report("md")
    assert "# RAG integrity report" in md and "stale_embedding" in md
    csv_text = svc.report("csv")
    assert csv_text.splitlines()[0].startswith("tenant_id,document_id")
    data = svc.report("json")
    assert data["documents"] and all(d["issues"] for d in data["documents"])


def test_inspect_document_shows_three_way_view(svc):
    world = svc.connectors.world
    key = next(k for k, v in world.faults.items() if v["fault"] == "superseded")
    view = svc.inspect(*key)
    assert view["source"] and view["manifest"] and view["index"]["points"] > 0
    assert set(view["index"]["by_class"]) >= {"fresh", "stale"}
    assert [f["type"] for f in view["findings"]] == ["superseded_active"]


def test_demo_reset_rebuilds_world(svc):
    first = {k for k in svc.connectors.world.faults}
    svc.demo_reset(seed=99)
    assert {k for k in svc.connectors.world.faults} != first
    assert svc.overview()["documents"]["total"] > 0
