"""The hand-written Supabase migration must stay in lock-step with the SQLAlchemy ledger models."""

from __future__ import annotations

import re
from pathlib import Path

from ragintegrity.ledger import build_tables

MIGRATION = Path(__file__).parent.parent / "supabase" / "migrations" / "20261107000000_ragi_ledger.sql"


def parse_migration() -> dict[str, list[str]]:
    sql = MIGRATION.read_text(encoding="utf-8")
    tables: dict[str, list[str]] = {}
    for m in re.finditer(r"create table if not exists ragi\.(\w+) \((.*?)\n\);", sql, re.S):
        cols = []
        for line in m.group(2).splitlines():
            line = line.split("--")[0].strip()
            if not line or line.startswith("primary key"):
                continue
            cols.append(line.split()[0].strip('"'))
        tables[m.group(1)] = cols
    return tables


def test_migration_columns_match_models():
    sql_tables = parse_migration()
    _, model_tables = build_tables(None)
    assert set(sql_tables) == set(model_tables)
    for name, table in model_tables.items():
        assert sql_tables[name] == [c.name for c in table.c], f"column drift in ragi.{name}"


def test_every_table_has_rls_enabled():
    sql = MIGRATION.read_text(encoding="utf-8")
    for name in parse_migration():
        assert f"alter table ragi.{name}" in sql and "enable row level security" in sql
