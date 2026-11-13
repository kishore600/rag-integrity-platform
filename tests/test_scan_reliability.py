"""Feature 2, index completeness and scan reliability: results must stay trustworthy when the index is large and the scan is not.

The rule every test here comes back to: an incomplete scan is never proof that anything is missing. A document is judged only
after the part of the index that could hold its vectors has been read completely. When a scan stops, what was finished is
reported (and is final), what was not is not claimed, and the run says so: completed, partial, failed or in progress.
"""

from __future__ import annotations

import hashlib

import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from ragintegrity.config import Settings
from ragintegrity.connectors.base import AuditTimeout, ScanStats
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.resilience import call_with_retry, classify
from ragintegrity.engine.audit import AuditOptions, PartialAudit, run_reconciliation
from ragintegrity.ledger import Ledger
from ragintegrity.models import Fingerprint, IndexedChunk, ManifestRow, SourceDoc
from ragintegrity.service import IntegrityService
from tests.test_source_only import FakeManifest, FakeSource

DOCS = [f"d{i:02d}" for i in range(12)]  # three slices of four documents
KEY = "default"


def sha(doc: str) -> str:
    return hashlib.sha256(doc.encode()).hexdigest()


def source_docs(docs=DOCS) -> list[SourceDoc]:
    return [SourceDoc(KEY, d, f"s3://b/{d}.pdf", source_hash=sha(d), size_bytes=1) for d in docs]


def manifest_rows(docs=DOCS) -> list[ManifestRow]:
    return [ManifestRow(KEY, d, source_uri=f"s3://b/{d}.pdf", source_hash=sha(d), processing_status="success",
                        expected_chunk_count=3, indexed_chunk_count=3) for d in docs]


def point(doc: str, k: int, *, h: str | None = None, tag: str = "") -> IndexedChunk:
    return IndexedChunk("c", f"{doc}-{k}{tag}", KEY, doc, chunk_id=f"{doc}#{k}", chunk_index=k, source_hash=h or sha(doc),
                        fingerprint=Fingerprint(), present_fields=frozenset({"document_id", "source_hash"}))


def world_points(docs=DOCS, partial=("d09",)) -> list[IndexedChunk]:
    """A corpus with one of each fault: d03 never embedded, d05 stale, d07 duplicated, d09 (and others in ``partial``) half indexed."""
    points = []
    for d in docs:
        if d == "d03":
            continue
        for k in range(2 if d in partial else 3):
            points.append(point(d, k, h=sha("older " + d) if d == "d05" else None))
        if d == "d07":
            points.append(point(d, 0, tag="-again"))
    return points


FAULTS = {(KEY, "d03"): "missing_embedding", (KEY, "d05"): "stale_embedding", (KEY, "d07"): "duplicate_chunk", (KEY, "d09"): "partial_index"}


class PointIndex:
    """An index over a list of points. ``fail={n: (after_points, error)}`` makes the n-th scan raise after that many points."""

    def __init__(self, points, fail=None):
        self.points, self.fail, self.scans = list(points), dict(fail or {}), []
        self.deadline = None
        self.scan_stats = ScanStats()
        self.on_progress = None  # the engine hooks a progress note here, as it does on the real connector

    def collections(self):
        return ["c"]

    def vector_sizes(self):
        return {"c": 3}

    def estimated_points(self):
        self.scan_stats.estimated_total = len(self.points)
        return len(self.points)

    def probe(self, *a, **k):
        return None

    def scan(self, scope=None, with_vectors=False):
        call = len(self.scans)
        self.scans.append(scope)
        if self.on_progress is not None:
            self.on_progress(self.scan_stats)
        after, error = self.fail.get(call, (None, None))
        sent = 0
        for p in self.points:
            if scope is None or scope.is_full or scope.matches((p.tenant_id or KEY, p.document_id)):
                if error is not None and sent >= after:
                    raise error
                sent += 1
                yield p
        if error is not None:
            raise error


def opts(**kw) -> AuditOptions:
    return AuditOptions(source_only=True, slice_size=4, probe=False, required_fields=["document_id"], **kw)


def run(points=None, docs=DOCS, **kw):
    return run_reconciliation(FakeSource(source_docs(docs)), FakeManifest(manifest_rows(docs)),
                              PointIndex(world_points(docs) if points is None else points), opts(**kw))


def found(result) -> dict:
    out: dict = {}
    for f in result.findings:
        out.setdefault(f.key, set()).add(f.type.value)
    return out


# ------------------------------------------------------------------------------------- reading the index in slices
def test_a_sliced_scan_finds_exactly_what_one_pass_over_the_whole_index_finds():
    full = run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), PointIndex(world_points()),
                              AuditOptions(probe=False, required_fields=["document_id"]))
    index = PointIndex(world_points())
    sliced = run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), index, opts())
    one = run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), PointIndex(world_points()),
                             AuditOptions(source_only=True, slice_size=1000, probe=False, required_fields=["document_id"]))
    assert found(sliced) == found(full) == found(one) == {k: {v} for k, v in FAULTS.items()}
    assert {s.key: s.status for s in sliced.summaries} == {s.key: s.status for s in full.summaries}
    for key in ("documents_total", "findings_total", "findings_by_type", "findings_by_severity", "health_score"):
        assert sliced.stats[key] == full.stats[key] == one.stats[key], key
    assert len(index.scans) == 3 and sliced.stats["scan"]["slices_total"] == 3  # one filtered pass per slice of four documents
    assert sliced.stats["scan"]["status"] == "completed" and sliced.stats["scan"]["complete"] is True
    assert sliced.stats["scan"]["percent"] == 100.0 and sliced.stats["scan"]["points_scanned"] == len(world_points())


def test_every_slice_is_handed_over_the_moment_it_is_complete_and_the_collection_checks_come_last():
    got = []
    run(target=Fingerprint(embedding_dim=8), on_slice=got.append)  # the collection holds 3-dimensional vectors: a mismatch
    assert [(s.index, s.total, s.final) for s in got] == [(1, 3, False), (2, 3, False), (3, 3, False), (0, 3, True)]
    assert [s.documents_done for s in got[:3]] == [4, 8, 12]
    assert [s.last_key for s in got[:3]] == [(KEY, "d03"), (KEY, "d07"), (KEY, "d11")]
    assert got[0].carry["findings_by_type"] == {"missing_embedding": 1} and got[2].carry["documents_by_status"]["broken"] == 3
    last = got[3]
    assert last.scope.keys == frozenset({("*", "*")}) and [f.type.value for f in last.findings] == ["pipeline_drift"]
    assert last.findings[0].severity.value == "critical"


# ------------------------------------------------------------------------------------- an incomplete scan proves nothing
def test_a_scan_that_stops_part_way_reports_only_the_documents_it_finished():
    index = PointIndex(world_points(), fail={1: (5, TimeoutError("Qdrant timed out"))})  # the second slice dies after 5 points
    got = []
    with pytest.raises(PartialAudit) as stopped:
        run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), index, opts(on_slice=got.append))
    pa = stopped.value
    assert pa.scan["status"] == "partial" and pa.scan["provisional"] is True and pa.scan["complete"] is False
    assert (pa.scan["slices_done"], pa.scan["slices_total"], pa.scan["documents_done"], pa.scan["documents_total"]) == (1, 3, 4, 12)
    assert pa.scan["percent"] == 33.3 and pa.scan["checkpoint"] == [KEY, "d03"] and "timed out" in pa.scan["stopped_because"]
    # the key property: documents whose part of the index was not read completely get NO verdict. Not "missing", nothing.
    assert {s.key for s in pa.result.summaries} == {(KEY, f"d{i:02d}") for i in range(4)}
    assert found(pa.result) == {(KEY, "d03"): {"missing_embedding"}}
    assert [s.index for s in got] == [1]  # only the finished slice was handed over
    assert pa.result.stats["documents_total"] == 4 and pa.carry["findings_by_type"] == {"missing_embedding": 1}


def test_nothing_finished_means_the_audit_failed_not_partial():
    index = PointIndex(world_points(), fail={0: (2, ConnectionError("connection reset"))})
    got = []
    with pytest.raises(ConnectionError) as failed:
        run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), index, opts(on_slice=got.append))
    snap = failed.value.scan_snapshot
    assert snap["status"] == "failed" and snap["slices_done"] == 0 and snap["points_scanned"] == 2 and got == []


def test_an_unsliced_scan_that_stops_reports_nothing_at_all_and_says_how_far_it_got():
    index = PointIndex(world_points(), fail={0: (7, TimeoutError("timed out"))})
    with pytest.raises(TimeoutError) as failed:
        run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), index,
                           AuditOptions(probe=False, required_fields=["document_id"]))  # the whole index in one pass
    snap = failed.value.scan_snapshot
    assert snap["status"] == "failed" and snap["points_scanned"] == 7 and snap["estimated_total"] == len(world_points())
    assert snap["percent"] == round(100 * 7 / len(world_points()), 1) and snap["mode"] == "single_pass"


def test_a_partial_scan_never_reports_a_collection_level_problem_it_could_not_check():
    index = PointIndex(world_points(), fail={1: (0, TimeoutError("timed out"))})
    with pytest.raises(PartialAudit) as stopped:
        run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), index, opts(target=Fingerprint(embedding_dim=8)))
    assert not [f for f in stopped.value.result.findings if f.key == ("*", "*")]  # those need the whole index


# ------------------------------------------------------------------------------------- resuming from the last checkpoint
def test_a_resumed_scan_skips_the_finished_slices_and_carries_the_totals_over():
    with pytest.raises(PartialAudit) as stopped:
        run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()),
                           PointIndex(world_points(), fail={1: (0, TimeoutError("timed out"))}), opts())
    first = stopped.value
    index = PointIndex(world_points())
    second = run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), index,
                                opts(resume_after=(KEY, "d03"), carry=first.carry, resumed_from="run-1"))
    assert len(index.scans) == 2  # slices two and three only
    assert found(second) == {(KEY, "d05"): {"stale_embedding"}, (KEY, "d07"): {"duplicate_chunk"}, (KEY, "d09"): {"partial_index"}}
    assert second.stats["documents_total"] == 12 and second.stats["findings_total"] == 4  # the first run's d03 is in the totals
    assert second.stats["findings_by_type"] == {"missing_embedding": 1, "stale_embedding": 1, "duplicate_chunk": 1, "partial_index": 1}
    scan = second.stats["scan"]
    assert scan["status"] == "completed" and scan["documents_done"] == 12 and scan["resumed_from"] == "run-1"
    assert "isolation" not in second.stats  # built from the later slices only: left to the next full audit
    clean = run()
    assert second.stats["health_score"] == clean.stats["health_score"]  # the same answer as an audit that was never interrupted


# ------------------------------------------------------------------------------------- the same through the service and the ledger
def service(tmp_path, index, docs=DOCS, name="ledger", **settings) -> IntegrityService:
    s = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{(tmp_path / (name + '.db')).as_posix()}",
                 source_documents_only=True, audit_slice_documents=4, probe_retrieval=False, **settings)
    return IntegrityService(s, Ledger(s.database_url), Connectors(FakeSource(source_docs(docs)), FakeManifest(manifest_rows(docs)), index))


def ledger_state(svc) -> tuple[dict, dict]:
    issues = {i["id"]: (i["document_id"], i["type"], i["status"]) for i in svc.ledger.list_issues(status="all", limit=500)[0]}
    docs = {(d["tenant_id"], d["document_id"]): d["status"] for d in svc.ledger.list_documents(limit=500)[0]}
    return issues, docs


def test_a_stopped_audit_is_recorded_as_partial_and_resuming_it_gives_the_same_ledger_as_a_clean_audit(tmp_path):
    index = PointIndex(world_points(), fail={1: (2, TimeoutError("timed out"))})
    svc = service(tmp_path, index)
    partial = svc.run_audit()
    assert partial.status == "partial"
    run = svc.ledger.get_run(partial.run_id)
    assert run["status"] == "partial" and "4 of 12 documents" in run["error"] and "Resume" in run["error"]
    assert run["stats"]["scan"]["checkpoint"] == [KEY, "d03"]
    issues, docs = ledger_state(svc)
    assert {v[0] for v in issues.values()} == {"d03"} and sorted(d for _, d in docs) == ["d00", "d01", "d02", "d03"]  # only what was finished
    ov = svc.overview()
    assert ov["resumable_audit"]["documents_done"] == 4 and ov["resumable_audit"]["percent"] == 33.3
    assert ov["latest_full_run"] is None  # a partial audit is not a completed full audit: it does not feed the trend or the score

    index.fail.clear()  # the index is reachable again
    done = svc.run_audit(resume=True)
    assert done.status == "completed" and done.stats["resume"]["resumed_from"] == partial.run_id
    assert done.stats["documents_total"] == 12 and done.stats["scan"]["resumed_from"] == partial.run_id
    assert svc.overview()["resumable_audit"] is None
    assert svc.ledger.get_run(partial.run_id)["status"] == "partial"  # history keeps what happened

    clean = service(tmp_path, PointIndex(world_points()), name="clean")
    reference = clean.run_audit()
    assert ledger_state(svc) == ledger_state(clean)  # exactly the ledger of an audit that was never interrupted
    assert done.stats["health_score"] == reference.stats["health_score"] and done.stats["findings_total"] == 4


def test_a_resume_that_still_cannot_reach_the_index_keeps_the_checkpoint(tmp_path):
    index = PointIndex(world_points(), fail={1: (0, TimeoutError("timed out"))})
    svc = service(tmp_path, index)
    first = svc.run_audit()
    index.fail = {0: (0, TimeoutError("still down"))}  # on the resume the next slice is scan number 0
    index.scans.clear()
    again = svc.run_audit(resume=True)
    assert again.status == "partial" and again.stats["scan"]["checkpoint"] == [KEY, "d03"]
    assert svc.ledger.latest_resumable_run()["id"] == again.run_id and first.run_id != again.run_id
    issues, docs = ledger_state(svc)
    assert sorted(d for _, d in docs) == ["d00", "d01", "d02", "d03"]  # still only the finished slice, nothing was lost or invented


def test_a_process_killed_mid_audit_leaves_a_run_that_becomes_partial_and_can_be_resumed(tmp_path):
    """A serverless function killed at its time limit never records a result. Its last checkpoint must not be lost."""
    index = PointIndex(world_points(), fail={1: (3, KeyboardInterrupt())})  # not an Exception: nothing in the audit can catch it
    svc = service(tmp_path, index)
    with pytest.raises(KeyboardInterrupt):
        svc.run_audit()
    [run] = svc.ledger.list_runs(limit=5)
    assert run["status"] == "running"
    assert svc.ledger.retire_stale_runs(0) == 1  # what the next request does once the run is old enough
    run = svc.ledger.get_run(run["id"])
    assert run["status"] == "partial" and run["stats"]["scan"]["checkpoint"] == [KEY, "d03"] and "Resume" in run["error"]
    assert run["stats"]["documents_total"] == 4 and run["stats"]["findings_by_type"] == {"missing_embedding": 1}
    assert svc.ledger.latest_resumable_run()["id"] == run["id"]

    index.fail.clear()
    done = svc.run_audit(resume=True)
    assert done.status == "completed" and ledger_state(svc) == ledger_state(
        (lambda c: (c.run_audit(), c)[1])(service(tmp_path, PointIndex(world_points()), name="clean")))


def test_a_completed_audit_after_a_partial_one_makes_it_history(tmp_path):
    index = PointIndex(world_points(), fail={1: (0, TimeoutError("timed out"))})
    svc = service(tmp_path, index)
    assert svc.run_audit().status == "partial"
    index.fail.clear()
    assert svc.run_audit().status == "completed"  # an ordinary full audit, not a resume
    assert svc.ledger.latest_resumable_run() is None and svc.overview()["resumable_audit"] is None
    nothing = svc.run_audit(resume=True)  # asked to resume, but there is nothing to continue: a full audit
    assert nothing.status == "completed" and "resume" not in nothing.stats and nothing.stats["scan"]["resumed_from"] is None


def test_documents_that_vanish_between_the_stop_and_the_resume_are_cleaned_up_but_finished_ones_are_left_alone(tmp_path):
    docs_before = DOCS
    svc = service(tmp_path, PointIndex(world_points(partial=("d09", "d10"))), docs=docs_before)
    svc.run_audit()  # a complete audit: d09 and d10 are half indexed
    assert {v[0] for v in ledger_state(svc)[0].values() if v[2] == "open"} == {"d03", "d05", "d07", "d09", "d10"}

    gone = [d for d in DOCS if d != "d10"]  # d10 is deleted everywhere: source, manifest and index
    index = PointIndex([p for p in world_points(partial=("d09",)) if p.document_id != "d10"], fail={1: (0, TimeoutError("timed out"))})
    svc.connectors.source, svc.connectors.manifest, svc.connectors.index = FakeSource(source_docs(gone)), FakeManifest(manifest_rows(gone)), index
    assert svc.run_audit().status == "partial"
    assert any(v[0] == "d10" and v[2] == "open" for v in ledger_state(svc)[0].values())  # not swept: an incomplete audit proves nothing
    index.fail.clear()
    assert svc.run_audit(resume=True).status == "completed"
    issues, docs = ledger_state(svc)
    assert [v for v in issues.values() if v[0] == "d10"][0][2] == "resolved" and (KEY, "d10") not in docs
    assert (KEY, "d03") in docs and any(v[0] == "d03" and v[2] == "open" for v in issues.values())  # the finished slice is untouched


def test_a_complete_sliced_audit_closes_the_documents_that_exist_nowhere_any_more(tmp_path):
    svc = service(tmp_path, PointIndex(world_points(partial=("d09", "d10"))))
    svc.run_audit()
    gone = [d for d in DOCS if d != "d10"]
    svc.connectors.source, svc.connectors.manifest = FakeSource(source_docs(gone)), FakeManifest(manifest_rows(gone))
    svc.connectors.index = PointIndex([p for p in world_points(partial=("d09",)) if p.document_id != "d10"])
    result = svc.run_audit()
    issues, docs = ledger_state(svc)
    assert result.status == "completed" and result.diff.to_json()["resolved"] >= 1
    assert [v for v in issues.values() if v[0] == "d10"][0][2] == "resolved" and (KEY, "d10") not in docs


def test_a_run_that_finished_no_slice_is_failed_and_changes_nothing(tmp_path):
    svc = service(tmp_path, PointIndex(world_points(), fail={0: (1, ConnectionError("connection refused"))}))
    with pytest.raises(ConnectionError):
        svc.run_audit()
    [run] = svc.ledger.list_runs(limit=5)
    assert run["status"] == "failed" and run["stats"]["scan"]["status"] == "failed" and run["stats"]["scan"]["slices_done"] == 0
    assert svc.ledger.list_issues(status="all")[1] == 0 and svc.ledger.list_documents()[1] == 0 and svc.ledger.latest_resumable_run() is None


def test_the_checkpoint_survives_every_later_progress_note(tmp_path):
    notes = []
    index = PointIndex(world_points(), fail={1: (1, TimeoutError("timed out"))})
    svc = service(tmp_path, index)
    real = svc.ledger.set_progress
    svc.ledger.set_progress = lambda run_id, phase, **info: (notes.append((phase, info)), real(run_id, phase, **info))[1]
    svc.run_audit()
    after_first = [i for p, i in notes[[p for p, _ in notes].index("recorded a slice of the audit") + 1:]]
    assert after_first and all(i.get("checkpoint") == [KEY, "d03"] and i.get("carry") for i in after_first)  # never dropped
    last = [i for p, i in notes if p == "recorded a slice of the audit"][-1]
    assert last["percent"] == 33.3 and last["documents_done"] == 4 and last["documents_total"] == 12 and last["slices_total"] == 3


# ------------------------------------------------------------------------------------- retry, backoff and rate limits
class HttpError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f"HTTP {status}")
        self.status_code, self.headers = status, headers or {}


@pytest.mark.parametrize("error, retry", [
    (HttpError(429), True), (HttpError(503), True), (HttpError(500), True), (HttpError(502), True), (HttpError(504), True),
    (HttpError(408), True), (HttpError(400), False), (HttpError(401), False), (HttpError(403), False), (HttpError(404), False),
    (TimeoutError("x"), True), (ConnectionResetError("x"), True), (RuntimeError("read operation timed out"), True),
    (RuntimeError("Too Many Requests"), True), (ValueError("bad value"), False), (KeyError("x"), False),
])
def test_only_failures_that_can_pass_are_retried(error, retry):
    assert classify(error)[0] is retry


def flaky(errors):
    calls = iter(errors)

    def fn():
        e = next(calls, None)
        if e is not None:
            raise e
        return "page"
    return fn


def test_backoff_doubles_with_jitter_and_stops_at_the_cap():
    delays: list[float] = []
    stats = ScanStats()
    assert call_with_retry(flaky([TimeoutError()] * 3), stats=stats, attempts=5, base_delay=0.5, max_delay=1.5,
                           sleep=delays.append, jitter=lambda: 1.0) == "page"
    assert delays == [0.5, 1.0, 1.5]  # 0.5, 1.0, then 2.0 capped at 1.5
    assert (stats.retries, stats.recovered_errors, stats.unrecoverable_errors) == (3, 1, 0) and stats.waited_seconds == 3.0
    half: list[float] = []
    call_with_retry(flaky([TimeoutError()]), base_delay=1.0, sleep=half.append, jitter=lambda: 0.0)
    assert half == [0.5]  # full jitter range is 50% to 100% of the step


def test_a_rate_limit_answer_is_honoured_and_counted():
    delays: list[float] = []
    stats = ScanStats()
    call_with_retry(flaky([HttpError(429, {"Retry-After": "7"})]), stats=stats, sleep=delays.append)
    assert delays == [7.0] and stats.rate_limited == 1 and stats.retries == 1
    huge: list[float] = []
    call_with_retry(flaky([HttpError(429, {"retry-after": "9999"})]), sleep=huge.append)
    assert huge == [60.0]  # a server cannot make the audit wait for an hour


def test_a_refusal_is_not_retried_and_retries_run_out():
    for refusal in (HttpError(403), HttpError(400), HttpError(404)):
        stats = ScanStats()
        calls: list[int] = []

        def refused(e=refusal, seen=calls):
            seen.append(1)
            raise e

        with pytest.raises(HttpError):
            call_with_retry(refused, stats=stats, sleep=lambda s: None)
        assert len(calls) == 1 and stats.retries == 0 and stats.unrecoverable_errors == 1
    stats = ScanStats()
    with pytest.raises(HttpError):
        call_with_retry(flaky([HttpError(503)] * 9), stats=stats, attempts=4, sleep=lambda s: None)
    assert (stats.retries, stats.unrecoverable_errors, stats.recovered_errors) == (3, 1, 0)


def test_the_time_budget_is_never_slept_past_and_a_timeout_of_the_audit_is_never_retried():
    import time

    slept: list[float] = []
    stats = ScanStats()
    with pytest.raises(TimeoutError):
        call_with_retry(flaky([TimeoutError()] * 3), stats=stats, deadline=time.monotonic() + 0.1, base_delay=5.0, sleep=slept.append)
    assert slept == [] and stats.unrecoverable_errors == 1  # the wait would pass the deadline: fail now, with the real reason
    calls = []
    with pytest.raises(AuditTimeout):
        call_with_retry(lambda: (calls.append(1), (_ for _ in ()).throw(AuditTimeout("out of time")))[1], sleep=slept.append)
    assert len(calls) == 1


# ------------------------------------------------------------------------------------- the real connector over a flaky client
class FlakyClient:
    """A Qdrant client whose scroll fails the way a busy cluster does: timeouts, rate limits, an overloaded node."""

    def __init__(self, inner, plan):
        self.inner, self.plan, self.calls = inner, list(plan), 0

    def scroll(self, **kw):
        err = self.plan[self.calls] if self.calls < len(self.plan) else None
        self.calls += 1
        if err is not None:
            raise err
        return self.inner.scroll(**kw)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def local_collection(name="c") -> QdrantClient:
    client = QdrantClient(":memory:")
    client.create_collection(name, vectors_config=qm.VectorParams(size=3, distance=qm.Distance.COSINE))
    client.upsert(name, points=[
        qm.PointStruct(id=i + 1, vector=[1.0, 0.0, 0.0], payload={
            "document_id": p.document_id, "source_hash": p.source_hash, "chunk_id": p.chunk_id, "chunk_index": p.chunk_index})
        for i, p in enumerate(world_points())])
    return client


def qdrant_index(client, page=5) -> QdrantIndex:
    idx = QdrantIndex(Settings(_env_file=None, qdrant_collections="c", qdrant_page_size=page), client=client)
    idx._sleep = lambda s: None  # no real waiting in a test
    return idx


@pytest.mark.parametrize("sliced", [True, False], ids=["sliced", "one-pass"])
def test_a_scan_over_a_flaky_cluster_finishes_with_the_same_findings_as_over_a_healthy_one(sliced):
    plan = [None, TimeoutError("read timed out"), None, HttpError(429, {"Retry-After": "2"}), HttpError(503), None, None, HttpError(502)]
    healthy = qdrant_index(local_collection())
    shaky = qdrant_index(FlakyClient(local_collection(), plan))
    kw = dict(source_only=sliced, slice_size=4, probe=False, required_fields=["document_id"])
    a = run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), healthy, AuditOptions(**kw))
    b = run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), shaky, AuditOptions(**kw))
    assert found(a) == found(b) == {k: {v} for k, v in FAULTS.items()}
    scan = b.stats["scan"]
    assert scan["status"] == "completed" and scan["retries"] == 4 and scan["rate_limited"] == 1
    assert scan["recovered_errors"] == 3  # three requests needed at least one more try (one of them needed two)
    assert scan["unrecoverable_errors"] == 0 and scan["pages"] >= 4 and scan["points_scanned"] == len(world_points())
    assert a.stats["scan"]["retries"] == 0 and a.stats["scan"]["recovered_errors"] == 0


def test_a_cluster_that_never_recovers_ends_the_audit_as_partial_not_as_missing_vectors(tmp_path):
    plan = [None] + [HttpError(503)] * 40  # the first slice is read, then the node stays overloaded
    idx = qdrant_index(FlakyClient(local_collection(), plan), page=100)
    s = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{(tmp_path / 'q.db').as_posix()}", source_documents_only=True,
                 audit_slice_documents=4, probe_retrieval=False)
    svc = IntegrityService(s, Ledger(s.database_url), Connectors(FakeSource(source_docs()), FakeManifest(manifest_rows()), idx))
    result = svc.run_audit()
    scan = result.stats["scan"]
    assert result.status == "partial" and scan["slices_done"] == 1 and scan["unrecoverable_errors"] == 1 and scan["retries"] == 3
    issues, docs = ledger_state(svc)
    assert {v[0] for v in issues.values()} == {"d03"} and len(docs) == 4  # nothing was claimed about the eight unread documents


def test_progress_reports_points_scanned_pages_and_the_index_size():
    notes = []
    idx = qdrant_index(local_collection(), page=4)
    idx._last_progress = -10.0
    run_reconciliation(FakeSource(source_docs()), FakeManifest(manifest_rows()), idx,
                       AuditOptions(probe=False, required_fields=["document_id"], progress=lambda phase, **i: notes.append((phase, i))))
    reading = [i for p, i in notes if p == "reading the vector index (Qdrant)" and "points_scanned" in i]
    assert reading and reading[0]["estimated_total"] == len(world_points()) and reading[-1]["points_scanned"] <= len(world_points())
