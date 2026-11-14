"""The practice lab must keep giving exactly the answers lab/WORKBOOK.md promises.

The lab is written into S3 (moto), a SQL manifest (SQLite) and Qdrant (local mode); the real connector code reads it back, as
it does in Docker, and the findings are compared with what was planted. A second run on real services is in the README's checks.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from ragintegrity.config import Settings
from ragintegrity.connectors.factory import Connectors
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.connectors.qdrant import QdrantIndex
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.demo import lab
from ragintegrity.demo.world import TARGET_FP
from ragintegrity.ledger import Ledger
from ragintegrity.service import IntegrityService

ROOT = Path(__file__).parent.parent
SAME_NUMBER = r"^(?P<document_id>[^/]+)/(?P=document_id)\.pdf$"
PER_BILL = r"^(?P<document_id>[^/]+)/[^/]+\.pdf$"
COLUMN_MAP = '{"document_id":"external_doc_id","source_uri":"s3_url","processing_status":"is_indexed"}'
BILL_COLUMN_MAP = '{"document_id":"external_bill_id","source_uri":"s3_url","processing_status":"is_indexed"}'


@pytest.fixture()
def seeded(tmp_path):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        qd = QdrantClient(":memory:")
        eng = create_engine(f"sqlite:///{tmp_path / 'manifest.db'}")
        world = lab.seed_everything(s3, "docs", eng, qd, say=lambda _: None)
        yield world, s3, qd, eng, tmp_path


def audit(seeded, which: str, **overrides):
    _world, s3, qd, eng, tmp = seeded
    base = dict(_env_file=None, mode="live", database_url=f"sqlite:///{tmp / f'ledger-{which}-{len(overrides)}-{abs(hash(str(overrides)))}.db'}",
                s3_region="us-east-1", manifest_database_url=f"sqlite:///{tmp / 'manifest.db'}", grace_minutes=0)
    if which == "A":
        base.update(s3_bucket="docs", manifest_chunk_table="rag_chunk_manifest", qdrant_collections="kb_main", qdrant_check_vectors=True,
                    **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()})
    else:
        base.update(s3_bucket="bills-lab", s3_prefix="bills/", s3_key_pattern=SAME_NUMBER, s3_lookup_from_manifest=True, s3_hash_mode="etag",
                    manifest_table="bill_documents", manifest_column_map=COLUMN_MAP, qdrant_collections="bill_chunks",
                    qdrant_payload_map='{"document_id":"source_id"}', source_documents_only=True, required_payload_fields="document_id")
    base.update(overrides)
    settings = Settings(**base)
    svc = IntegrityService(settings, Ledger(settings.database_url),
                           Connectors(S3Source(settings, client=s3), PostgresManifest(settings, engine=eng), QdrantIndex(settings, client=qd)))
    svc.ledger.init()
    run = svc.run_audit(probe=True)
    issues, _ = svc.ledger.list_issues(status="open", limit=500)
    by = defaultdict(list)
    for i in issues:
        by[i["document_id"] if which == "B" else (i["tenant_id"], i["document_id"])].append(f"{i['type']}({i['severity']})")
    return svc, run, by


# ------------------------------------------------------------------------------------- Lab A
def test_every_fault_is_planted_exactly_once():
    world = lab.LabWorld()
    names = [info["fault"] for info in world.faults.values()]
    for name, count in lab.LAB_PLAN:
        assert names.count(name) == count == 1, name
    assert len(world.sources) + 2 == lab.LAB_DOCS_PER_TENANT * len(world.tenants)  # two files were deleted on purpose
    assert [k for k in lab.LabWorld().faults] == [k for k in world.faults]  # the same documents every time


def test_lab_a_finds_exactly_what_was_planted(seeded):
    world, *_ = seeded
    _svc, run, by = audit(seeded, "A")
    expected = {k: sorted(v["types"]) for k, v in world.faults.items()}
    assert {k: sorted(t.split("(")[0] for t in v) for k, v in by.items()} == expected
    assert run.stats["documents_total"] == 31 and run.stats["findings_total"] == 14 and run.stats["health_score"] == 54.8
    assert [w["code"] for w in run.stats["warnings"]] == ["duplicate_manifest_ids"]
    assert run.stats["isolation"]["overall"]["status"] == "leak"


def test_the_id_practice_documents_are_healthy_although_stored_three_ways(seeded):
    _world, _s3, qd, _eng, _tmp = seeded
    stored = {}
    for p in qd.scroll("kb_main", limit=1000)[0]:
        if str(p.payload["document_id"]).startswith("2000"):
            stored[str(int(float(p.payload["document_id"])))] = type(p.payload["document_id"]).__name__
    assert stored == {"20001": "int", "20002": "float", "20003": "str"}  # really three different ways of writing an ID
    svc, _run, by = audit(seeded, "A")
    assert not [k for k in by if k[1].startswith("2000")]
    docs = {d["document_id"]: d for d in svc.ledger.all_documents()}
    assert all(docs[d]["status"] == "healthy" and docs[d]["indexed_chunks"] > 0 for d in ("20001", "20002", "20003"))


def test_the_duplicated_manifest_row_is_a_warning_not_a_finding(seeded):
    world, *_ = seeded
    key = lab.duplicate_row_target(world)
    svc, run, by = audit(seeded, "A")
    assert key not in by
    [warning] = run.stats["warnings"]
    assert warning["code"] == "duplicate_manifest_ids" and warning["count"] == 1


def test_the_repair_loop_works_on_lab_a(seeded, monkeypatch):
    """plan -> trigger -> the reference worker re-indexes -> verify -> approve cleanup -> verify -> audit, on the lab's own data.

    The lab's manifest has NO unique key (the duplicated row exercise removed it), which once made the worker fail silently.
    """
    import importlib.util
    import sys

    from fastapi.testclient import TestClient

    from ragintegrity import repair as repair_module

    world, s3, qd, eng, tmp = seeded
    spec = importlib.util.spec_from_file_location("reference_worker_lab", ROOT / "examples" / "reference_worker" / "worker.py")
    rw = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rw
    spec.loader.exec_module(rw)
    secret = "local-lab-secret"
    settings = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{tmp / 'ledger-repair.db'}", s3_region="us-east-1", grace_minutes=0,
                        manifest_database_url=f"sqlite:///{tmp / 'manifest.db'}", s3_bucket="docs", manifest_chunk_table="rag_chunk_manifest",
                        qdrant_collections="kb_main", qdrant_check_vectors=True, repair_webhook_url="http://worker:9000/ragi-webhook",
                        repair_webhook_secret=secret, **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()})
    svc = IntegrityService(settings, Ledger(settings.database_url),
                           Connectors(S3Source(settings, client=s3), PostgresManifest(settings, engine=eng), QdrantIndex(settings, client=qd)))
    svc.ledger.init()
    worker = TestClient(rw.create_app(rw.Worker(s3, "docs", qd, eng), secret, background=False))
    monkeypatch.setattr(repair_module.httpx, "post",
                        lambda url, content=None, headers=None, timeout=None: worker.post("/ragi-webhook", content=content, headers=headers))

    svc.run_audit(probe=True)
    assert svc.ledger.issue_counts()["open"] == 14
    plan = svc.repairs.trigger(svc.repairs.create_plan()["id"])
    assert plan["status"] == "triggered"
    plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "cleanup_pending"
    plan = svc.repairs.verify(svc.repairs.approve_cleanup(plan["id"])["id"])
    assert plan["status"] == "completed"
    svc.run_audit(probe=True)
    left = svc.ledger.issue_counts()["open"]
    assert left < 14, "the repair loop fixed nothing"
    assert not any(i["type"] in ("missing_embedding", "false_success", "stale_embedding") for i in svc.ledger.list_issues(status="open", limit=500)[0])


def reference_worker_module():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("reference_worker_lab", ROOT / "examples" / "reference_worker" / "worker.py")
    rw = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rw
    spec.loader.exec_module(rw)
    return rw


# ------------------------------------------------------------------------------------- Lab B
def test_the_repair_loop_works_on_lab_b(seeded, monkeypatch):
    """Lab B's two broken bills are repaired by the bills worker: plan -> trigger -> worker -> verify -> audit is clean.

    The first reference worker only knows Lab A's layout; asked to repair a bill it failed in the background with NoSuchKey
    and "Verify now" then said the documents were not fixed. Lab B has its own worker, started with RAGI_WORKER_KIND=bills.
    """
    from fastapi.testclient import TestClient

    from ragintegrity import repair as repair_module

    _world, s3, qd, eng, tmp = seeded
    rw = reference_worker_module()
    secret = "local-lab-secret"
    settings = Settings(_env_file=None, mode="live", database_url=f"sqlite:///{tmp / 'ledger-repair-b.db'}", s3_region="us-east-1", grace_minutes=0,
                        manifest_database_url=f"sqlite:///{tmp / 'manifest.db'}", s3_bucket="bills-lab", s3_prefix="bills/", s3_key_pattern=SAME_NUMBER,
                        s3_lookup_from_manifest=True, s3_hash_mode="etag", manifest_table="bill_documents", manifest_column_map=COLUMN_MAP,
                        qdrant_collections="bill_chunks", qdrant_payload_map='{"document_id":"source_id"}', source_documents_only=True,
                        required_payload_fields="document_id", repair_webhook_url="http://worker-bills:9000/ragi-webhook", repair_webhook_secret=secret)
    svc = IntegrityService(settings, Ledger(settings.database_url),
                           Connectors(S3Source(settings, client=s3), PostgresManifest(settings, engine=eng), QdrantIndex(settings, client=qd)))
    svc.ledger.init()
    worker = TestClient(rw.create_app(rw.BillsWorker(s3, qd, eng), secret, background=False))
    sent = []

    def deliver(url, content=None, headers=None, timeout=None):
        sent.append(url)
        return worker.post("/ragi-webhook", content=content, headers=headers)

    monkeypatch.setattr(repair_module.httpx, "post", deliver)

    assert svc.run_audit(probe=True).stats["findings_total"] == 2
    plan = svc.repairs.create_plan()
    assert sorted(i["document_id"] for i in plan["items"]) == ["2300004", "2300005"]
    assert all(i["source_uri"].startswith("s3://bills-lab/bills/") for i in plan["items"])  # what the worker reads the file from
    plan = svc.repairs.verify(svc.repairs.trigger(plan["id"])["id"])
    assert sent and plan["status"] == "completed", [i for i in plan["items"] if i["status"] != "completed"]
    run = svc.run_audit(probe=True)
    assert (run.stats["documents_total"], run.stats["findings_total"], run.stats["health_score"]) == (5, 0, 100.0)
    # the worker is idempotent: sending the same repair again must not duplicate pieces
    again = {"phase": "reindex", "items": [{"document_id": "2300004", "source_uri": "s3://bills-lab/bills/2300004/2300004.pdf"}]}
    before = qd.count("bill_chunks").count
    assert rw.BillsWorker(s3, qd, eng).handle(again) == 1
    assert qd.count("bill_chunks").count == before


def test_lab_b_with_the_settings_the_workbook_tells_you_to_type(seeded):
    svc, run, by = audit(seeded, "B")
    assert run.stats["documents_total"] == 5 and run.stats["findings_total"] == 2 and run.stats["health_score"] == 60.0
    assert dict(by) == {"2300004": ["missing_embedding(critical)"], "2300005": ["missing_embedding(high)"]}
    assert run.stats["isolation"]["overall"]["status"] == "limited"


@pytest.mark.parametrize("n, overrides, documents, findings, extra", [
    (1, {"s3_lookup_from_manifest": False}, 6, 3, {"9000001": ["metadata_inconsistent(medium)"]}),
    (2, {"source_documents_only": False}, 11, 8, {"2200001": ["orphan_vector(high)"], "3300001": ["manifest_orphan(low)"],
                                                 "3300002": ["manifest_orphan(low)"], "3300003": ["manifest_orphan(low)"],
                                                 "8000001": ["orphan_vector(high)"], "9000001": ["orphan_vector(high)"]}),
    (3, {"s3_lookup_from_manifest": False, "source_documents_only": False}, 11, 8,
     {"2200001": ["orphan_vector(high)"], "3300001": ["manifest_orphan(low)"], "3300002": ["manifest_orphan(low)"],
      "3300003": ["manifest_orphan(low)"], "8000001": ["orphan_vector(high)"], "9000001": ["metadata_inconsistent(medium)"]}),
])
def test_the_exercises_give_what_the_workbook_says(seeded, n, overrides, documents, findings, extra):
    _svc, run, by = audit(seeded, "B", **overrides)
    assert run.stats["documents_total"] == documents and run.stats["findings_total"] == findings, n
    assert dict(by) == {"2300004": ["missing_embedding(critical)"], "2300005": ["missing_embedding(high)"], **extra}


def test_the_per_bill_exercise(seeded):
    _svc, run, by = audit(seeded, "B", s3_key_pattern=PER_BILL, manifest_column_map=BILL_COLUMN_MAP)
    assert run.stats["documents_total"] == 7 and run.stats["findings_total"] == 3 and run.stats["health_score"] == 57.1
    assert dict(by) == {"2200002": ["missing_embedding(critical)"], "2300004": ["missing_embedding(critical)"],
                        "2300005": ["missing_embedding(high)"]}
    assert "duplicate_manifest_ids" in [w["code"] for w in run.stats["warnings"]]


def test_the_exercise_table_in_the_workbook_matches_the_tests_above():
    text = lab.workbook_markdown()
    for change, see, _teach in lab.BILLS_EXERCISES:
        assert change in text and see in text
    assert len(lab.BILLS_EXERCISES) == 4


# ------------------------------------------------------------------------------------- the committed files
def test_the_committed_workbook_is_up_to_date():
    committed = (ROOT / "lab" / "WORKBOOK.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed.strip() == lab.workbook_markdown().strip(), "run: python -m ragintegrity.demo.lab > lab/WORKBOOK.md"


@pytest.mark.parametrize("label, host", [("S3", "s3.amazonaws.com"), ("PostgreSQL", "db.abcdefgh.supabase.co"),
                                         ("Qdrant", "xyz.cloud.qdrant.io"), ("S3", None), ("PostgreSQL", "10.0.0.5")])
def test_the_lab_refuses_anything_that_is_not_local(label, host):
    with pytest.raises(SystemExit, match="Refusing to seed"):
        lab.assert_local(label, host)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "s3", "postgres", "qdrant"])
def test_the_lab_accepts_its_own_hosts(host):
    lab.assert_local("S3", host)


def test_the_compose_file_is_local_only_and_has_both_labs():
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((ROOT / "docker-compose.lab.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"postgres", "qdrant", "s3", "seed", "worker", "worker-bills", "app-lab", "app-bills"}
    assert services["worker-bills"]["environment"]["RAGI_WORKER_KIND"] == "bills" and "RAGI_WORKER_KIND" not in services["worker"]["environment"]
    assert "http://worker-bills:9000/ragi-webhook" in lab.workbook_markdown()  # the address the workbook tells you to type exists
    assert services["s3"]["image"].startswith("motoserver/moto:") and ":latest" not in services["s3"]["image"]  # pinned, official
    for name, svc in services.items():
        for port in svc.get("ports", []):
            assert port.startswith("127.0.0.1:"), f"{name} publishes {port} to the whole network"
    text = (ROOT / "docker-compose.lab.yml").read_text(encoding="utf-8")
    assert "supabase" not in text.lower() and "env_file" not in text
    assert services["app-lab"]["environment"]["RAGI_MODE"] == "live" and services["app-bills"]["environment"]["RAGI_MODE"] == "app"
    for app in ("app-lab", "app-bills"):  # a throwaway ledger inside the container, never a real database
        assert services[app]["environment"]["RAGI_DATABASE_URL"].startswith("sqlite:")
    assert services["seed"]["command"] == ["python", "scripts/seed_lab.py"]
    assert any(p.endswith(":5432") for p in services["postgres"]["ports"]) and not any(p.startswith("127.0.0.1:5432:") for p in services["postgres"]["ports"])
    # the fake S3 is reached by the same address in the compose file, the seed step and the answer sheet
    endpoint = "http://s3:5000"
    assert services["s3"]["ports"] == ["127.0.0.1:9000:5000"] and "s3" in services["seed"]["depends_on"]
    assert services["seed"]["environment"]["LAB_S3_ENDPOINT"] == services["app-lab"]["environment"]["RAGI_S3_ENDPOINT_URL"] == endpoint
    assert services["worker"]["environment"]["S3_ENDPOINT_URL"] == endpoint and f"`{endpoint}`" in lab.workbook_markdown()
