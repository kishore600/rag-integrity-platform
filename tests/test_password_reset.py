"""The operator's password reset: `ragi users set-password EMAIL`, and Accounts.set_password under it."""

from __future__ import annotations

import io

import pytest

from ragintegrity import cli
from ragintegrity.accounts import AccountError, Accounts, login_email_key
from ragintegrity.config import get_settings
from ragintegrity.ledger import Ledger
from ragintegrity.security import Vault

KEY = "k" * 40
OLD = "a-long-unusual-passphrase"
NEW = "another-long-unusual-phrase"


@pytest.fixture()
def accounts(tmp_path):
    led = Ledger(f"sqlite:///{tmp_path / 'acc.db'}")
    led.init()
    return Accounts(led, Vault(KEY))


def test_set_password_replaces_it_signs_out_everywhere_and_clears_the_lockout(accounts):
    user = accounts.register("Alice@Example.com", OLD)
    tokens = [accounts.create_session(user["id"], user["workspace_id"], "1.2.3.4", "test")[0] for _ in range(2)]
    key = login_email_key("alice@example.com")
    for _ in range(8):
        accounts.hit(key, 8, 900)
    assert accounts.hit(key, 8, 900) is False  # locked out after too many attempts

    assert accounts.set_password(" ALICE@example.com ", NEW) is True
    assert accounts.authenticate("alice@example.com", OLD) is None
    assert accounts.authenticate("alice@example.com", NEW)["email"] == "alice@example.com"
    assert all(accounts.session_user(t) is None for t in tokens)
    assert accounts.hit(key, 8, 900) is True  # the new password can be used straight away


def test_set_password_refuses_weak_passwords_and_unknown_accounts(accounts):
    accounts.register("alice@example.com", OLD)
    with pytest.raises(AccountError):
        accounts.set_password("alice@example.com", "short")
    with pytest.raises(AccountError):
        accounts.set_password("alice@example.com", "alice-is-my-password")  # contains the email's name
    with pytest.raises(AccountError):
        accounts.set_password("not an email", NEW)
    assert accounts.set_password("nobody@example.com", NEW) is False
    assert accounts.authenticate("alice@example.com", OLD) is not None  # nothing changed


def run_cli(monkeypatch, tmp_path, argv, stdin=""):
    monkeypatch.setenv("RAGI_DATABASE_URL", f"sqlite:///{tmp_path / 'acc.db'}")
    monkeypatch.setenv("RAGI_SECRET_KEY", KEY)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    get_settings.cache_clear()
    try:
        return cli.main(argv)
    finally:
        get_settings.cache_clear()


def test_the_command_resets_a_password_from_a_pipe(monkeypatch, tmp_path, accounts, capsys):
    accounts.register("alice@example.com", OLD)
    assert run_cli(monkeypatch, tmp_path, ["users", "set-password", "alice@example.com"], NEW + "\n") == 0
    assert "Password changed for alice@example.com" in capsys.readouterr().out
    assert accounts.authenticate("alice@example.com", NEW) is not None

    assert run_cli(monkeypatch, tmp_path, ["users", "set-password", "nobody@example.com"], NEW + "\n") == 1
    assert "There is no account" in capsys.readouterr().err
    assert run_cli(monkeypatch, tmp_path, ["users", "set-password", "alice@example.com"], "short\n") == 2
    assert "Not changed" in capsys.readouterr().err
    assert run_cli(monkeypatch, tmp_path, ["users", "set-password"]) == 2  # the email is required
    assert accounts.authenticate("alice@example.com", NEW) is not None  # the failed attempts changed nothing
