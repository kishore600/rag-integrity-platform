from __future__ import annotations

import socket

import pytest

from ragintegrity import security as sec
from ragintegrity.security import (
    UnsafeTarget,
    Vault,
    VaultError,
    assert_public_host,
    assert_public_url,
    hash_password,
    normalize_email,
    password_problem,
    scrub,
    validate_postgres_url,
    verify_password,
)

KEY = "k" * 40


# ------------------------------------------------------------------------------------------------ passwords
def test_password_hash_roundtrip_and_uniqueness():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2  # per-user salt
    assert verify_password("correct horse battery", h1) and verify_password("correct horse battery", h2)
    assert not verify_password("wrong horse battery", h1)
    assert h1.startswith("scrypt$") and "correct" not in h1


def test_verify_rejects_garbage_without_raising():
    for bad in ("", "plain", "scrypt$1$2$3$x$y", "md5$a$b$c$d$e", "scrypt$notint$8$1$AAAA$AAAA"):
        assert verify_password("x", bad) is False


def test_password_policy():
    assert password_problem("short1", "a@b.co")
    assert password_problem("password123", "a@b.co")  # common
    assert password_problem("aaaaaaaaaaaa", "a@b.co")  # one repeated character
    assert password_problem("alice-is-great-1", "alice@example.com")  # contains the email name
    assert password_problem("x" * 200, "a@b.co")
    assert password_problem("a-long-unusual-passphrase", "a@b.co") is None


def test_email_normalisation():
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"
    for bad in ("", "nope", "a@b", "a b@c.com", "x@" + "y" * 300 + ".com"):
        with pytest.raises(ValueError):
            normalize_email(bad)


# ------------------------------------------------------------------------------------------------ vault
def test_vault_roundtrip_and_ciphertext_hides_plaintext():
    v = Vault(KEY)
    token = v.encrypt({"secret_access_key": "AKIA-super-secret", "n": 1})
    assert "AKIA-super-secret" not in token
    assert v.decrypt(token) == {"secret_access_key": "AKIA-super-secret", "n": 1}


def test_vault_wrong_key_and_tampering_are_detected():
    token = Vault(KEY).encrypt({"a": "b"})
    with pytest.raises(VaultError):
        Vault("z" * 40).decrypt(token)
    with pytest.raises(VaultError):
        Vault(KEY).decrypt(token[:-4] + "AAAA")


def test_vault_key_rotation_and_validation():
    old = Vault(KEY)
    token = old.encrypt({"a": 1})
    rotated = Vault("n" * 40 + "," + KEY)  # new key first, old key still decrypts
    assert rotated.decrypt(token) == {"a": 1}
    assert Vault("n" * 40).decrypt(rotated.encrypt({"b": 2})) == {"b": 2}  # new data is under the new key only
    with pytest.raises(VaultError):
        Vault("n" * 40).decrypt(token)
    with pytest.raises(VaultError):
        Vault(None)
    with pytest.raises(VaultError):
        Vault("too-short")


# ------------------------------------------------------------------------------------------------ SSRF guard
@pytest.mark.parametrize("host", [
    "127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.5.5", "169.254.169.254",  # incl. the cloud metadata address
    "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "localhost", "db.internal", "printer.local",
])
def test_private_and_reserved_hosts_are_refused(host):
    with pytest.raises(UnsafeTarget):
        assert_public_host(host)


def test_public_literals_are_allowed_and_override_works():
    assert_public_host("93.184.216.34")
    assert_public_host("2606:4700:4700::1111")
    assert_public_host("127.0.0.1", allow_private=True)  # self-hosting escape hatch


def test_hostnames_are_resolved_and_every_address_must_be_public(monkeypatch):
    def fake(host, port, **kw):
        table = {"good.example": ["93.184.216.34"], "bad.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "169.254.169.254"]}
        if host not in table:
            raise socket.gaierror("nope")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    monkeypatch.setattr(sec.socket, "getaddrinfo", fake)
    assert_public_host("good.example")
    with pytest.raises(UnsafeTarget):
        assert_public_host("bad.example")  # a public-looking name pointing inside the network
    with pytest.raises(UnsafeTarget):
        assert_public_host("mixed.example")  # one bad record is enough (DNS rebinding)
    with pytest.raises(UnsafeTarget, match="resolve"):
        assert_public_host("unknown.example")


def test_url_rules(monkeypatch):
    for bad in ("ftp://93.184.216.34/x", "http://user:pw@93.184.216.34/", "https:///nohost", "javascript:alert(1)",
                "http://[::1]:6333", "http://169.254.169.254/latest/meta-data", "https://93.184.216.34:99999"):
        with pytest.raises(UnsafeTarget):
            assert_public_url(bad)
    assert assert_public_url("https://93.184.216.34:6333/") == "https://93.184.216.34:6333/"


def test_postgres_url_rules():
    ok = "postgresql://u:p@93.184.216.34:5432/db?sslmode=require"
    assert validate_postgres_url(ok) == ok
    assert validate_postgres_url("postgres://u:p@93.184.216.34/db") == "postgres://u:p@93.184.216.34/db"
    for bad in (
        "mysql://u:p@93.184.216.34/db",
        "postgresql://u:p@127.0.0.1/db",
        "postgresql://u:p@10.0.0.4:5432/db",
        "postgresql://u:p@/db?host=/var/run/postgresql",  # unix socket
        "postgresql://u:p@93.184.216.34/db?hostaddr=10.0.0.4",  # would bypass the host check
        "postgresql://u:p@93.184.216.34/db?options=-c%20search_path%3Devil",
        "not a url",
    ):
        with pytest.raises(UnsafeTarget):
            validate_postgres_url(bad)
    validate_postgres_url("postgresql://u:p@127.0.0.1:5499/db", allow_private=True)


def test_scrub_removes_passwords_from_messages():
    msg = "could not connect to postgresql://admin:Sup3rS3cret!@db.example.com:5432/app (timeout)"
    out = scrub(msg)
    assert "Sup3rS3cret" not in out and "admin" in out and "***@db.example.com" in out
    assert scrub("x" * 1000, limit=50) == "x" * 50
