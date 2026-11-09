"""Security primitives for the multi-user app: password hashing, the secret vault, SSRF guard, validation.

Design notes
* Passwords: scrypt (stdlib, memory-hard) with a per-user salt; verification is constant-time and an unknown email
  still burns the same CPU, so login timing does not reveal which emails exist.
* Vault: connection secrets (S3 keys, database URLs, API keys) are encrypted at rest with Fernet (AES-128-CBC +
  HMAC-SHA256) under RAGI_SECRET_KEY, which only ever lives in the server environment, never in the database.
* SSRF: users type hostnames that *this server* will connect to. Every such target is resolved and must be a
  public address; private, loopback, link-local and metadata ranges are refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from .config import normalize_db_url

# ---------------------------------------------------------------------------------------------- passwords
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD, MAX_PASSWORD = 10, 128
COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "1234567890", "12345678901", "qwertyuiop", "qwerty12345", "iloveyou123",
    "letmein1234", "welcome1234", "admin12345", "changeme123", "abc1234567", "passw0rd123", "0123456789",
})


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(dk, _unb64(digest))
    except (ValueError, TypeError):
        return False


_DUMMY: str | None = None


def burn_password_time(password: str) -> None:
    """Spend the same time as a real verification (used when the email is unknown)."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not-a-real-password")
    verify_password(password, _DUMMY)


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Password must be at most {MAX_PASSWORD} characters."
    low = password.lower()
    if low in COMMON_PASSWORDS or len(set(low)) < 4:
        return "That password is too easy to guess."
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in low:
        return "Password must not contain your email name."
    return None


_URL_CREDS = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://[^:@\s/]+:)[^@\s]+(@)")


def scrub(message: str, limit: int = 400) -> str:
    """Strip passwords out of anything we are about to show a user or write to the ledger."""
    return _URL_CREDS.sub(r"\1***\2", str(message))[:limit]


_ANY_URL = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
# httpx quotes the raw Location header of a 3xx answer, which may be relative ("/services/T0/B0/token") and so has no scheme
_REDIRECT_TARGET = re.compile(r"(redirect location: ')[^'\r\n]*(')", re.IGNORECASE)


def _address_pieces(url: str) -> list[str]:
    """The parts of an address that a library can echo without its scheme (a TLS error names the host): path, query,
    user info and host, longest first. Very short parts are skipped so ordinary words are not rewritten."""
    try:
        p = urlparse(url.strip())
        parts = {p.path, p.query, p.username, p.password, p.hostname}
    except ValueError:
        return []
    return sorted((x for x in parts if x and len(x) >= 4), key=len, reverse=True)


def redact_urls(message: str, *secret_urls: str | None) -> str:
    """Remove web addresses from an error message before it is stored, logged or shown.

    A webhook address is a secret (a Slack webhook carries its token in the path), and HTTP client errors quote the
    address they failed on. The exact configured addresses go first, then their separate parts (host, path, query,
    user info) wherever they appear without the scheme, then the target of a redirect (even a relative one), then any
    other address."""
    text = str(message)
    for url in secret_urls:
        if url:
            text = text.replace(url, "<webhook>")
            for piece in _address_pieces(url):
                text = text.replace(piece, "<webhook>")
    text = _REDIRECT_TARGET.sub(r"\1<url>\2", text)
    return _ANY_URL.sub("<url>", text)


# ---------------------------------------------------------------------------------------------- email / tokens
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------------------------- vault
class VaultError(RuntimeError):
    pass


class Vault:
    """Encrypts small JSON documents (connection secrets). RAGI_SECRET_KEY may list several keys, comma separated:
    the first encrypts, all decrypt, so keys can be rotated without re-entering secrets."""

    MIN_KEY_CHARS = 32

    def __init__(self, keys: str | None) -> None:
        from cryptography.fernet import Fernet, MultiFernet

        parts = [k.strip() for k in (keys or "").split(",") if k.strip()]
        if not parts:
            raise VaultError("RAGI_SECRET_KEY is not set")
        if any(len(k) < self.MIN_KEY_CHARS for k in parts):
            raise VaultError(f"RAGI_SECRET_KEY must be at least {self.MIN_KEY_CHARS} characters of randomness")
        self._fernet = MultiFernet([Fernet(self._derive(k)) for k in parts])

    @staticmethod
    def _derive(key: str) -> bytes:
        return base64.urlsafe_b64encode(hmac.new(b"ragi-vault-v1", key.encode(), hashlib.sha256).digest())

    def encrypt(self, data: dict[str, Any]) -> str:
        return self._fernet.encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()

    def decrypt(self, token: str) -> dict[str, Any]:
        from cryptography.fernet import InvalidToken

        try:
            return json.loads(self._fernet.decrypt(token.encode()))
        except InvalidToken as exc:
            raise VaultError("Stored secrets cannot be decrypted with the current RAGI_SECRET_KEY") from exc


# ---------------------------------------------------------------------------------------------- SSRF guard
class UnsafeTarget(ValueError):
    pass


def _is_public(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def assert_public_host(host: str | None, port: int | None = None, allow_private: bool = False) -> None:
    """Refuse hosts that are, or resolve to, anything but a public address."""
    if allow_private:
        return
    host = (host or "").strip().strip("[]")
    if not host:
        raise UnsafeTarget("A host name is required.")
    try:
        if not _is_public(host):
            raise UnsafeTarget(f"{host} is a private or reserved address; only public hosts are allowed.")
        return
    except ValueError:
        pass  # not an IP literal: resolve it
    low = host.lower()
    if low == "localhost" or low.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise UnsafeTarget(f"{host} is not a public host name.")
    try:
        infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeTarget(f"Could not resolve {host}.") from exc
    if not infos:
        raise UnsafeTarget(f"Could not resolve {host}.")
    for _fam, _t, _p, _c, sockaddr in infos:
        if not _is_public(sockaddr[0]):
            raise UnsafeTarget(f"{host} resolves to a private or reserved address; only public hosts are allowed.")


def assert_public_url(url: str, allow_private: bool = False, schemes: tuple[str, ...] = ("https", "http")) -> str:
    p = urlparse((url or "").strip())
    if p.scheme not in schemes:
        raise UnsafeTarget(f"URL must start with {' or '.join(s + '://' for s in schemes)}.")
    if p.username or p.password:
        raise UnsafeTarget("Do not put credentials inside the URL.")
    try:
        port = p.port
    except ValueError as exc:
        raise UnsafeTarget("Invalid port in URL.") from exc
    assert_public_host(p.hostname, port, allow_private)
    return url.strip()


PG_QUERY_ALLOWLIST = {"sslmode", "connect_timeout", "application_name"}


def validate_postgres_url(url: str, allow_private: bool = False) -> str:
    """Parse a Postgres connection string and make sure it can only point at a public host."""
    try:
        u = make_url(normalize_db_url((url or "").strip()))
    except Exception as exc:
        raise UnsafeTarget("That is not a valid database URL.") from exc
    if u.get_backend_name() != "postgresql":
        raise UnsafeTarget("Only postgresql:// connection strings are supported.")
    if not u.host or u.host.startswith("/"):
        raise UnsafeTarget("The database URL needs a network host (unix sockets are not allowed).")
    bad = set(u.query) - PG_QUERY_ALLOWLIST
    if bad:
        raise UnsafeTarget(f"Unsupported connection option(s): {', '.join(sorted(bad))}. Allowed: {', '.join(sorted(PG_QUERY_ALLOWLIST))}.")
    if u.port is not None and not 0 < u.port < 65536:
        raise UnsafeTarget("Invalid database port.")
    assert_public_host(u.host, u.port or 5432, allow_private)
    return (url or "").strip()
