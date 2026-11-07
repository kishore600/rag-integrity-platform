-- EXAMPLE customer-side processing manifest (the "source of truth" for what your pipeline believes).
--
-- This is NOT part of the ledger migration and is not applied automatically. Your ingestion workers
-- own and write these tables; RAG Integrity only ever reads them (inside READ ONLY transactions).
-- Use it as a template, or map your own table with RAGI_MANIFEST_TABLE / RAGI_MANIFEST_COLUMN_MAP.
--
-- Apply to a scratch database to try the live connectors:   psql "$DATABASE_URL" -f manifest_example.sql

create table if not exists public.rag_document_manifest (
  tenant_id               text        not null,
  document_id             text        not null,
  source_uri              text,
  source_version          text,                 -- S3 version id / etag the pipeline last processed
  source_hash             text,                 -- sha256 of the source content the pipeline last processed
  parsed_hash             text,                 -- sha256 of the extracted content
  parser_version          text,
  chunking_version        text,
  chunk_size              integer,
  chunk_overlap           integer,
  embedding_model         text,
  embedding_model_version text,
  embedding_dim           integer,
  preprocessing           text,
  expected_chunk_count    integer,
  indexed_chunk_count     integer,
  indexed_version         text,
  processing_status       text,                 -- pending | processing | success | failed ...
  last_verified_at        timestamptz,
  updated_at              timestamptz not null default now(),
  acl_hash                text,
  primary key (tenant_id, document_id)
);

-- Optional but recommended: stable chunk ids/hashes let the engine find *which* chunks are missing,
-- not just that the count is off.
create table if not exists public.rag_chunk_manifest (
  tenant_id   text not null,
  document_id text not null,
  chunk_id    text not null,
  chunk_index integer,
  chunk_hash  text,
  primary key (tenant_id, document_id, chunk_id)
);

-- Your pipeline tables should not be reachable through Supabase's REST API.
alter table public.rag_document_manifest enable row level security;
alter table public.rag_chunk_manifest    enable row level security;

-- A read-only role for RAG Integrity (recommended instead of the postgres superuser):
--   create role ragi_reader login password '<generate one>';
--   grant usage on schema public to ragi_reader;
--   grant select on public.rag_document_manifest, public.rag_chunk_manifest to ragi_reader;
--   create policy ragi_read_manifest on public.rag_document_manifest for select to ragi_reader using (true);
--   create policy ragi_read_chunks   on public.rag_chunk_manifest    for select to ragi_reader using (true);
