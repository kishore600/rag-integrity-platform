"""Runs the ledger, the Supabase migration and the manifest connector against a REAL Postgres.

Skipped unless RAGI_TEST_PG_URL points at a throwaway database, e.g.
    RAGI_TEST_PG_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest tests/test_postgres_integration.py
CI provides one through a Postgres service container.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from ragintegrity.config import Settings, normalize_db_url
from ragintegrity.connectors.factory import build_connectors
from ragintegrity.connectors.postgres import PostgresManifest
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.models import Scope
from ragintegrity.service import IntegrityService

PG_URL = os.environ.get("RAGI_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="RAGI_TEST_PG_URL not set")
ROOT = Path(__file__).parent.parent


def engine():
    return create_engine(normalize_db_url(PG_URL), pool_size=2, max_overflow=0, connect_args={"prepare_threshold": None})


def run_sql_file(eng, path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"--[^\n]*", "", raw).replace("%", "%%")  # psycopg treats a bare % as a placeholder; psql does not
    with eng.begin() as c:
        c.exec_driver_sql(raw)


@pytest.fixture()
def clean_pg():
    eng = engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS ragi CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS public.rag_document_manifest, public.rag_chunk_manifest"))
    yield eng
    eng.dispose()


MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))


def apply_all_migrations(eng) -> None:
    for path in MIGRATIONS:
        run_sql_file(eng, path)


def test_supabase_migrations_apply_in_order_and_match_the_models(clean_pg):
    apply_all_migrations(clean_pg)
    apply_all_migrations(clean_pg)  # re-running is safe: the ledger tables are empty, so the guard passes
    ledger = Ledger(PG_URL, engine=clean_pg)
    ledger.init()  # create_all must find nothing to add
    assert ledger.schema_ready() == (True, "ok")
    with clean_pg.connect() as c:
        rls = {r[0]: r[1] for r in c.execute(text(
            "select relname, relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'ragi' and relkind = 'r'"))}
    assert len(rls) == 13 and all(rls.values()), rls


def test_the_destructive_migration_refuses_to_drop_a_ledger_that_has_data(clean_pg):
    run_sql_file(clean_pg, MIGRATIONS[0])  # v1 tables
    with clean_pg.begin() as c:
        c.execute(text("insert into ragi.audit_runs (id, kind, \"trigger\", status, started_at) values ('x','full','t','completed', now())"))
    with pytest.raises(DBAPIError, match="refusing to recreate"):
        run_sql_file(clean_pg, MIGRATIONS[1])
    with clean_pg.connect() as c:  # nothing was dropped
        assert c.execute(text("select count(*) from ragi.audit_runs")).scalar_one() == 1


def test_workspace_isolation_accounts_and_audit_lock_on_real_postgres(clean_pg):
    from ragintegrity.accounts import Accounts
    from ragintegrity.ledger import RunInProgress
    from ragintegrity.models import Action, DocSummary, Finding, IssueType, Severity
    from ragintegrity.security import Vault

    apply_all_migrations(clean_pg)
    led = Ledger(PG_URL, engine=clean_pg)
    acc = Accounts(led, Vault("k" * 40))
    a = acc.register("pg-a@example.com", "a-long-unusual-passphrase")
    b = acc.register("pg-b@example.com", "a-long-unusual-passphrase")
    assert acc.authenticate("PG-A@example.com", "a-long-unusual-passphrase")["id"] == a["id"]
    token, _ = acc.create_session(a["id"], a["workspace_id"], "1.2.3.4", "pytest")
    assert acc.session_user(token)["workspace_id"] == a["workspace_id"]
    acc.save_settings(a["workspace_id"], "s3", {"bucket": "b"}, {"secret_access_key": "SECRET-ON-PG"})
    with clean_pg.connect() as c:
        assert "SECRET-ON-PG" not in str(c.execute(text("select secrets from ragi.workspace_settings")).all())
    assert acc.load_settings(a["workspace_id"])["s3"]["secrets"] == {"secret_access_key": "SECRET-ON-PG"}
    assert acc.hit("k", 2, 60) and acc.hit("k", 2, 60) and not acc.hit("k", 2, 60)

    la, lb = led.for_workspace(a["workspace_id"]), led.for_workspace(b["workspace_id"])
    f = Finding(IssueType.STALE_EMBEDDING, Severity.HIGH, "t", "same.md", None, "t", "d", {}, Action.REINDEX_FULL)
    s = DocSummary("t", "same.md", "broken", ["stale_embedding"], "high", True, True, True)
    ra, rb = la.start_run("full", "t", None), lb.start_run("full", "t", None)  # two workspaces may run at once
    la.apply_run(ra, [f], [s], None)
    lb.apply_run(rb, [], [], None)
    assert la.issue_counts()["open"] == 1 and lb.issue_counts()["open"] == 0
    assert lb.get_issue(f.issue_id) is None and lb.set_issue_status(f.issue_id, "ignored") is False

    with pytest.raises(RunInProgress):  # the partial unique index, enforced by Postgres itself
        la.start_run("full", "t", None)
    la.finish_run(ra, "completed", {})
    la.start_run("full", "t", None)
    assert acc.delete_user("pg-a@example.com") and la.issue_counts()["open"] == 0 and acc.load_settings(a["workspace_id"]) == {}


def test_full_service_cycle_on_postgres(clean_pg):
    ledger = Ledger(PG_URL, engine=clean_pg)
    ledger.init()
    settings = Settings(_env_file=None, mode="demo", database_url=PG_URL, grace_minutes=0,
                        **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()})
    svc = IntegrityService(settings, ledger, build_connectors(settings, DemoWorld(seed=3, docs_per_tenant=25)))
    svc.bootstrap()
    ov = svc.overview()
    assert ov["issues"]["open"] > 0 and ov["documents"]["total"] > 0

    again = svc.run_audit()  # idempotent upsert on Postgres: same ids, no duplicates, nothing resolved
    assert again.diff.opened == [] and again.diff.resolved == []

    plan = svc.repairs.create_plan()
    svc.repairs.trigger(plan["id"])
    plan = svc.repairs.verify(plan["id"])
    if plan["status"] == "cleanup_pending":
        svc.repairs.approve_cleanup(plan["id"])
        plan = svc.repairs.verify(plan["id"])
    assert plan["status"] == "completed"
    svc.run_audit()
    assert ledger.issue_counts()["open"] == 0
    assert ledger.history(20) and ledger.document_counts()["health_score"] == 100.0
    scoped = ledger.documents_for([(d["tenant_id"], d["document_id"]) for d in list(ledger.all_documents())[:3]])
    assert len(scoped) == 3  # tuple IN (...) works on Postgres


def test_manifest_connector_reads_real_postgres_read_only(clean_pg):
    run_sql_file(clean_pg, ROOT / "supabase" / "examples" / "manifest_example.sql")
    with clean_pg.begin() as c:
        c.execute(text("insert into public.rag_document_manifest (tenant_id, document_id, source_hash, processing_status, "
                       "expected_chunk_count, embedding_model, embedding_dim, updated_at) values "
                       "('acme','a.md','h1','success',3,'m1',16, now()), ('globex','a.md','h2','failed',null,null,null, now())"))
        c.execute(text("insert into public.rag_chunk_manifest values ('acme','a.md','a#0',0,'x'),('acme','a.md','a#1',1,'y')"))
    s = Settings(_env_file=None, manifest_database_url=PG_URL, manifest_chunk_table="rag_chunk_manifest")
    m = PostgresManifest(s, engine=clean_pg)
    rows = {r.key: r for r in m.documents()}
    assert set(rows) == {("acme", "a.md"), ("globex", "a.md")}
    assert rows[("acme", "a.md")].updated_at.endswith("Z") and rows[("acme", "a.md")].fingerprint.embedding_dim == 16
    assert [r.key for r in m.documents(Scope(keys=frozenset({("globex", "a.md")})))] == [("globex", "a.md")]
    assert {c.chunk_id for c in m.chunks()} == {"a#0", "a#1"}
    assert m.health().ok

    # every statement the connector runs is inside a READ ONLY transaction...
    [row] = list(m._stream("SELECT current_setting('transaction_read_only') AS ro", {}))
    assert row["ro"] == "on"
    # ...and a write cannot get through it
    with pytest.raises(DBAPIError):
        list(m._stream("DELETE FROM public.rag_document_manifest", {}))
    with clean_pg.connect() as c:
        assert c.execute(text("select count(*) from public.rag_document_manifest")).scalar_one() == 2
