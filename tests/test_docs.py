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
