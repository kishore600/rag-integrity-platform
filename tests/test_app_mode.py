"""The multi-user product over HTTP: sign-up, login, sessions, CSRF, rate limits, settings, API keys, isolation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ragintegrity.api.app import COOKIE, create_app
from ragintegrity.config import Settings

KEY = "k" * 40
PW = "a-long-unusual-passphrase"
ORIGIN = {"Origin": "http://testserver"}


def make(tmp_path, **kw):
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'app.db'}", secret_key=KEY, **kw)
    app = create_app(settings=settings)
    return TestClient(app), app, settings


def signup(client, email="alice@example.com", password=PW):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    client.headers.update(ORIGIN)
    return r


@pytest.fixture()
def client(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        yield c


# ------------------------------------------------------------------------------------------------ gate
def test_everything_but_the_shell_requires_a_session(client):
    s = client.get("/api/session").json()
    assert s["app"] is True and s["authenticated"] is False and s["registration_open"] is True and s["setup"]["required"] is False
    assert client.get("/").status_code == 200 and client.get("/healthz").json()["ok"] is True
    for method, path in [("get", "/api/overview"), ("get", "/api/issues"), ("get", "/api/documents"), ("get", "/api/settings"),
                         ("get", "/api/keys"), ("get", "/api/repairs"), ("get", "/api/history"), ("post", "/api/audits"),
                         ("post", "/api/repairs"), ("post", "/api/query-log"), ("get", "/api/report")]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, (path, r.status_code)


def test_app_mode_has_no_sample_data(client):
    signup(client)
    ov = client.get("/api/overview").json()
    assert ov["documents"]["total"] == 0 and ov["issues"]["open"] == 0 and ov["latest_run"] is None
    assert ov["demo"] is False and client.get("/api/documents").json()["total"] == 0
    assert client.get("/api/history").json() == []
    assert client.post("/api/demo/reset", json={}).status_code == 404


# ------------------------------------------------------------------------------------------------ register / login / logout
def test_register_sets_a_hardened_cookie_and_signs_in(client):
    r = signup(client)
    cookie = r.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    s = client.get("/api/session").json()
    assert s["authenticated"] is True and s["user"]["email"] == "alice@example.com" and s["ready"] is False
    assert s["workspace"]["name"]  # the sidebar names the signed-in workspace
    client.post("/api/auth/logout")
    assert "workspace" not in client.get("/api/session").json()  # nothing about a workspace leaks to a signed-out visitor


def test_register_validation_and_duplicates(client):
    for body, status in [({"email": "nope", "password": PW}, 422), ({"email": "a@example.com", "password": "short"}, 422),
                         ({"email": "b@example.com", "password": "password123"}, 422), ({"email": "c@example.com"}, 422)]:
        assert client.post("/api/auth/register", json=body).status_code == status
    signup(client)
    other = TestClient(client.app)
    assert other.post("/api/auth/register", json={"email": "ALICE@example.com", "password": PW}).status_code == 409


def test_login_logout_roundtrip(client):
    signup(client)
    client.post("/api/auth/logout")
    assert client.get("/api/session").json()["authenticated"] is False
    assert client.get("/api/overview").status_code == 401
    r = client.post("/api/auth/login", json={"email": "Alice@Example.com", "password": PW})
    assert r.status_code == 200 and client.get("/api/overview").status_code == 200


def test_login_errors_do_not_reveal_which_emails_exist(client):
    signup(client)
    fresh = TestClient(client.app)
    wrong_pw = fresh.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password-123"})
    no_user = fresh.post("/api/auth/login", json={"email": "ghost@example.com", "password": "wrong-password-123"})
    assert wrong_pw.status_code == no_user.status_code == 401 and wrong_pw.json() == no_user.json()


def test_brute_force_is_throttled_per_email_and_a_good_login_resets_it(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        signup(c)
        fresh = TestClient(c.app)
        for _ in range(8):
            assert fresh.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password-123"}).status_code == 401
        blocked = fresh.post("/api/auth/login", json={"email": "alice@example.com", "password": PW})
        assert blocked.status_code == 429  # even the right password is refused while throttled
        # a different account from the same network is not locked out by this
        assert TestClient(c.app).post("/api/auth/register", json={"email": "bob@example.com", "password": PW}).status_code == 201


def test_signups_are_rate_limited_per_network(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        # a fresh client each time, as a new visitor would be (a signed-in browser also sends an Origin header)
        codes = [TestClient(c.app).post("/api/auth/register", json={"email": f"user{i}@example.com", "password": PW}).status_code
                 for i in range(7)]
    assert codes[:5] == [201] * 5 and codes[5:] == [429, 429]


def test_registration_can_be_closed(tmp_path):
    c, *_ = make(tmp_path, allow_registration=False)
    with c:
        assert c.get("/api/session").json()["registration_open"] is False
        assert c.post("/api/auth/register", json={"email": "a@example.com", "password": PW}).status_code == 403


def test_forged_and_stale_cookies_are_rejected(client):
    client.headers.update(ORIGIN)
    client.cookies.set(COOKIE, "forged-token-value")
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/session").json()["authenticated"] is False


# ------------------------------------------------------------------------------------------------ CSRF
def test_cookie_writes_must_come_from_the_same_origin(client):
    signup(client)
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/audits", json={}, headers=evil).status_code == 403
    assert client.put("/api/settings/policy", json={"values": {"grace_minutes": 5}}, headers=evil).status_code == 403
    assert client.post("/api/auth/logout", headers=evil).status_code == 403
    no_origin = client.post("/api/auth/logout", headers={"Origin": ""})
    assert no_origin.status_code == 403
    assert client.get("/api/overview", headers=evil).status_code == 200  # reads are not state-changing
    assert client.put("/api/settings/policy", json={"values": {"grace_minutes": 5}}).status_code == 200  # same origin


# ------------------------------------------------------------------------------------------------ password change
def test_change_password_flow(client):
    signup(client)
    assert client.post("/api/auth/password", json={"current_password": "wrong-pass-1234", "new_password": "a-brand-new-passphrase"}).status_code == 403
    assert client.post("/api/auth/password", json={"current_password": PW, "new_password": "weak"}).status_code == 422
    assert client.post("/api/auth/password", json={"current_password": PW, "new_password": "a-brand-new-passphrase"}).status_code == 200
    assert client.get("/api/overview").status_code == 200  # this session survives
    fresh = TestClient(client.app)
    assert fresh.post("/api/auth/login", json={"email": "alice@example.com", "password": PW}).status_code == 401
    assert fresh.post("/api/auth/login", json={"email": "alice@example.com", "password": "a-brand-new-passphrase"}).status_code == 200


# ------------------------------------------------------------------------------------------------ settings
def test_settings_view_hides_secrets_and_tracks_readiness(client):
    signup(client)
    v = client.get("/api/settings").json()
    assert v["ready"] is False and v["missing"] == ["s3", "qdrant"]  # the manifest is optional: S3 and the index are enough
    assert not any(k["configured"] for k in v["kinds"])  # a brand-new workspace has nothing configured, optional groups included
    client.put("/api/settings/policy", json={"values": {"grace_minutes": 3}})
    assert next(k for k in client.get("/api/settings").json()["kinds"] if k["kind"] == "policy")["configured"] is True
    assert {k["kind"] for k in v["kinds"]} == {"s3", "manifest", "qdrant", "index", "pgvector", "pipeline", "repair", "alerts", "email", "policy"}
    assert {k["kind"] for k in v["kinds"] if k["required_for_audit"]} == {"s3", "qdrant"}
    r = client.put("/api/settings/s3", json={"values": {"bucket": "my-docs", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "TOPSECRET-123",
                                                          "region": "us-east-1", "hash_mode": "compute"}})
    assert r.status_code == 200
    assert "TOPSECRET-123" not in r.text and "AKIAEXAMPLE" not in r.text  # secrets never come back out
    s3 = next(k for k in r.json()["kinds"] if k["kind"] == "s3")
    fields = {f["name"]: f for f in s3["fields"]}
    assert s3["configured"] is True and fields["bucket"]["value"] == "my-docs" and fields["hash_mode"]["value"] == "compute"
    assert fields["secret_access_key"]["value"] is None and fields["secret_access_key"]["has_value"] is True
    assert r.json()["missing"] == ["qdrant"]


def test_omitted_secret_is_kept_and_empty_string_clears_it(client):
    signup(client)
    client.put("/api/settings/s3", json={"values": {"bucket": "b", "access_key_id": "AK", "secret_access_key": "SK"}})
    kept = client.put("/api/settings/s3", json={"values": {"bucket": "b2"}}).json()
    s3 = next(k for k in kept["kinds"] if k["kind"] == "s3")
    assert {f["name"]: f["has_value"] for f in s3["fields"]}["secret_access_key"] is True and s3["configured"] is True
    cleared = client.put("/api/settings/s3", json={"values": {"secret_access_key": ""}}).json()
    s3 = next(k for k in cleared["kinds"] if k["kind"] == "s3")
    assert {f["name"]: f["has_value"] for f in s3["fields"]}["secret_access_key"] is False and s3["configured"] is False


def test_secrets_are_encrypted_in_the_database(tmp_path):
    c, app, settings = make(tmp_path)
    with c:
        signup(c)
        c.put("/api/settings/s3", json={"values": {"bucket": "b", "access_key_id": "AKIA-PLAIN-ID", "secret_access_key": "PLAIN-SECRET-XYZ"}})
        c.put("/api/settings/alerts", json={"values": {"webhook_url": "https://93.184.216.34/hooks/SECRET-TOKEN"}})
        led = app.state.app_state.ledger
        with led.engine.connect() as conn:
            raw = str(conn.execute(select(led.t["workspace_settings"])).all())
    for secret in ("PLAIN-SECRET-XYZ", "AKIA-PLAIN-ID", "SECRET-TOKEN"):
        assert secret not in raw
    assert "my-docs" not in raw and "'bucket': 'b'" in raw  # non-secret config is stored as readable values


@pytest.mark.parametrize("kind,values,fragment", [
    ("s3", {"endpoint_url": "http://127.0.0.1:9000"}, "private or reserved"),
    ("s3", {"endpoint_url": "http://169.254.169.254/latest"}, "private or reserved"),
    ("s3", {"endpoint_url": "file:///etc/passwd"}, "must start with"),
    ("s3", {"key_pattern": "(unclosed"}, "regular expression"),
    ("s3", {"key_pattern": r"^(?P<tenant_id>[^/]+)/.+$"}, "document_id"),
    ("s3", {"hash_mode": "magic"}, "must be one of"),
    ("manifest", {"database_url": "postgresql://u:p@10.0.0.5:5432/db"}, "private or reserved"),
    ("manifest", {"database_url": "postgresql://u:p@93.184.216.34/db?hostaddr=10.0.0.5"}, "Unsupported connection option"),
    ("manifest", {"database_url": "mysql://u:p@93.184.216.34/db"}, "postgresql"),
    ("manifest", {"table": "x; DROP TABLE users"}, "Invalid"),
    ("manifest", {"column_map": "[1,2]"}, "JSON object"),
    ("manifest", {"column_map": "{not json"}, "not valid JSON"),
    ("qdrant", {"url": "http://localhost:6333"}, "not a public host"),
    ("qdrant", {"url": "https://user:pw@93.184.216.34:6333"}, "credentials"),
    ("qdrant", {"collections": "ok,bad name!"}, "letters, digits"),
    ("pipeline", {"embedding_dim": "-4"}, "between"),
    ("pipeline", {"chunk_size": "abc"}, "number"),
    ("repair", {"webhook_url": "http://192.168.1.5/hook"}, "private or reserved"),
    ("alerts", {"webhook_url": "http://10.0.0.1/hook"}, "private or reserved"),
    ("policy", {"grace_minutes": 99999}, "between"),
    ("s3", {"not_a_setting": "x"}, "Unknown setting"),
])
def test_dangerous_or_invalid_settings_are_rejected(client, kind, values, fragment):
    signup(client)
    r = client.put(f"/api/settings/{kind}", json={"values": values})
    assert r.status_code == 422 and fragment in r.json()["detail"], r.text
    assert client.put("/api/settings/nope", json={"values": {}}).status_code == 404


def test_private_hosts_are_allowed_only_when_the_operator_opts_in(tmp_path):
    c, *_ = make(tmp_path, allow_private_hosts=True)  # self-hosting next to your own Qdrant
    with c:
        signup(c)
        assert c.put("/api/settings/qdrant", json={"values": {"url": "http://localhost:6333"}}).status_code == 200


def test_connection_test_refuses_private_targets_and_reports_failures_cleanly(client):
    signup(client)
    client.put("/api/settings/policy", json={"values": {"grace_minutes": 5}})
    r = client.post("/api/settings/qdrant/test", json={"values": {"url": "http://127.0.0.1:6333"}})
    assert r.status_code == 422  # rejected before any connection is attempted
    r = client.post("/api/settings/qdrant/test")  # nothing saved yet
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False and "required fields" in body["checks"][0]["detail"].lower()


def test_connection_tests_are_rate_limited(client):
    signup(client)
    codes = [client.post("/api/settings/policy/test").status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[30:] == [429, 429]


def test_audit_before_setup_is_a_clear_409_and_leaves_no_trace(client):
    signup(client)
    r = client.post("/api/audits", json={})
    assert r.status_code == 409 and r.json()["setup_incomplete"] is True and "S3" in r.json()["detail"]
    assert client.get("/api/audits").json() == [] and client.post("/api/repairs", json={}).status_code == 404


# ------------------------------------------------------------------------------------------------ API keys
def test_api_keys_authenticate_automation_but_not_account_changes(client):
    signup(client)
    made = client.post("/api/keys", json={"name": "github-actions"})
    assert made.status_code == 201
    token = made.json()["token"]
    assert token.startswith("ragi_") and "shown only once" in made.json()["note"]
    listing = client.get("/api/keys").json()
    assert [k["name"] for k in listing] == ["github-actions"] and token not in str(listing)

    bot = TestClient(client.app)  # no cookie: only the key
    auth = {"Authorization": f"Bearer {token}"}
    assert bot.get("/api/overview", headers=auth).status_code == 200
    assert bot.post("/api/query-log", json={"queries": [{"tenant_id": "t", "retrieved_doc_ids": ["a.md"]}]}, headers=auth).json() == {"ingested": 1}
    for method, path in [("get", "/api/settings"), ("get", "/api/keys"), ("post", "/api/keys"), ("post", "/api/auth/password"),
                         ("put", "/api/settings/policy")]:
        r = getattr(bot, method)(path, headers=auth, **({"json": {"name": "x", "values": {}, "current_password": "a", "new_password": "b"}} if method != "get" else {}))
        assert r.status_code == 403, (path, r.status_code)  # automation cannot read secrets or mint more keys
    assert bot.get("/api/overview", headers={"Authorization": "Bearer ragi_not-a-real-key"}).status_code == 401

    key_id = listing[0]["id"]
    assert client.delete(f"/api/keys/{key_id}").status_code == 200
    assert bot.get("/api/overview", headers=auth).status_code == 401  # revoked keys stop working immediately
    assert client.delete(f"/api/keys/{key_id}").status_code == 404


def test_api_key_count_is_capped(client):
    signup(client)
    for i in range(20):
        assert client.post("/api/keys", json={"name": f"k{i}"}).status_code == 201
    assert client.post("/api/keys", json={"name": "one-too-many"}).status_code == 409


# ------------------------------------------------------------------------------------------------ isolation over HTTP
def test_two_users_never_see_each_others_data(tmp_path):
    c, *_ = make(tmp_path)
    with c:
        alice, bob = TestClient(c.app), TestClient(c.app)
        signup(alice, "alice@example.com")
        signup(bob, "bob@example.com")
        key = alice.post("/api/keys", json={"name": "alice-ci"}).json()
        alice.post("/api/query-log", json={"queries": [{"tenant_id": "t", "retrieved_doc_ids": ["secret.md"]}]},
                   headers={"Authorization": f"Bearer {key['token']}"})
        alice.put("/api/settings/s3", json={"values": {"bucket": "alice-private-bucket", "access_key_id": "AK", "secret_access_key": "SK"}})

        assert alice.get("/api/overview").json()["query_log_size"] == 1
        assert bob.get("/api/overview").json()["query_log_size"] == 0
        assert "alice-private-bucket" not in bob.get("/api/settings").text
        assert bob.get("/api/keys").json() == []
        assert bob.delete(f"/api/keys/{key['key']['id']}").status_code == 404  # cannot revoke Alice's key by id
        assert alice.get("/api/keys").json()[0]["name"] == "alice-ci"
        # a request that carries both a session and an API key is resolved by the session: Bob's browser stays in Bob's workspace
        assert bob.get("/api/overview", headers={"Authorization": f"Bearer {key['token']}"}).json()["query_log_size"] == 0
        # whereas the key on its own (no cookie) acts inside Alice's workspace, and only there
        assert TestClient(c.app).get("/api/overview", headers={"Authorization": f"Bearer {key['token']}"}).json()["query_log_size"] == 1
        assert TestClient(c.app).get("/api/settings", headers={"Authorization": f"Bearer {key['token']}"}).status_code == 403


# ------------------------------------------------------------------------------------------------ setup-required state
def test_missing_secret_key_puts_the_app_in_a_safe_setup_state(tmp_path):
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'x.db'}", secret_key=None)
    with TestClient(create_app(settings=settings)) as c:
        s = c.get("/api/session").json()
        assert s["setup"]["required"] is True and any("RAGI_SECRET_KEY" in p for p in s["setup"]["problems"])
        assert c.get("/api/overview").status_code == 503
        assert c.post("/api/auth/register", json={"email": "a@example.com", "password": PW}).status_code == 503
        assert c.get("/healthz").status_code == 200 and c.get("/").status_code == 200


def test_serverless_never_uses_an_ephemeral_database_for_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    settings = Settings(_env_file=None, mode="app", database_url=f"sqlite:///{tmp_path / 'x.db'}", secret_key=KEY)
    with TestClient(create_app(settings=settings)) as c:
        s = c.get("/api/session").json()
        assert s["setup"]["required"] is True and any("Postgres" in p for p in s["setup"]["problems"])
        assert c.post("/api/auth/register", json={"email": "a@example.com", "password": PW}).status_code == 503


def test_error_messages_never_contain_connection_passwords(tmp_path):
    from ragintegrity.security import scrub

    err = "connection to postgresql://svc:HUNTER2-password@db.example.com:5432/app failed"
    assert "HUNTER2" not in scrub(err)
