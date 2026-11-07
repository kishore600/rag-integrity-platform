# Using Supabase

Supabase plays two optional roles. Neither needs anything installed in the customer's data path.

1. **Control-plane ledger** (this app writes): issues, audit history, per-document state, repair plans.
2. **The customer's processing manifest** (this app only reads): your pipeline's own Postgres table.

You can use one Supabase project for both, but a separate project for the ledger is cleaner.

## 1. Ledger on Supabase

1. Create a project (Dashboard -> New project) and note the database password.
2. Copy a connection string: *Project Settings -> Database -> Connection string*. Prefer the **Session pooler** (port 5432)
   or the direct connection; the transaction pooler (6543) also works (prepared statements are disabled for it).
   Append `?sslmode=require`.
3. Either let the app create the schema, or apply the migration yourself:

   ```bash
   supabase link --project-ref <ref>
   supabase db push            # applies supabase/migrations/20261107000000_ragi_ledger.sql
   ```

4. Configure and verify:

   ```bash
   export RAGI_DATABASE_URL='postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require'
   ragi init-db                # creates tables if missing (idempotent) and checks connectivity
   ```

What the migration does: creates a private `ragi` schema (not exposed by Supabase's REST API), seven tables,
indexes, **enables row level security with no policies**, and revokes `anon` / `authenticated`. The app connects with a
direct Postgres role, so RLS does not get in its way. `tests/test_schema.py` keeps the SQL and the ORM models in
lock-step, and `tests/test_postgres_integration.py` applies it to a real Postgres on every CI run.

No document contents are stored; only ids, hashes, versions, counts and evidence. Query text is hashed.

## 2. Reading your pipeline's manifest from Supabase

Create a **read-only** role rather than using the `postgres` superuser (template in
[`supabase/examples/manifest_example.sql`](../supabase/examples/manifest_example.sql)):

```sql
create role ragi_reader login password '<generate one>';
grant usage on schema public to ragi_reader;
grant select on public.rag_document_manifest, public.rag_chunk_manifest to ragi_reader;
create policy ragi_read_manifest on public.rag_document_manifest for select to ragi_reader using (true);
create policy ragi_read_chunks   on public.rag_chunk_manifest    for select to ragi_reader using (true);
```

Then set `RAGI_MANIFEST_DATABASE_URL` to that role's connection string. The connector also opens every transaction
`READ ONLY`, so even a misconfigured role cannot write. Using different table or column names? See
[configuration.md](configuration.md#processing-manifest-postgresql--supabase).

## Notes

* Do **not** run `scripts/seed_live.py` against Supabase: it drops and recreates the demo manifest tables (it refuses
  `supabase.co`/`supabase.com` hosts for that reason).
* Rotating the database password only requires updating the environment variable.
* Backups/retention of the ledger are Supabase's; the audit history is append-only by design.
