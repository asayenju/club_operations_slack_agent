-- A reconciliation proposal must be posted to a designated review channel.
-- The app is multi-tenant, so that channel belongs to workspace-scoped
-- configuration rather than one deployment-wide environment variable.

alter table public.workspace_admin_settings
  add column if not exists reconciliation_channel_id text null;

comment on column public.workspace_admin_settings.reconciliation_channel_id is
  'Slack channel that receives reconciliation proposals for this workspace.';
