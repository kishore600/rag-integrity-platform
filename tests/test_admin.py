"""The admin dashboard API: only listed emails on a signed-in session see it, and it never hands out secrets."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.ledger import Ledger, utcnow

KEY = "k" * 40
PW = "a-long-unusual-passphrase"
ORIGIN = {"Origin": "http://testserver"}
BOSS = "boss@example.com"
ADMIN_PATHS = ("/api/admin/overview", "/api/admin/users", "/api/admin/audits")


def client_for(tmp_path, **kw) -> TestClient:
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'app.db'}", secret_key=KEY, **kw)
    return TestClient(create_app(settings=settings))


def signup(c: TestClient, email: str) -> None:
    r = c.post("/api/auth/register", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    c.headers.update(ORIGIN)


def login(c: TestClient, email: str) -> None:
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers.update(ORIGIN)


def seed(tmp_path) -> dict[str, str]:
    """Alice and the boss sign up while nobody is an admin yet (the order the docs ask for)."""
    with client_for(tmp_path) as c:
        signup(c, "alice@example.com")
    with client_for(tmp_path) as c:
        signup(c, BOSS)
    led = Ledger(f"sqlite:///{tmp_path / 'app.db'}")
    u = led.t["users"]
    with led.engine.connect() as conn:
        return {email: ws for email, ws in conn.execute(select(u.c.email, u.c.workspace_id))}


def add_runs(tmp_path, ws: str) -> None:
    led = Ledger(f"sqlite:///{tmp_path / 'app.db'}")
    r, s = led.t["audit_runs"], led.t["workspace_settings"]
    now = utcnow()
    with led.engine.begin() as conn:
        conn.execute(insert(s), [{"workspace_id": ws, "kind": kind, "config": {"bucket": "b"}, "secrets": None, "updated_at": now}
                                 for kind in ("s3", "pgvector")])
        conn.execute(insert(r), [
            {"id": str(uuid.uuid4()), "workspace_id": ws, "kind": "full", "trigger": "manual", "scope": {}, "status": "completed",
             "started_at": now - timedelta(hours=2), "finished_at": now - timedelta(hours=2) + timedelta(seconds=12),
             "stats": {"documents_total": 40, "findings_total": 3, "health_score": 92.5, "duration_seconds": 12.04},
             "error": None},  # every row names the same columns: a multi-row insert takes them from the first row
            {"id": str(uuid.uuid4()), "workspace_id": ws, "kind": "full", "trigger": "api", "scope": {}, "status": "failed",
             "started_at": now - timedelta(minutes=5), "finished_at": now - timedelta(minutes=4), "stats": {},
             "error": "OperationalError: could not connect to postgresql://reader:hunter2@db.example.com:5432/x "
                      "while posting to https://hooks.slack.com/services/T0/B0/secret"},
        ])


def test_without_admin_emails_there_is_no_dashboard(tmp_path):
    seed(tmp_path)
    with client_for(tmp_path) as c:
        login(c, BOSS)
        assert c.get("/api/session").json()["user"] == {"email": BOSS, "admin": False}
        for path in ADMIN_PATHS:
            assert c.get(path).status_code == 404, path


def test_only_listed_emails_on_a_session_get_in(tmp_path):
    seed(tmp_path)
    with client_for(tmp_path, admin_emails=f" {BOSS.upper()} , other@example.com") as c:
        for path in ADMIN_PATHS:
            assert c.get(path).status_code == 401, path  # signed out
        login(c, "alice@example.com")
        assert c.get("/api/session").json()["user"]["admin"] is False
        for path in ADMIN_PATHS:
            assert c.get(path).status_code == 404, path  # signed in, not an admin: looks like an unknown address
        c.post("/api/auth/logout")
        login(c, BOSS)
        assert c.get("/api/session").json()["user"]["admin"] is True  # matched without regard to case or spaces
        for path in ADMIN_PATHS:
            assert c.get(path).status_code == 200, path
        token = c.post("/api/keys", json={"name": "ci"}).json()["token"]
    with client_for(tmp_path, admin_emails=BOSS) as c:  # an API key, even the admin's own, never opens the dashboard
        for path in ADMIN_PATHS:
            assert c.get(path, headers={"Authorization": f"Bearer {token}"}).status_code in (403, 404), path


def test_a_listed_email_cannot_be_claimed_through_sign_up(tmp_path):
    with client_for(tmp_path, admin_emails="new-boss@example.com") as c:
        r = c.post("/api/auth/register", json={"email": "New-Boss@example.com", "password": PW})
        assert r.status_code == 409 and r.json()["detail"] == "An account with that email already exists."
        assert c.post("/api/auth/register", json={"email": "someone@example.com", "password": PW}).status_code == 201


def test_the_dashboard_shows_accounts_and_audits_without_secrets(tmp_path):
    ws = seed(tmp_path)
    add_runs(tmp_path, ws["alice@example.com"])
    with client_for(tmp_path, admin_emails=BOSS) as c:
        login(c, BOSS)
        users = c.get("/api/admin/users").json()
        audits = c.get("/api/admin/audits").json()
        ov = c.get("/api/admin/overview").json()

    assert [u["email"] for u in users] == [BOSS, "alice@example.com"]  # newest first
    alice = users[1]
    assert alice["workspace"] == "alice's workspace" and alice["systems"] == ["pgvector", "s3"] and alice["connected"] is True
    assert alice["audits"] == 2 and alice["audits_failed"] == 1 and alice["last_audit"]["status"] == "failed"
    assert alice["last_active_at"] is not None and users[0]["connected"] is False and users[0]["audits"] == 0

    assert [a["status"] for a in audits] == ["failed", "completed"] and {a["email"] for a in audits} == {"alice@example.com"}
    done = audits[1]
    assert done["documents"] == 40 and done["findings"] == 3 and done["health_score"] == 92.5 and done["duration_seconds"] == 12.0
    err = audits[0]["error"]
    assert "hunter2" not in err and "hooks.slack.com" not in err and "secret" not in err and "OperationalError" in err

    assert ov["users"] == {"total": 2, "new_7d": 2, "new_30d": 2, "active_7d": 2}
    assert ov["funnel"] == {"signed_up": 2, "connected": 1, "audited": 1}
    assert ov["audits"]["total"] == 2 and ov["audits"]["last_7d"] == 2 and ov["audits"]["failed_7d"] == 1
    assert len(ov["daily"]) == 30 and sum(d["signups"] for d in ov["daily"]) == 2 and sum(d["audits"] for d in ov["daily"]) == 2

    blob = str(users) + str(audits) + str(ov)
    for forbidden in ("password", "token", "user_agent", "testclient", "scrypt", "bucket"):
        assert forbidden not in blob, forbidden
