-- Backs the Bolt InstallationStore for multi-workspace OAuth installs
-- (issue #61). One row per Slack team (or per enterprise install). Bot
-- tokens are stored encrypted (see common/crypto.py) -- never plaintext.

create table if not exists public.slack_installations (
  team_id text not null,
  enterprise_id text null,
  is_enterprise_install boolean not null default false,
  bot_token_encrypted text not null,
  bot_id text null,
  bot_user_id text null,
  bot_scopes text null,
  app_id text null,
  installed_by_user_id text null,
  installed_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  raw_installation jsonb not null,
  primary key (team_id)
);

create index if not exists slack_installations_enterprise_idx
  on public.slack_installations (enterprise_id);

alter table public.slack_installations enable row level security;

comment on table public.slack_installations is
  'One row per Slack workspace install, backing the Bolt InstallationStore. Bot tokens are Fernet-encrypted at the application layer before being written here.';
