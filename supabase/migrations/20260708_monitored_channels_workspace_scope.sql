-- Add workspace scoping to monitored_channels so multiple Slack workspace
-- installs sharing one deployment/database can't collide or leak channel
-- config across tenants (issue #65). Every other tenant-scoped table
-- (documents, connected_folders, reconciliation_proposals) already keys on
-- workspace_id; monitored_channels was the one gap.

alter table public.monitored_channels
  add column if not exists workspace_id text;

-- Backfill any pre-existing single-tenant rows with a sentinel so the
-- NOT NULL + primary key changes below never fail against real data.
-- Replace 'legacy-unscoped' with the real workspace_id by hand if you have
-- existing rows from before multi-tenancy.
update public.monitored_channels
set workspace_id = 'legacy-unscoped'
where workspace_id is null;

alter table public.monitored_channels
  alter column workspace_id set not null;

alter table public.monitored_channels
  drop constraint if exists monitored_channels_pkey;

alter table public.monitored_channels
  add primary key (workspace_id, channel_id);
