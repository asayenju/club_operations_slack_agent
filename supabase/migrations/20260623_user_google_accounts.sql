create table if not exists public.user_google_accounts (
  workspace_id text not null,
  slack_user_id text not null,
  google_email text not null,
  display_name text,
  source text not null default 'register',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, slack_user_id),
  unique (workspace_id, google_email),
  constraint user_google_accounts_email_normalized
    check (google_email = lower(trim(google_email))),
  constraint user_google_accounts_source
    check (source in ('register', 'roster'))
);

alter table public.user_google_accounts enable row level security;

comment on table public.user_google_accounts is
  'Workspace-scoped Slack-to-Google account mapping for Calendar operations.';
comment on column public.user_google_accounts.source is
  'Explicit register mappings take precedence over future roster imports.';
