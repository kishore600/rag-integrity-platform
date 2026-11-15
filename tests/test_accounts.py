"""Accounts, sessions, rate limits, API keys - and, above all, that workspaces cannot see each other's data."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from ragintegrity.accounts import AccountError, Accounts
from ragintegrity.ledger import Ledger, RunInProgress, utcnow
from ragintegrity.models import Action, DocSummary, Finding, IssueType, Scope, Severity
from ragintegrity.security import Vault

KEY = "k" * 40


@pytest.fixture()
def led(tmp_path):
    ledger = Ledger(f"sqlite:///{tmp_path / 'acc.db'}")
    ledger.init()
    return ledger


@pytest.fixture()
def accounts(led):
    return Accounts(led, Vault(KEY), session_days=7)


def finding(doc="d.md", tenant="t", typ=IssueType.STALE_EMBEDDING, sev=Severity.HIGH):
    return Finding(typ, sev, tenant, doc, None, "title", "detail", {"k": "v"}, Action.REINDEX_FULL)


def summary(doc="d.md", tenant="t", status="broken"):
    return DocSummary(tenant, doc, status, ["stale_embedding"], "high", True, True, True)


# ------------------------------------------------------------------------------------------------ users
def test_register_and_authenticate(accounts):
    u = accounts.register("Alice@Example.com", "a-long-unusual-passphrase")
    assert u["email"] == "alice@example.com" and u["workspace_id"]
    assert accounts.authenticate("ALICE@example.com", "a-long-unusual-passphrase")["id"] == u["id"]
    assert accounts.authenticate("alice@example.com", "wrong-passphrase-1") is None
    assert accounts.authenticate("nobody@example.com", "a-long-unusual-passphrase") is None
    assert accounts.authenticate("not-an-email", "x") is None


def test_duplicate_email_and_validation(accounts):
    accounts.register("bob@example.com", "a-long-unusual-passphrase")
    with pytest.raises(AccountError) as dup:
        accounts.register("BOB@example.com", "another-long-passphrase")
    assert dup.value.status == 409
    for email, pw in (("bad", "a-long-unusual-passphrase"), ("c@example.com", "short"), ("d@example.com", "password123")):
        with pytest.raises(AccountError) as e:
            accounts.register(email, pw)
        assert e.value.status == 422


def test_password_is_never_stored_in_clear(accounts, led):
    accounts.register("carol@example.com", "a-long-unusual-passphrase")
    with led.engine.connect() as c:
        stored = c.execute(select(led.t["users"].c.password_hash)).scalar_one()
    assert "unusual" not in stored and stored.startswith("scrypt$")


# ------------------------------------------------------------------------------------------------ sessions
def test_session_lifecycle(accounts, led):
    u = accounts.register("dan@example.com", "a-long-unusual-passphrase")
    token, expires = accounts.create_session(u["id"], u["workspace_id"], "1.2.3.4", "pytest")
    with led.engine.connect() as c:  # only a hash of the token is stored
        assert token not in str(c.execute(select(led.t["sessions"])).all())
    got = accounts.session_user(token)
    assert got["email"] == "dan@example.com" and got["workspace_id"] == u["workspace_id"]
    assert accounts.session_user("garbage") is None and accounts.session_user(None) is None
    accounts.delete_session(token)
    assert accounts.session_user(token) is None  # logout really revokes


def test_expired_sessions_are_rejected_and_cleaned_up(accounts, led):
    u = accounts.register("eve@example.com", "a-long-unusual-passphrase")
    token, _ = accounts.create_session(u["id"], u["workspace_id"], None, None)
    s = led.t["sessions"]
    with led.engine.begin() as c:
        c.execute(update(s).values(expires_at=utcnow() - timedelta(minutes=1)))
    assert accounts.session_user(token) is None
    accounts.create_session(u["id"], u["workspace_id"], None, None)  # creating a session sweeps the dead one
    with led.engine.connect() as c:
        assert len(c.execute(select(s)).all()) == 1


def test_change_password_revokes_other_sessions(accounts):
    u = accounts.register("fay@example.com", "a-long-unusual-passphrase")
    keep, _ = accounts.create_session(u["id"], u["workspace_id"], None, None)
    other, _ = accounts.create_session(u["id"], u["workspace_id"], None, None)
    with pytest.raises(AccountError) as e:
        accounts.change_password(u["id"], "wrong-current-1", "a-brand-new-passphrase", keep)
    assert e.value.status == 403
    accounts.change_password(u["id"], "a-long-unusual-passphrase", "a-brand-new-passphrase", keep)
    assert accounts.session_user(keep) and accounts.session_user(other) is None
    assert accounts.authenticate("fay@example.com", "a-brand-new-passphrase")
    assert accounts.authenticate("fay@example.com", "a-long-unusual-passphrase") is None


# ------------------------------------------------------------------------------------------------ rate limits
def test_rate_limit_window(accounts, led):
    assert all(accounts.hit("k", 3, 60) for _ in range(3))
    assert accounts.hit("k", 3, 60) is False and accounts.hit("k", 3, 60) is False
    assert accounts.hit("other", 3, 60)  # keys are independent
    with led.engine.begin() as c:  # the window passes
        t = led.t["rate_limits"]
        c.execute(update(t).where(t.c.key == "k").values(window_start=utcnow() - timedelta(seconds=61)))
    assert accounts.hit("k", 3, 60)
    accounts.clear_hits("k")
    assert accounts.hit("k", 1, 60)


# ------------------------------------------------------------------------------------------------ API keys
def test_api_keys(accounts, led):
    u = accounts.register("gus@example.com", "a-long-unusual-passphrase")
    ws = u["workspace_id"]
    token, row = accounts.create_api_key(ws, "ci")
    assert token.startswith("ragi_") and row["prefix"] == token[:12]
    with led.engine.connect() as c:
        assert token not in str(c.execute(select(led.t["api_keys"])).all())  # stored hashed
    assert accounts.api_key_workspace(token) == ws
    assert accounts.api_key_workspace("ragi_wrong") is None and accounts.api_key_workspace("nope") is None
    assert [k["name"] for k in accounts.list_api_keys(ws)] == ["ci"]
    assert accounts.revoke_api_key(ws, row["id"]) is True
    assert accounts.api_key_workspace(token) is None and accounts.list_api_keys(ws) == []
    with pytest.raises(AccountError):
        accounts.create_api_key(ws, "  ")


def test_one_workspace_cannot_revoke_anothers_key(accounts):
    a = accounts.register("a1@example.com", "a-long-unusual-passphrase")
    b = accounts.register("b1@example.com", "a-long-unusual-passphrase")
    token, row = accounts.create_api_key(a["workspace_id"], "ci")
    assert accounts.revoke_api_key(b["workspace_id"], row["id"]) is False
    assert accounts.api_key_workspace(token) == a["workspace_id"]


# ------------------------------------------------------------------------------------------------ encrypted settings
def test_settings_are_encrypted_at_rest(accounts, led):
    ws = accounts.register("hal@example.com", "a-long-unusual-passphrase")["workspace_id"]
    accounts.save_settings(ws, "s3", {"bucket": "docs"}, {"secret_access_key": "TOPSECRET-VALUE"})
    with led.engine.connect() as c:
        raw = str(c.execute(select(led.t["workspace_settings"])).all())
    assert "TOPSECRET-VALUE" not in raw and "docs" in raw
    loaded = accounts.load_settings(ws)["s3"]
    assert loaded["secrets"] == {"secret_access_key": "TOPSECRET-VALUE"} and loaded["config"] == {"bucket": "docs"}


def test_secrets_cannot_be_saved_or_read_without_a_key(led):
    keyless = Accounts(led, None)
    ws = keyless.register("ivy@example.com", "a-long-unusual-passphrase")["workspace_id"]
    with pytest.raises(AccountError):
        keyless.save_settings(ws, "s3", {}, {"secret_access_key": "x"})
    Accounts(led, Vault(KEY)).save_settings(ws, "s3", {}, {"secret_access_key": "x"})
    with pytest.raises(AccountError):
        keyless.load_settings(ws)


def test_settings_version_changes_when_settings_change(accounts):
    ws = accounts.register("jo@example.com", "a-long-unusual-passphrase")["workspace_id"]
    v0 = accounts.settings_version(ws)
    accounts.save_settings(ws, "s3", {"bucket": "a"}, {})
    v1 = accounts.settings_version(ws)
    time.sleep(0.05)  # the version is the save's timestamp: Windows' clock ticks about every 15 ms, so two saves in one tick would look alike
    accounts.save_settings(ws, "s3", {"bucket": "b"}, {})
    assert len({v0, v1, accounts.settings_version(ws)}) == 3


# ------------------------------------------------------------------------------------------------ TENANT ISOLATION
def two_workspaces(led):
    a, b = led.for_workspace("ws-a"), led.for_workspace("ws-b")
    ra, rb = a.start_run("full", "t", None), b.start_run("full", "t", None)
    a.apply_run(ra, [finding("only-a.md"), finding("shared.md")], [summary("only-a.md"), summary("shared.md")], None)
    b.apply_run(rb, [finding("only-b.md"), finding("shared.md")], [summary("only-b.md"), summary("shared.md")], None)
    a.finish_run(ra, "completed", {}), b.finish_run(rb, "completed", {})
    return a, b, ra, rb


def test_workspaces_see_only_their_own_issues_and_documents(led):
    a, b, ra, rb = two_workspaces(led)
    assert {i["document_id"] for i in a.list_issues(status="all")[0]} == {"only-a.md", "shared.md"}
    assert {i["document_id"] for i in b.list_issues(status="all")[0]} == {"only-b.md", "shared.md"}
    assert {d["document_id"] for d in a.list_documents()[0]} == {"only-a.md", "shared.md"}
    assert a.issue_counts()["open"] == 2 and b.issue_counts()["open"] == 2
    assert a.document_counts()["total"] == 2
    assert a.get_document("t", "only-b.md") is None and b.get_document("t", "only-a.md") is None
    assert {i["id"] for i in a.open_issues()}.isdisjoint({"x"})
    assert [r["id"] for r in a.list_runs()] == [ra] and [r["id"] for r in b.list_runs()] == [rb]
    assert a.get_run(rb) is None and b.get_run(ra) is None


def test_the_same_finding_in_two_workspaces_does_not_collide(led):
    a, b, *_ = two_workspaces(led)
    iid = finding("shared.md").issue_id
    assert a.get_issue(iid)["workspace_id"] == "ws-a" and b.get_issue(iid)["workspace_id"] == "ws-b"
    assert a.set_issue_status(iid, "ignored", "mine")
    assert a.get_issue(iid)["status"] == "ignored" and b.get_issue(iid)["status"] == "open"  # B is untouched


def test_a_workspace_cannot_touch_another_workspaces_issue_by_id(led):
    a, b, *_ = two_workspaces(led)
    only_a = finding("only-a.md").issue_id
    assert b.get_issue(only_a) is None
    assert b.set_issue_status(only_a, "ignored", "attack") is False
    assert a.get_issue(only_a)["status"] == "open"
    assert b.issue_events(only_a) == [] and b.issues_for_document("t", "only-a.md") == []


def test_resolving_in_one_workspace_never_resolves_in_another(led):
    a, b, *_ = two_workspaces(led)
    run = a.start_run("full", "t", None)
    diff = a.apply_run(run, [], [], None)  # A's index is now clean
    a.finish_run(run, "completed", {})
    assert len(diff.resolved) == 2 and a.issue_counts()["open"] == 0
    assert b.issue_counts()["open"] == 2 and b.document_counts()["total"] == 2


def test_scoped_runs_stay_inside_their_workspace(led):
    a, b, *_ = two_workspaces(led)
    run = a.start_run("scoped", "t", Scope(keys=frozenset({("t", "shared.md")})))
    a.apply_run(run, [], [], Scope(keys=frozenset({("t", "shared.md")})))
    a.finish_run(run, "completed", {})
    assert a.get_issue(finding("shared.md").issue_id)["status"] == "resolved"
    assert b.get_issue(finding("shared.md").issue_id)["status"] == "open"


def test_plans_events_history_and_query_log_are_isolated(led):
    a, b, *_ = two_workspaces(led)
    a.save_plan("plan-a", "draft", [], {}, create=True)
    a.add_repair_event("plan-a", "created", {})
    a.add_queries([{"ts": utcnow(), "tenant_id": "t", "query_hash": "h", "retrieved_doc_ids": ["x"]}])
    assert b.list_plans() == [] and b.get_plan("plan-a") is None and b.repair_events("plan-a") == []
    assert b.query_count() == 0 and b.queries_since(1) == [] and a.query_count() == 1
    assert led.workspace_of_plan("plan-a") == "ws-a"
    assert {h["kind"] for h in b.history()} == {"issue", "audit"} and all(h.get("plan_id") != "plan-a" for h in b.history())
    b.save_plan("plan-a", "hijacked", [], {})  # updating a plan by id is scoped too: this matches no row in ws-b
    assert a.get_plan("plan-a")["status"] == "draft"


def test_reset_only_clears_its_own_workspace(led):
    a, b, *_ = two_workspaces(led)
    a.reset()
    assert a.issue_counts()["open"] == 0 and a.list_runs() == [] and a.document_counts()["total"] == 0
    assert b.issue_counts()["open"] == 2 and len(b.list_runs()) == 1 and b.document_counts()["total"] == 2


def test_delete_user_removes_their_workspace_data_only(accounts, led):
    ua = accounts.register("del-a@example.com", "a-long-unusual-passphrase")
    ub = accounts.register("del-b@example.com", "a-long-unusual-passphrase")
    for u in (ua, ub):
        wl = led.for_workspace(u["workspace_id"])
        wl.apply_run(wl.start_run("full", "t", None), [finding()], [summary()], None)
        accounts.save_settings(u["workspace_id"], "s3", {"bucket": "b"}, {"secret_access_key": "s"})
        accounts.create_session(u["id"], u["workspace_id"], None, None)
    assert accounts.delete_user("DEL-A@example.com") and not accounts.delete_user("del-a@example.com")
    assert led.for_workspace(ua["workspace_id"]).issue_counts()["open"] == 0
    assert accounts.load_settings(ua["workspace_id"]) == {}
    assert led.for_workspace(ub["workspace_id"]).issue_counts()["open"] == 1
    assert accounts.authenticate("del-b@example.com", "a-long-unusual-passphrase")


# ------------------------------------------------------------------------------------------------ one audit at a time per workspace
def test_database_enforces_one_running_audit_per_workspace(led):
    a, b = led.for_workspace("ws-a"), led.for_workspace("ws-b")
    first = a.start_run("full", "t", None)
    with pytest.raises(RunInProgress):
        a.start_run("full", "t", None)  # even from a different process: the unique index is in the database
    b.start_run("full", "t", None)  # another workspace is unaffected
    a.finish_run(first, "completed", {})
    a.start_run("full", "t", None)  # free again once finished


def test_abandoned_runs_do_not_block_a_workspace_forever(led):
    a = led.for_workspace("ws-a")
    stuck = a.start_run("full", "t", None)
    r = led.t["audit_runs"]
    with led.engine.begin() as c:
        c.execute(update(r).where(r.c.id == stuck).values(started_at=utcnow() - timedelta(hours=1)))
    fresh = a.start_run("full", "t", None)  # the dead run is retired instead of blocking
    assert a.get_run(stuck)["status"] == "failed" and "abandoned" in a.get_run(stuck)["error"]
    assert a.get_run(fresh)["status"] == "running"
