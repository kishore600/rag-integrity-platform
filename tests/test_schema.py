"""The hand-written Supabase migrations must stay in lock-step with the SQLAlchemy ledger models."""

from __future__ import annotations

import re
from pathlib import Path

from ragintegrity.ledger import build_tables

MIGRATIONS = sorted((Path(__file__).parent.parent / "supabase" / "migrations").glob("*.sql"))


def parse_migrations() -> dict[str, list[str]]:
    """Replay every migration in order: `create table` defines a table, `drop table` removes it, `add column` appends."""
    tables: dict[str, list[str]] = {}
    for path in MIGRATIONS:
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        # statements in file order
        pattern = (r"drop table if exists ([^;]+?)\s+cascade;"
                   r"|create table if not exists ragi\.(\w+) \((.*?)\n\);"
                   r"|alter table ragi\.(\w+) add column if not exists (\w+)")
        for m in re.finditer(pattern, sql, re.S):
            if m.group(1):
                for name in re.findall(r"ragi\.(\w+)", m.group(1)):
                    tables.pop(name, None)
                continue
            if m.group(4):
                if m.group(5) not in tables[m.group(4)]:
                    tables[m.group(4)].append(m.group(5))
                continue
            cols = []
            for line in m.group(3).splitlines():
                line = line.strip()
                if not line or line.startswith(("primary key", "unique", "constraint")):
                    continue
                cols.append(line.split()[0].strip('",'))
            tables[m.group(2)] = cols
    return tables


def test_migrations_match_models():
    sql_tables = parse_migrations()
    _, model_tables = build_tables(None)
    assert set(sql_tables) == set(model_tables), set(sql_tables) ^ set(model_tables)
    for name, table in model_tables.items():
        assert sql_tables[name] == [c.name for c in table.c], f"column drift in ragi.{name}"


def test_every_table_has_rls_enabled():
    sql = "\n".join(p.read_text(encoding="utf-8") for p in MIGRATIONS)
    for name in parse_migrations():
        assert f"alter table ragi.{name}" in sql, f"RLS not enabled on ragi.{name}"
    assert "enable row level security" in sql


def test_the_destructive_migration_refuses_to_run_on_data():
    sql = (Path(__file__).parent.parent / "supabase" / "migrations" / "20261108000000_multi_user.sql").read_text(encoding="utf-8")
    assert sql.index("raise exception") < sql.index("drop table"), "the data guard must come before any drop"


def test_one_running_audit_per_workspace_is_enforced_in_the_schema():
    sql = "\n".join(p.read_text(encoding="utf-8") for p in MIGRATIONS)
    assert "ux_audit_runs_one_running" in sql and "where status = 'running'" in sql
