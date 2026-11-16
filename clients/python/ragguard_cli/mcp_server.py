"""The RAGGuard MCP server: lets an AI assistant (Claude Code, Cursor, Claude Desktop, VS Code...) check a RAG index.

Run it with `ragguard mcp` (stdio). It needs RAGGUARD_API_KEY, and RAGGUARD_URL for a self-hosted server. Every tool calls the
RAGGuard API with that key, which can run audits and read results but cannot read connection settings or create other keys.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

try:  # mcp 2.x renamed FastMCP to MCPServer; the parts used here (name, instructions, .tool(), .run()) are the same in both
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .client import SEVERITIES, RagGuard, RagGuardError

INSTRUCTIONS = (
    "RAGGuard checks that a RAG (retrieval-augmented generation) index matches its source documents: missing, stale, "
    "half-indexed, duplicate, empty, deleted-but-still-searchable and wrong-tenant chunks. Use it after changing ingestion, "
    "chunking or embedding code, after a re-index, or when a user says the RAG app gave a wrong or outdated answer. "
    "Start with ragguard_status; run ragguard_run_audit for fresh results; read ragguard_get_issue for the evidence and the fix."
)

mcp = _Server("RAGGuard", instructions=INSTRUCTIONS)
_client: RagGuard | None = None


def client() -> RagGuard:
    global _client
    if _client is None:
        _client = RagGuard()
    return _client


def _issue(i: dict[str, Any]) -> dict[str, Any]:
    return {k: i.get(k) for k in ("id", "severity", "type", "title", "tenant_id", "document_id", "status", "detail")}


def _summary(ov: dict[str, Any]) -> dict[str, Any]:
    run = ov.get("latest_run") or {}
    return {
        "health_score": (ov.get("documents") or {}).get("health_score"),
        "documents": (ov.get("documents") or {}).get("total"),
        "open_issues": (ov.get("issues") or {}).get("open"),
        "open_issues_by_severity": (ov.get("issues") or {}).get("by_severity"),
        "latest_audit": {k: run.get(k) for k in ("id", "status", "started_at", "finished_at")} if run else None,
        "audit_running": ov.get("audit_running"),
    }


def _guard(fn):
    """Turn an API error into a message the assistant can act on, instead of a stack trace. functools.wraps keeps the
    signature, which the MCP framework reads to describe the tool's parameters."""
    returns_text = fn.__annotations__.get("return") in (str, "str")

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except RagGuardError as exc:
            return f"error: {exc}" if returns_text else {"error": str(exc)}

    return wrapper


@mcp.tool()
@_guard
def ragguard_status() -> dict[str, Any]:
    """The current health of the RAG index from the latest audit: health score (share of documents whose index matches the
    latest source exactly), document count, open issues by severity, and when the latest audit ran. Fast; runs no audit."""
    return _summary(client().status())


@mcp.tool()
@_guard
def ragguard_run_audit() -> dict[str, Any]:
    """Run a fresh audit of the RAG index against its source documents and wait for it to finish (can take minutes on a large
    index). Returns the audit's result and the open issues, most severe first. Use after ingestion or embedding changes."""
    rg = client()
    run = rg.run_audit()
    stats = run.get("stats") or {}
    out = {
        "audit": {"id": run.get("id"), "status": run.get("status"), "error": run.get("error"),
                  "documents_checked": stats.get("documents_total"), "findings": stats.get("findings_total"),
                  "health_score": stats.get("health_score"), "duration_seconds": stats.get("duration_seconds")},
        **_summary(rg.status()),
        "top_open_issues": [_issue(i) for i in rg.issues(limit=15)["items"]],
    }
    if run.get("status") == "partial":
        out["note"] = "The audit stopped part-way: the numbers cover the documents it reached."
    return out


@mcp.tool()
@_guard
def ragguard_list_issues(severity: str | None = None, limit: int = 25) -> dict[str, Any]:
    """Open integrity issues, most severe first. Optional severity filter: critical, high, medium, low or info. Each issue names
    its type (for example stale_embedding, orphan_vector, missing_embedding, tenant_mismatch), document and ID."""
    if severity and severity not in SEVERITIES:
        return {"error": f"severity must be one of {', '.join(SEVERITIES)}"}
    out = client().issues(severity=severity, limit=max(1, min(limit, 200)))
    return {"total": out["total"], "issues": [_issue(i) for i in out["items"]]}


@mcp.tool()
@_guard
def ragguard_get_issue(issue_id: str) -> dict[str, Any]:
    """One issue in full: what is wrong, the evidence (expected versus actual values RAGGuard read), the recommended repair
    action and its history. Use the ID from ragguard_list_issues or ragguard_run_audit."""
    return client().issue(issue_id)


@mcp.tool()
@_guard
def ragguard_check_document(document_id: str, tenant: str | None = None) -> dict[str, Any]:
    """Everything RAGGuard knows about one document: whether its source, the pipeline's records and the index agree, its
    chunk counts and hashes, and its open issues. Use when a user says an answer about that document is wrong or outdated."""
    return client().document(document_id, tenant=tenant)


@mcp.tool()
@_guard
def ragguard_report() -> str:
    """The full audit report as Markdown: totals, health by tenant, and every open issue with its evidence."""
    return client().report("md")


def serve() -> None:
    # stdout carries the MCP protocol; keep the request-by-request HTTP log out of the assistant's logs too
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()  # stdio
