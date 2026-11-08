-- The dashboard compares the source version of each document with the version the index actually holds.
-- Additive and safe to re-run: existing rows simply have no value until the next audit fills it in.
-- Keep in sync with src/ragintegrity/ledger.py (tests/test_schema.py enforces column parity).

alter table ragi.documents add column if not exists indexed_version text;
