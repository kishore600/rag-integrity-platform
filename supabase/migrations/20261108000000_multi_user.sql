-- RAG Integrity v2: multi-user accounts and workspace-scoped ledger.
--
-- Adds: users, sessions, workspaces, workspace_settings (connection config; secrets are Fernet-encrypted by the
-- application under RAGI_SECRET_KEY, never by the database), api_keys, rate_limits.
-- Changes: every ledger table gains workspace_id (and composite keys), so one workspace can never see another's data.
--
-- The v1 ledger tables had no workspace column, so they are recreated. To make that safe the migration REFUSES to run
-- if any of them contains data: nothing is dropped unless they are empty.
-- Keep this file in sync with src/ragintegrity/ledger.py (tests/test_schema.py enforces column parity).

do $$
begin
  if exists (select 1 from ragi.issues)
     or exists (select 1 from ragi.documents)
     or exists (select 1 from ragi.audit_runs)
     or exists (select 1 from ragi.repair_plans)
     or exists (select 1 from ragi.query_log) then
    raise exception 'ragi ledger tables contain data; refusing to recreate them. Back up and migrate the rows into a workspace first.';
  end if;
end $$;

drop table if exists ragi.issue_events, ragi.issues, ragi.documents, ragi.audit_runs,
                     ragi.repair_plans, ragi.repair_events, ragi.query_log cascade;

-- ------------------------------------------------------------------------------------------------ accounts
create table if not exists ragi.workspaces (
  id         varchar(36) primary key,
  name       text        not null,
  owner_id   varchar(36) not null,
  created_at timestamptz not null
);

create table if not exists ragi.users (
  id            varchar(36) primary key,
  email         text        not null unique,
  password_hash text        not null,           -- scrypt, per-user salt
  workspace_id  varchar(36) not null,
  created_at    timestamptz not null,
  last_login_at timestamptz
);

create table if not exists ragi.sessions (
  token_hash   varchar(64) primary key,         -- sha256 of the cookie token; the token itself is never stored
  user_id      varchar(36) not null,
  workspace_id varchar(36) not null,
  created_at   timestamptz not null,
  expires_at   timestamptz not null,
  last_used_at timestamptz not null,
  ip           text,
  user_agent   text
);
create index if not exists ix_sessions_user    on ragi.sessions (user_id);
create index if not exists ix_sessions_expires on ragi.sessions (expires_at);

create table if not exists ragi.workspace_settings (
  workspace_id varchar(36) not null,
  kind         varchar(32) not null,            -- s3 | manifest | qdrant | pipeline | repair | alerts | policy
  config       jsonb       not null default '{}'::jsonb,   -- non-secret values
  secrets      text,                            -- Fernet token (encrypted JSON) of the secret values
  updated_at   timestamptz not null,
  last_test    jsonb,
  primary key (workspace_id, kind)
);

create table if not exists ragi.api_keys (
  id           varchar(36) primary key,
  workspace_id varchar(36) not null,
  name         text        not null,
  token_hash   varchar(64) not null unique,     -- sha256; the token is shown once at creation
  prefix       varchar(16) not null,
  created_at   timestamptz not null,
  last_used_at timestamptz,
  revoked_at   timestamptz
);
create index if not exists ix_api_keys_workspace on ragi.api_keys (workspace_id);

create table if not exists ragi.rate_limits (
  "key"        text        primary key,
  window_start timestamptz not null,
  "count"      integer     not null
);

-- ------------------------------------------------------------------------------------------------ the ledger (workspace-scoped)
create table if not exists ragi.audit_runs (
  id           varchar(36) primary key,
  workspace_id varchar(36) not null,
  kind         varchar(16) not null,            -- full | scoped | verify
  "trigger"    varchar(32) not null,
  scope        jsonb       not null default '{}'::jsonb,
  status       varchar(16) not null,            -- running | completed | failed
  started_at   timestamptz not null,
  finished_at  timestamptz,
  stats        jsonb       not null default '{}'::jsonb,
  error        text
);
create index if not exists ix_audit_runs_ws_started on ragi.audit_runs (workspace_id, started_at);
-- at most one running audit per workspace, enforced by the database (holds across serverless instances)
create unique index if not exists ux_audit_runs_one_running on ragi.audit_runs (workspace_id) where status = 'running';

create table if not exists ragi.issues (
  workspace_id    varchar(36) not null,
  id              varchar(32) not null,         -- deterministic: hash(type, tenant, document, collection)
  type            varchar(32) not null,
  severity        varchar(16) not null,
  status          varchar(16) not null,         -- open | resolved | ignored
  tenant_id       text        not null,
  document_id     text        not null,
  collection      text,
  title           text        not null,
  detail          text        not null,
  evidence        jsonb       not null default '{}'::jsonb,
  action          varchar(32) not null,
  first_seen_at   timestamptz not null,
  last_seen_at    timestamptz not null,
  first_run_id    varchar(36) not null,
  last_run_id     varchar(36) not null,
  resolved_at     timestamptz,
  resolved_run_id varchar(36),
  occurrences     integer     not null default 1,
  reopened_count  integer     not null default 0,
  ignored_reason  text,
  primary key (workspace_id, id)
);
create index if not exists ix_issues_status_sev on ragi.issues (workspace_id, status, severity);
create index if not exists ix_issues_doc        on ragi.issues (workspace_id, tenant_id, document_id);

create table if not exists ragi.issue_events (
  id           integer generated by default as identity primary key,
  workspace_id varchar(36) not null,
  issue_id     varchar(32) not null,
  run_id       varchar(36),
  ts           timestamptz not null,
  event        varchar(32) not null,
  details      jsonb       not null default '{}'::jsonb
);
create index if not exists ix_issue_events_issue on ragi.issue_events (workspace_id, issue_id);
create index if not exists ix_issue_events_ts    on ragi.issue_events (workspace_id, ts);

create table if not exists ragi.documents (
  workspace_id        varchar(36) not null,
  tenant_id           text        not null,
  document_id         text        not null,
  status              varchar(16) not null,     -- healthy | degraded | broken | pending | orphaned
  issue_count         integer     not null,
  worst_severity      varchar(16),
  issue_types         jsonb       not null default '[]'::jsonb,
  fingerprint         jsonb       not null default '{}'::jsonb,
  source_uri          text,
  source_hash         text,
  source_version      text,
  size_bytes          integer     not null default 0,
  expected_chunks     integer,
  indexed_chunks      integer     not null default 0,
  manifest_status     text,
  manifest_updated_at text,
  collections         jsonb       not null default '[]'::jsonb,
  source_present      integer     not null,
  manifest_present    integer     not null,
  index_present       integer     not null,
  last_verified_at    timestamptz not null,
  last_run_id         varchar(36) not null,
  primary key (workspace_id, tenant_id, document_id)
);
create index if not exists ix_documents_status on ragi.documents (workspace_id, status);

create table if not exists ragi.repair_plans (
  id           varchar(36) primary key,
  workspace_id varchar(36) not null,
  status       varchar(24) not null,
  created_at   timestamptz not null,
  updated_at   timestamptz not null,
  items        jsonb       not null default '[]'::jsonb,
  summary      jsonb       not null default '{}'::jsonb
);
create index if not exists ix_repair_plans_ws on ragi.repair_plans (workspace_id, created_at);

create table if not exists ragi.repair_events (
  id           integer generated by default as identity primary key,
  workspace_id varchar(36) not null,
  plan_id      varchar(36) not null,
  ts           timestamptz not null,
  event        varchar(32) not null,
  details      jsonb       not null default '{}'::jsonb
);
create index if not exists ix_repair_events_plan on ragi.repair_events (workspace_id, plan_id);

create table if not exists ragi.query_log (
  id                integer generated by default as identity primary key,
  workspace_id      varchar(36) not null,
  ts                timestamptz not null,
  tenant_id         text        not null,
  query_hash        varchar(64),                -- query text is hashed, never stored
  retrieved_doc_ids jsonb       not null default '[]'::jsonb
);
create index if not exists ix_query_log_ts on ragi.query_log (workspace_id, ts);

-- ------------------------------------------------------------------------------------------------ lock everything down
alter table ragi.workspaces         enable row level security;
alter table ragi.users              enable row level security;
alter table ragi.sessions           enable row level security;
alter table ragi.workspace_settings enable row level security;
alter table ragi.api_keys           enable row level security;
alter table ragi.rate_limits        enable row level security;
alter table ragi.audit_runs         enable row level security;
alter table ragi.issues             enable row level security;
alter table ragi.issue_events       enable row level security;
alter table ragi.documents          enable row level security;
alter table ragi.repair_plans       enable row level security;
alter table ragi.repair_events      enable row level security;
alter table ragi.query_log          enable row level security;

do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on schema ragi from %I', r);
      execute format('revoke all on all tables in schema ragi from %I', r);
      execute format('revoke all on all sequences in schema ragi from %I', r);
    end if;
  end loop;
end $$;
