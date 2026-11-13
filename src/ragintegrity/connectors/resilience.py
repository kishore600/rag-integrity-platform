"""Retrying a request to the customer's own infrastructure without turning a hiccup into a false finding.

A scan of millions of vectors makes thousands of requests. One timed-out page, one rate-limit answer or one dropped connection
must not abort the audit, and must never make documents look missing. Requests that fail for a reason that can pass
(a timeout, a dropped connection, HTTP 408/425/429/500/502/503/504) are retried with exponential backoff and jitter, honouring
a ``Retry-After`` header, and never past the audit's time budget. Requests that fail because the server refused them
(400, 401, 403, 404: wrong key, missing index, no such collection) are NOT retried: asking again changes nothing.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from .base import AuditTimeout, ScanStats

T = TypeVar("T")

TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_TRANSIENT_NAMES = frozenset({
    "ResponseHandlingException", "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout", "TimeoutException",
    "ConnectError", "ReadError", "WriteError", "RemoteProtocolError", "ProtocolError", "ConnectionError", "ServerDisconnectedError",
})
_TRANSIENT_WORDS = ("timed out", "timeout", "temporarily unavailable", "connection reset", "connection aborted", "broken pipe",
                    "server disconnected", "too many requests", "service unavailable")


def retry_after_seconds(exc: BaseException) -> float | None:
    """The delay a server asked for in a ``Retry-After`` header (seconds), if the error carries headers."""
    headers = getattr(exc, "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
        return max(0.0, min(float(value), 60.0)) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def classify(exc: BaseException) -> tuple[bool, float | None]:
    """(is this failure worth retrying, how long the server asked us to wait)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in TRANSIENT_STATUS, (retry_after_seconds(exc) if status in TRANSIENT_STATUS else None)
    if isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in _TRANSIENT_NAMES:
        return True, None
    text = str(exc).lower()
    return any(w in text for w in _TRANSIENT_WORDS), None


def call_with_retry(
    fn: Callable[[], T], *, stats: ScanStats | None = None, deadline: float | None = None, attempts: int = 4,
    base_delay: float = 0.5, max_delay: float = 10.0, sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> T:
    """Call ``fn``; retry what is worth retrying, count what happened in ``stats``, and re-raise what cannot be fixed."""
    attempt = 0
    while True:
        attempt += 1
        try:
            result = fn()
        except AuditTimeout:
            raise
        except Exception as exc:
            transient, asked = classify(exc)
            if not transient or attempt >= attempts:
                if stats is not None:
                    stats.unrecoverable_errors += 1
                raise
            delay = asked if asked is not None else min(max_delay, base_delay * 2 ** (attempt - 1)) * (0.5 + jitter() / 2)
            if deadline is not None and time.monotonic() + delay >= deadline:  # never sleep past the time budget
                if stats is not None:
                    stats.unrecoverable_errors += 1
                raise
            if stats is not None:
                stats.retries += 1
                stats.waited_seconds += delay
                if getattr(exc, "status_code", None) == 429:
                    stats.rate_limited += 1
            sleep(delay)
            continue
        if attempt > 1 and stats is not None:
            stats.recovered_errors += 1
        return result


def describe(exc: BaseException) -> str:
    """A short reason for a stopped scan, safe to show."""
    return f"{type(exc).__name__}: {str(exc)[:200]}"


__all__ = ["call_with_retry", "classify", "describe", "retry_after_seconds", "TRANSIENT_STATUS"]


