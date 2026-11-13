"""GUIDE.md is the full reference for the product. It must never drift from the code it describes.

Every settings field, route, issue type, action, environment variable, CLI command, database table and column
that exists in the code has to be mentioned in the guide; the test fails (naming what is missing) when someone
adds or renames one without documenting it.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from ragintegrity.api.app import create_app
from ragintegrity.cli import build_parser
from ragintegrity.config import Settings
from ragintegrity.connectors.payload import CANONICAL_FIELDS
from ragintegrity.connectors.postgres import CHUNK_COLUMNS, DOC_COLUMNS
from ragintegrity.ledger import build_tables
from ragintegrity.models import Action, IssueType
from ragintegrity.workspaces import SPECS

ROOT = Path(__file__).parent.parent
GUIDE = (ROOT / "GUIDE.md").read_text(encoding="utf-8")

def missing(items, text=GUIDE):
    return sorted({str(i) for i in items if str(i) not in text})


def test_guide_exists_and_is_linked_from_the_readme():
    assert len(GUIDE) > 20_000
    assert "GUIDE.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_settings_group_and_field_is_documented():
    problems = []
    for kind, spec in SPECS.items():
        if spec.title not in GUIDE:
            problems.append(f"group title: {spec.title}")
        for f in spec.fields:
            for what, needle in (("label", f.label), ("key", f"`{f.name}`"), ("env var", f"`RAGI_{f.setting.upper()}`")):
                if needle not in GUIDE:
                    problems.append(f"{kind}.{f.name}: {what} {needle}")
            for choice in f.choices:
                if choice not in GUIDE:
                    problems.append(f"{kind}.{f.name}: choice {choice}")
    assert not problems, "GUIDE.md is missing:\n" + "\n".join(problems)


def test_documented_defaults_match_the_code():
    """A default quoted in the guide's field tables must be the real one."""
    defaults = Settings.model_fields
    problems = []
    for spec in SPECS.values():
        for f in spec.fields:
            default = defaults[f.setting].default
            if isinstance(default, (str, int, float)) and not isinstance(default, bool) and default not in ("", None):
                row = next((ln for ln in GUIDE.splitlines() if ln.startswith(f"| **{f.label}**")), None)
                if row is not None and str(default) not in row:
                    problems.append(f"{f.label}: code default {default!r} not in its row")
    assert not problems, "\n".join(problems)


def test_every_environment_variable_is_documented():
    names = [f"RAGI_{n.upper()}" for n in Settings.model_fields]
    gap = missing(names)
    assert not gap, f"undocumented environment variables: {gap}"


def test_every_issue_type_and_action_is_documented():
    assert not missing(f"`{t.value}`" for t in IssueType)
    assert not missing(f"`{a.value}`" for a in Action)


def test_every_route_is_documented():
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    app = create_app(settings=Settings(_env_file=None, mode="app", database_url=f"sqlite:///{(tmp / 'x.db').as_posix()}", secret_key="k" * 40))
    paths = {
        r.path for r in app.routes
        if getattr(r, "methods", None) and r.path.startswith(("/api", "/healthz")) or getattr(r, "path", "") == "/"
    }
    gap = missing(f"`{p}`" for p in paths)
    assert not gap, f"undocumented routes: {gap}"


def test_every_page_in_the_menu_has_a_section():
    nav = ROOT / "frontend" / "src" / "components" / "layout" / "nav.ts"
    if not nav.exists():
        pytest.skip("the web interface sources are not part of this checkout")
    labels = re.findall(r'label:\s*"([^"]+)"', nav.read_text(encoding="utf-8"))
    assert len(labels) >= 9
    gap = [label for label in labels if f"### {label}\n" not in GUIDE]
    assert not gap, f"menu pages without a '### <page>' section in GUIDE.md: {gap}"


def test_every_cli_command_is_documented():
    parser = build_parser()
    sub = parser._subparsers._group_actions[0].choices
    gap = missing(f"ragi {name}" for name in sub)
    assert not gap, f"undocumented commands: {gap}"
    flags = {
        o for sp in sub.values() for a in sp._actions if not isinstance(a, argparse._HelpAction) for o in a.option_strings if o.startswith("--")
    }
    assert not missing(flags), f"undocumented flags: {missing(flags)}"


def test_every_table_and_column_is_documented():
    _, tables = build_tables(None)
    problems = []
    for name, table in tables.items():
        if f"`{name}`" not in GUIDE:
            problems.append(f"table {name}")
            continue
        row = next((ln for ln in GUIDE.splitlines() if ln.startswith(f"| `{name}` |")), "")
        problems += [f"{name}.{c.name}" for c in table.c if c.name not in row]
    assert not problems, f"undocumented tables or columns: {problems}"


def test_every_manifest_column_and_payload_field_is_documented():
    assert not missing(f"`{c}`" for c in (*DOC_COLUMNS, *CHUNK_COLUMNS))
    assert not missing(f"`{f}`" for f in CANONICAL_FIELDS)


def test_numbers_quoted_in_the_guide_match_the_code():
    """Limits quoted in prose are checked against the constants and calls that enforce them."""
    assert len(DOC_COLUMNS) == 21 and "of the 21 columns" in GUIDE
    app_py = (ROOT / "src" / "ragintegrity" / "api" / "app.py").read_text(encoding="utf-8")
    assert re.search(r"MAX_API_KEYS = 20\b", app_py) and "Up to 20 keys per workspace" in GUIDE
    assert "8 sign-in attempts per account and 30 per network per 15 minutes" in GUIDE
    assert 'hit(f"login:ip:{ip}", 30, 900)' in app_py and "email_key, 8, 900" in app_py
    assert 'hit(f"register:ip:{ip}", 5, 3600)' in app_py
    assert 'hit(f"test:{p.workspace_id}", 30, 600)' in app_py
    assert 'hit(f"password:{p.user_id}", 10, 900)' in app_py
    assert 'hit(f"setup-check:{p.workspace_id}", 20, 600)' in app_py and 'hit(f"deletion-check:{p.workspace_id}", 20, 600)' in app_py
    assert "20 setup checks and 20 deletion checks per workspace per 10 minutes" in GUIDE


def test_every_setup_check_and_id_warning_is_documented():
    """The checks of the setup check (3.10) and the ID warnings of an audit (3.4) are named in the guide by their codes,
    and the limits and thresholds quoted in 3.10 are the ones in the code."""
    from ragintegrity.engine import coverage

    src = (ROOT / "src" / "ragintegrity" / "engine" / "coverage.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'_check\(\s*"(\w+)"', src)) | set(re.findall(r'"code": "(\w+)"', src))
    assert len(codes) >= 13
    assert not missing(f"`{c}`" for c in codes)
    section = GUIDE[GUIDE.index("### 3.10 "):GUIDE.index("## 4. The interface")]
    for name in ("MAX_SOURCE_OBJECTS", "MAX_MANIFEST_ROWS", "INDEX_SAMPLE", "INDEX_LOOKUP_DOCS", "INDEX_LOOKUP_POINTS",
                 "INDEX_LOOKUP_SECONDS"):
        assert f"{getattr(coverage, name):,}" in section, f"3.10 does not state {name} = {getattr(coverage, name):,}"
    assert f"starts at {round(coverage.ALIGNED * 100)}%" in section and f"{round(coverage.PARTIAL * 100)}%" in section


def _section(start: str, end: str) -> str:
    return GUIDE[GUIDE.index(start):GUIDE.index(end)]


def test_version_integrity_section_names_every_verdict_and_every_table_row():
    from ragintegrity.engine import versions

    section = _section("### 3.11 ", "### 3.12 ")
    assert not missing((f"`{v}`" for v in versions.TITLES), section), "3.11 does not name every verdict"
    for prop in ("Source version", "Source hash", "Chunk count (any revision)", "Chunks of the current revision", "Chunk IDs", "Chunk hashes"):
        assert prop in section, prop
    for word in ("current", "older_revision", "older_config", "revision_unknown"):
        assert f"`{word}`" in section, word
    for status in ("match", "mismatch", "partial", "unknown"):
        assert f"`{status}`" in section, status


def test_scan_reliability_section_matches_the_code():
    import inspect

    from ragintegrity.connectors.base import ScanStats
    from ragintegrity.connectors.resilience import TRANSIENT_STATUS, call_with_retry
    from ragintegrity.engine.audit import SLICE_DOCUMENTS, scan_block

    section = _section("### 3.12 ", "### 3.13 ")
    params = inspect.signature(call_with_retry).parameters
    assert params["attempts"].default == 4 and "up to 4 times" in section
    assert params["base_delay"].default == 0.5 and "0.5 s" in section
    assert params["max_delay"].default == 10.0 and "at most 10 s" in section
    resilience_src = (ROOT / "src" / "ragintegrity" / "connectors" / "resilience.py").read_text(encoding="utf-8")
    assert "min(float(value), 60.0)" in resilience_src and "at most 60 s" in section
    assert not missing((f"`{s}`" for s in sorted(TRANSIENT_STATUS)), section), "3.12 does not list every retried HTTP status"
    assert SLICE_DOCUMENTS == 5000 and "default 5000" in section and Settings.model_fields["audit_slice_documents"].default == SLICE_DOCUMENTS
    block = scan_block("completed", ScanStats(), mode="sliced")
    assert not missing((f"`{k}`" for k in block), section), "3.12 does not document every stats.scan field"
    for state in ("running", "completed", "partial", "failed"):
        assert f"`{state}`" in section, state
    assert "`resumable_audit`" in section and "--resume" in section and '"resume": true' in section


def test_deletion_verification_section_matches_the_code():
    import inspect

    from ragintegrity.engine import deletions
    from ragintegrity.service import IntegrityService

    section = _section("### 3.13 ", "---\n\n## 4. ")
    assert not missing((f"`{v}`" for v in deletions.VERDICTS), section), "3.13 does not name every verdict"
    assert deletions.PROBES_PER_DOCUMENT == 3 and "up to 3 of the document's chunks" in section
    assert deletions.TOP_K == 10 and "top 10" in section
    assert inspect.signature(IntegrityService.verify_deletions).parameters["max_documents"].default == 200 and "At most 200 per check" in section
    for check in ("Source document", "Manifest status", "Vector chunks found", "Retrieval test"):
        assert check in section, check
    for field in ("documents_checked", "with_remaining_vectors", "verified_gone"):
        assert f"`{field}`" in section, field


def test_notifications_section_matches_the_code():
    from ragintegrity import mailer, notifications
    from ragintegrity.ledger import Ledger

    section = _section("### 3.14 ", "---\n\n## 4. ")
    samples = [
        {"status": "completed", "stats": {"findings_total": 0}},
        {"status": "completed", "stats": {"findings_total": 3, "findings_by_severity": {"critical": 1}, "findings_by_type": {"orphan_vector": 1}}},
        {"status": "completed", "stats": {"findings_total": 3, "findings_by_severity": {"high": 3}}},
        {"status": "completed", "stats": {"findings_total": 3, "findings_by_severity": {"low": 3}}},
        {"status": "partial", "stats": {"findings_total": 1, "findings_by_severity": {"high": 1}, "scan": {"documents_done": 1, "documents_total": 2}}},
        {"status": "failed", "stats": {}},
    ]
    labels, kinds = set(), set()
    for s in samples:
        n = notifications.compose(run_id="r", kind="full", trigger="manual", diff=None, error="x", **s)
        kinds.add(n.kind)
        labels.update(a["label"] for a in n.actions)
    assert not missing(labels, section), "3.14 does not name every button"
    assert not missing((f"`{k}`" for k in kinds), section), "3.14 does not name every notification kind"
    assert not missing((f"`{t}`" for t in notifications.POST_TARGETS), section), "3.14 does not name every endpoint a button can call"
    assert not missing((f"`{c}`" for c in notifications.EMAIL_WHEN), section) and "`Email me`" not in section and "*Email me*" in section
    assert notifications.EMAILS_PER_HOUR == 12 and "At most 12 emails an hour per workspace" in section
    assert Ledger.NOTIFICATIONS_KEPT == 200 and "newest 200 per workspace" in section
    assert mailer.TIMEOUT_SECONDS == 8 and "at most 8 seconds" in section
    assert not missing((f"`{m}`" for m in mailer.SECURITY_MODES), section)
    smtp = [f"`RAGI_{n.upper()}`" for n in Settings.model_fields if n.startswith("smtp_")]
    assert len(smtp) == 6 and not missing(smtp, section), "3.14 does not name every mail setting"
    assert not missing(("`RAGI_APP_URL`", "`RAGI_ALERT_EMAIL_TO`", "Auto-Submitted"), section)
