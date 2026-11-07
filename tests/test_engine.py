"""The engine must find exactly the faults injected into the demo world - no more, no less."""

from __future__ import annotations

from collections import defaultdict

from ragintegrity.demo.world import TARGET_FP, DemoIndex, DemoManifest, DemoSource, DemoWorld
from ragintegrity.engine.audit import AuditOptions, run_reconciliation
from ragintegrity.models import IssueType, Scope


def _found(result):
    by_doc = defaultdict(set)
    for f in result.findings:
        by_doc[f.key].add(f.type.value)
    return by_doc


def test_findings_match_injected_faults_exactly(world, connectors, opts):
    result = run_reconciliation(*connectors, opts)
    found = _found(result)

    expected = {key: set(info["types"]) for key, info in world.faults.items()}
    assert found == expected, {
        "missing": {k: v for k, v in expected.items() if found.get(k) != v},
        "unexpected": {k: v for k, v in found.items() if k not in expected or expected[k] != v},
    }


def test_healthy_documents_have_no_findings(world, connectors, opts):
    result = run_reconciliation(*connectors, opts)
    healthy = [s for s in result.summaries if s.status == "healthy"]
    assert len(healthy) == len(world.sources) - len([k for k in world.faults if k in world.sources])
    assert result.stats["health_score"] < 100


def test_false_success_is_critical(world, connectors, opts):
    result = run_reconciliation(*connectors, opts)
    claimed = [f for f in result.findings
               if f.type == IssueType.MISSING_EMBEDDING and f.evidence["pipeline_reported_success"]]
    assert claimed and all(f.severity.value == "critical" for f in claimed)
    never = [f for f in result.findings
             if f.type == IssueType.MISSING_EMBEDDING and not f.evidence["pipeline_reported_success"]]
    assert never and all(f.severity.value == "high" for f in never)


def test_orphans_are_probed_and_escalated(world, connectors, opts):
    result = run_reconciliation(*connectors, opts)
    orphans = [f for f in result.findings if f.type == IssueType.ORPHAN_VECTOR]
    assert orphans
    for f in orphans:
        probe = f.evidence["retrieval_probe"]
        assert probe["reachable"] and probe["rank"] == 1
        assert f.severity.value == "critical"
        assert f.evidence["removal_count"] > 0


def test_stats_and_document_status_reflect_probe_escalations(world, connectors, opts):
    """A confirmed probe escalates severities after reconciliation; stats and statuses must follow."""
    result = run_reconciliation(*connectors, opts)
    sev = defaultdict(int)
    for f in result.findings:
        sev[f.severity.value] += 1
    assert {k: v for k, v in result.stats["findings_by_severity"].items() if v} == dict(sev)
    assert result.stats["findings_by_severity"]["critical"] > 9  # orphans were escalated from high
    worst = {s.key: s.worst_severity for s in result.summaries}
    for f in result.findings:
        if f.type == IssueType.SUPERSEDED_ACTIVE and f.severity.value == "high":
            summary = next(s for s in result.summaries if s.key == f.key)
            assert summary.status == "broken" and worst[f.key] == "high"


def test_tenant_mismatch_is_critical_and_names_expected_tenant(world, connectors, opts):
    result = run_reconciliation(*connectors, opts)
    [f] = [f for f in result.findings if f.type == IssueType.TENANT_MISMATCH]
    assert f.severity.value == "critical"
    assert f.evidence["expected_tenants"]


def test_scoped_run_only_reports_requested_documents(world, connectors, opts):
    key = next(k for k, v in world.faults.items() if v["fault"] == "stale")
    result = run_reconciliation(*connectors, opts, scope=Scope(keys=frozenset({key})))
    assert {f.key for f in result.findings} == {key}
    assert [s.key for s in result.summaries] == [key]


def test_documents_still_being_ingested_are_not_flagged():
    world = DemoWorld(seed=3, docs_per_tenant=20, now=_now(), faults=False)
    key = sorted(world.sources)[0]
    world._drop_points(key)
    world.manifest[key].processing_status = "processing"
    world.manifest[key].updated_at = _iso(_now())
    opts = AuditOptions(target=TARGET_FP, now=_now(), grace_minutes=10, probe=False)
    conns = (DemoSource(world), DemoManifest(world), DemoIndex(world))
    result = run_reconciliation(*conns, opts)
    assert not result.findings
    assert next(s for s in result.summaries if s.key == key).status == "pending"

    # ...but a job stuck for hours is a finding
    world.manifest[key].updated_at = "2026-11-06T00:00:00Z"
    stuck = run_reconciliation(*conns, opts)
    assert [f.type for f in stuck.findings] == [IssueType.MISSING_EMBEDDING]
    assert "stuck_in_flight_since" in stuck.findings[0].evidence


def test_clean_world_has_perfect_score():
    world = DemoWorld(seed=5, docs_per_tenant=25, now=_now(), faults=False)
    conns = (DemoSource(world), DemoManifest(world), DemoIndex(world))
    result = run_reconciliation(*conns, AuditOptions(target=TARGET_FP, check_vectors=True, now=_now()))
    assert result.findings == []
    assert result.stats["health_score"] == 100.0


def test_partial_index_found_without_a_chunk_manifest(world, connectors, opts):
    """Without chunk ids or counts, gaps in chunk_index still reveal a partial index (lower confidence)."""
    key = next(k for k, v in world.faults.items() if v["fault"] == "partial")
    world.chunk_manifest.pop(key)
    world.manifest[key].expected_chunk_count = None
    # keep only the first and last chunk so there is a visible gap
    pts = sorted(world.points_of(key), key=lambda p: world.points[p].payload["chunk_index"])
    for pid in pts[1:-1]:
        del world.points[pid]
    result = run_reconciliation(*connectors, opts, scope=Scope(keys=frozenset({key})))
    partial = [f for f in result.findings if f.type == IssueType.PARTIAL_INDEX]
    assert partial and partial[0].evidence["method"] in ("index_gaps", "expected_chunk_count")


def _now():
    from tests.conftest import NOW
    return NOW


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def test_target_fingerprint_dimension_mismatch_flags_collection():
    from ragintegrity.models import Fingerprint
    world = DemoWorld(seed=5, docs_per_tenant=10, now=_now(), faults=False)
    conns = (DemoSource(world), DemoManifest(world), DemoIndex(world))
    target = Fingerprint(**{**TARGET_FP.to_dict(), "embedding_dim": 1536})
    result = run_reconciliation(*conns, AuditOptions(target=target, now=_now(), probe=False))
    crit = [f for f in result.findings if f.severity.value == "critical" and f.document_id == "*"]
    assert crit and crit[0].type == IssueType.PIPELINE_DRIFT
