-- Monitored Slack channel configuration + per-channel backfill/reconciliation
-- resume state. Run manually via the Supabase SQL editor (this repo has no
-- migration tooling wired up yet -- this is the first tracked migration).

create table if not exists public.monitored_channels (
  channel_id text primary key,
  channel_name text not null,
  enabled boolean not null default true,
  backfill_limit integer not null default 200,
  oldest_ts_backfilled text null,
  initial_backfill_complete boolean not null default false,
  last_reconciled_at timestamptz null,
  last_reconciled_ts text null,
  last_backfill_error text null,
  last_backfill_error_at timestamptz null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
