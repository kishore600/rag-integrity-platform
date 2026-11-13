-- In-app notifications: what an audit found and what to do about it, one list per workspace.
-- Additive and safe to re-run (create ... if not exists). The app also creates this table itself on start-up.
-- Keep in sync with src/ragintegrity/ledger.py (tests/test_schema.py enforces column parity).

create table if not exists ragi.notifications (
  id           varchar(36) primary key,
  workspace_id varchar(36) not null,
  created_at   timestamptz not null,
  kind         varchar(24) not null,          -- audit_completed | audit_partial | audit_failed
  tone         varchar(12) not null,          -- success | info | warning | critical
  title        text        not null,
  body         text        not null,
  details      jsonb       not null default '[]'::jsonb,
  run_id       varchar(36),
  actions      jsonb       not null default '[]'::jsonb,
  read_at      timestamptz,
  done_action  varchar(32),
  emailed_at   timestamptz
);
create index if not exists ix_notifications_ws_created on ragi.notifications (workspace_id, created_at);

alter table ragi.notifications enable row level security;

do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on all tables in schema ragi from %I', r);
    end if;
  end loop;
end $$;
