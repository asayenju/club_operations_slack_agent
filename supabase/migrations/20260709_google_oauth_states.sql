-- Server-side, single-use, expiring state records for the Google OAuth
-- "Connect Google Drive" flow (issue #74 review, Aman). The `state` query
-- param round-tripped through Google's consent screen was previously a
-- plain "{team_id}|{user_id}" string the callback trusted verbatim -- since
-- Slack team IDs are not secret, anyone who knew a workspace's team_id
-- could forge that state and complete Google's OAuth flow themselves,
-- causing their own refresh token to overwrite that workspace's stored
-- Drive credentials. The actual random, unguessable value is the state
-- token itself (the primary key here); the callback looks up which
-- workspace/user it was issued for server-side instead of trusting the
-- client-supplied content.

create table if not exists public.google_oauth_states (
  state text primary key,
  workspace_id text not null,
  user_id text null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz null
);

create index if not exists google_oauth_states_expires_at_idx
  on public.google_oauth_states (expires_at);

alter table public.google_oauth_states enable row level security;

comment on table public.google_oauth_states is
  'Single-use, expiring state tokens for the /connect-folder Google OAuth flow. A row is consumed (consumed_at set) at most once; expired or already-consumed rows are rejected by the callback.';
