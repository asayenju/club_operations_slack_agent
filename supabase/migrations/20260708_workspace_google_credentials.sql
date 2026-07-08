-- Per-workspace Google OAuth credentials (issue #66). Replaces the single
-- shared secrets/club_token.json file -- each installing Slack workspace
-- connects its own Google account via its own OAuth consent, so Docs/Sheets/
-- Drive access is fully isolated per workspace, not shared.

create table if not exists public.workspace_google_credentials (
  workspace_id text primary key,
  refresh_token_encrypted text not null,
  google_account_email text null,
  connected_by_user_id text null,
  scopes text not null,
  connected_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.workspace_google_credentials enable row level security;

comment on table public.workspace_google_credentials is
  'One row per Slack workspace that has connected its own Google account. refresh_token is Fernet-encrypted at the application layer (common/crypto.py) before being written here -- never stored plaintext.';
