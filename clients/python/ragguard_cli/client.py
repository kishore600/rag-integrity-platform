"""A small client for the RAGGuard HTTP API, used by the `ragguard` command and the MCP server.

It authenticates with an API key (create one on the Integrations page of RAGGuard), which can run audits and read results but
cannot read connection settings or create other keys. Every call is a plain HTTPS request; nothing is cached on disk.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import httpx

DEFAULT_URL = "https://rag-integrity-platform.vercel.app"
SEVERITIES = ("critical", "high", "medium", "low", "info")  # most severe first
FINAL = ("completed", "failed")
MAX_STRETCHES = 500  # a safety stop for a queued audit: a 4-million-vector index is a few dozen stretches


class RagGuardError(Exception):
    """Anything that went wrong talking to RAGGuard, in words a person can act on."""


class RagGuard:
    def __init__(self, url: str | None = None, api_key: str | None = None, *, http: httpx.Client | None = None,
                 timeout: float = 330.0) -> None:
        self.url = (url or os.environ.get("RAGGUARD_URL") or DEFAULT_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("RAGGUARD_API_KEY", "")
        if not self.api_key and http is None:
            raise RagGuardError("No API key. Create one on the Integrations page of RAGGuard and set RAGGUARD_API_KEY.")
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": "ragguard-cli"}
        if http is not None:  # tests pass an in-process client
            http.headers.update(headers)
            self.http = http
        else:
            # an audit started on a serverless host can run inside the request for several minutes
            self.http = httpx.Client(base_url=self.url, headers=headers, timeout=timeout)

    # ------------------------------------------------------------------ plumbing
    def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise RagGuardError(f"Could not reach RAGGuard at {self.url}: {type(exc).__name__}: {exc}") from exc
        if r.status_code == 401:
            raise RagGuardError("RAGGuard refused the API key. Check RAGGUARD_API_KEY, or create a new key on the Integrations page.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:300]
            raise RagGuardError(f"RAGGuard answered {r.status_code}: {detail}")
        return r

    def _json(self, method: str, path: str, **kw: Any) -> Any:
        return self._call(method, path, **kw).json()

    # ------------------------------------------------------------------ reads
    def status(self) -> dict[str, Any]:
        """The overview: health score, document and issue counts, and the latest audit."""
        return self._json("GET", "/api/overview")

    def audit(self, run_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/audits/{run_id}")

    def issues(self, *, severity: str | None = None, status: str = "open", limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"status": status, "limit": limit}
        if severity:
            params["severity"] = severity
        out = self._json("GET", "/api/issues", params=params)
        out["items"].sort(key=lambda i: SEVERITIES.index(i.get("severity", "info")) if i.get("severity") in SEVERITIES else 9)
        return out

    def issue(self, issue_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/issues/{issue_id}")

    def document(self, document_id: str, tenant: str | None = None) -> dict[str, Any]:
        """One document's state and issues. Without a tenant, the document is looked up by its ID first."""
        if tenant is None:
            found = self._json("GET", "/api/documents", params={"q": document_id, "status": "all", "limit": 50})["items"]
            exact = [d for d in found if d.get("document_id") == document_id]
            if not exact:
                raise RagGuardError(f"RAGGuard has no document with the ID {document_id!r}. Run an audit first, or check the ID.")
            if len({d.get("tenant_id") for d in exact}) > 1:
                tenants = ", ".join(sorted(str(d.get("tenant_id")) for d in exact))
                raise RagGuardError(f"{document_id!r} exists for several tenants ({tenants}). Say which one.")
            tenant = exact[0]["tenant_id"]
        return self._json("GET", "/api/document", params={"tenant": tenant, "document_id": document_id})

    def report(self, fmt: str = "md") -> str:
        return self._call("GET", "/api/report", params={"format": fmt}).text

    # ------------------------------------------------------------------ the audit
    def run_audit(self, *, timeout: float = 1800.0, poll: float = 3.0,
                  on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Start an audit and wait for it to end; returns the finished run (with its stats).

        On a server with a queue (RAGI_AUDIT_QUEUE), the audit waits for a worker; like the dashboard, this then does the worker's job
        itself, one stretch at a time, until the audit is over. A real worker is never in the way: whoever claims a stretch first gets
        it, and this call then simply waits.
        """
        say = on_progress or (lambda _msg: None)
        deadline = time.monotonic() + timeout
        start = self._json("POST", "/api/audits", json={})
        run_id, status = start["run_id"], start["status"]
        say(f"audit {run_id[:8]} {status}")
        if status == "queued":
            for _ in range(MAX_STRETCHES):
                if time.monotonic() > deadline:
                    raise RagGuardError(f"The audit is still going after {int(timeout)} s. Check it later with `ragguard status`.")
                out = self._json("POST", "/api/worker/step")
                if out.get("run_id"):
                    run_id = out["run_id"]
                if out.get("percent") is not None:
                    say(f"{out['percent']:.0f}% done")
                if out["status"] == "partial" and out.get("next"):
                    continue  # this stretch stopped part-way and queued the next one
                if out["status"] != "idle":
                    break
                status = self.audit(run_id)["status"]  # idle: a real worker has it, so wait for it
                if status in FINAL or status == "partial":
                    break
                time.sleep(poll)
        while True:
            run = self.audit(run_id)
            if run["status"] in FINAL or run["status"] == "partial":
                return run
            if time.monotonic() > deadline:
                raise RagGuardError(f"The audit is still going after {int(timeout)} s. Check it later with `ragguard status`.")
            time.sleep(poll)


def worst_open(by_severity: dict[str, int], at_least: str) -> int:
    """How many open issues are at or above a severity."""
    cut = SEVERITIES.index(at_least)
    return sum(n for sev, n in (by_severity or {}).items() if sev in SEVERITIES and SEVERITIES.index(sev) <= cut)
