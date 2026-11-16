"""The `ragguard` command (clients/python) against a real RAGGuard server, in-process: the demo world, with an API key.

The MCP tools are covered when the optional `mcp` package is installed (it is not a dependency of the server).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "clients" / "python"))

from ragguard_cli import RagGuard, RagGuardError  # noqa: E402
from ragguard_cli.cli import main  # noqa: E402

from ragintegrity.api.app import create_app  # noqa: E402
from ragintegrity.config import Settings  # noqa: E402

KEY = "test-api-key-0123456789"


def server(tmp_path, **kw) -> TestClient:
    settings = Settings(_env_file=None, mode="demo", database_url=f"sqlite:///{tmp_path / 'cli.db'}", api_key=KEY, **kw)
    return TestClient(create_app(settings=settings))


def run(tc: TestClient, *argv: str, key: str = KEY) -> int:
    return main(list(argv), client=RagGuard(api_key=key, http=tc))


def test_check_runs_an_audit_and_fails_on_open_issues(tmp_path, capsys):
    with server(tmp_path) as tc:
        code = run(tc, "check", "--fail-on", "info", "--top", "3")
        out = capsys.readouterr().out
        assert "RAGGuard audit" in out and "completed" in out and "Open issues, most severe first:" in out
        assert code == 1  # the demo world has planted problems, so "anything at all" fails
        assert run(tc, "check", "--json", "--top", "0") in (0, 1)
        data = json.loads(capsys.readouterr().out)
        assert data["run"]["status"] == "completed" and data["overview"]["documents"]["total"] > 0


def test_a_queued_audit_is_driven_to_the_end(tmp_path, capsys):
    """With RAGI_AUDIT_QUEUE the server only queues the audit; like the dashboard, the command does the worker's job."""
    with server(tmp_path, audit_queue=True) as tc:
        run_ = RagGuard(api_key=KEY, http=tc).run_audit(poll=0.05)
        assert run_["status"] == "completed" and (run_["stats"] or {}).get("documents_total", 0) > 0


def test_status_issues_issue_document_and_report(tmp_path, capsys):
    with server(tmp_path) as tc:
        assert run(tc, "status") == 0 and "health score" in capsys.readouterr().out
        assert run(tc, "issues", "--json", "--limit", "5") == 0
        issues = json.loads(capsys.readouterr().out)["items"]
        assert issues, "the demo world has open issues"
        sev = [i["severity"] for i in issues]
        order = ["critical", "high", "medium", "low", "info"]
        assert sev == sorted(sev, key=order.index)  # most severe first
        first = issues[0]
        assert run(tc, "issue", first["id"]) == 0
        shown = capsys.readouterr().out
        assert first["title"] in shown and "fix      :" in shown and "evidence :" in shown
        assert run(tc, "document", first["document_id"], "--tenant", first["tenant_id"], "--json") == 0
        assert json.loads(capsys.readouterr().out)["document"]["document_id"] == first["document_id"]
        assert run(tc, "document", first["document_id"]) == 0  # found without the tenant when the ID is unique
        capsys.readouterr()
        assert run(tc, "report") == 0 and capsys.readouterr().out.startswith("#")


def test_errors_are_explained_and_exit_2(tmp_path, capsys):
    with server(tmp_path) as tc:
        assert run(tc, "status", key="wrong-key") == 2
        assert "refused the API key" in capsys.readouterr().err
        assert run(tc, "document", "no-such-document.pdf") == 2
        assert "has no document" in capsys.readouterr().err
    with pytest.raises(RagGuardError, match="No API key"):
        RagGuard(api_key="")


def test_the_mcp_tools(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from ragguard_cli import mcp_server

    with server(tmp_path) as tc:
        monkeypatch.setattr(mcp_server, "_client", RagGuard(api_key=KEY, http=tc))
        tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
        assert set(tools) == {"ragguard_status", "ragguard_run_audit", "ragguard_list_issues", "ragguard_get_issue",
                              "ragguard_check_document", "ragguard_report"}

        def schema(name: str) -> dict:  # mcp 2.x names it input_schema, 1.x inputSchema
            t = tools[name]
            return getattr(t, "input_schema", None) or t.inputSchema

        assert set(schema("ragguard_list_issues")["properties"]) == {"severity", "limit"}
        assert schema("ragguard_check_document")["required"] == ["document_id"]
        audit = mcp_server.ragguard_run_audit()
        assert audit["audit"]["status"] == "completed" and audit["top_open_issues"]
        assert mcp_server.ragguard_status()["documents"] > 0
        assert mcp_server.ragguard_list_issues(severity="nope") == {"error": "severity must be one of critical, high, medium, low, info"}
        issue = mcp_server.ragguard_list_issues(limit=1)["issues"][0]
        assert mcp_server.ragguard_get_issue(issue["id"])["id"] == issue["id"]
        assert "error" in mcp_server.ragguard_check_document("no-such-document.pdf")
        assert mcp_server.ragguard_report().startswith("#")
