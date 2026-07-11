-- Per-workspace admin configuration (issue #67). Replaces the static
-- DRIVE_SYNC_ADMIN_USER_IDS/RECONCILIATION_APPROVAL_USER_IDS env vars, which
-- were a single deployment-wide list -- meaningless once more than one
-- workspace can install this app. A newly installed workspace gets a
-- sensible default (the Slack user who completed the install) seeded via
-- the OAuth success callback, not a redeploy or env var edit.

create table if not exists public.workspace_admin_settings (
  workspace_id text primary key,
  drive_sync_admin_user_ids text[] not null default '{}',
  reconciliation_approval_user_ids text[] not null default '{}',
  reconciliation_approval_reaction text not null default 'white_check_mark',
  updated_at timestamptz not null default now()
);

alter table public.workspace_admin_settings enable row level security;

comment on table public.workspace_admin_settings is
  'Per-workspace admin lists for /connect-folder and reconciliation approval reactions, seeded with the installer as default admin on install.';
