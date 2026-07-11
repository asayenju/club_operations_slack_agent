-- Add workspace scoping to monitored_channels so multiple Slack workspace
-- installs sharing one deployment/database can't collide or leak channel
-- config across tenants (issue #65). Every other tenant-scoped table
-- (documents, connected_folders, reconciliation_proposals) already keys on
-- workspace_id; monitored_channels was the one gap.

alter table public.monitored_channels
  add column if not exists workspace_id text;

-- Deliberately does NOT auto-backfill with a placeholder like
-- 'legacy-unscoped' -- every application query filters by the real
-- workspace_id (e.g. your Slack team ID), so a placeholder would make
-- every pre-existing channel invisible to the app: backfill/monitoring
-- would silently stop processing anything, with no error anywhere. Fail
-- loudly instead, before the NOT NULL/primary key changes below lock this
-- in, so this can't ship unnoticed the way a placeholder default did.
do $$
begin
  if exists (select 1 from public.monitored_channels where workspace_id is null) then
    raise exception
      'monitored_channels has rows with no workspace_id. Run this first '
      '(replace <YOUR_WORKSPACE_ID> with your real Slack team ID -- the '
      'same value as your WORKSPACE_ID env var), then re-run this migration: '
      'update public.monitored_channels set workspace_id = ''<YOUR_WORKSPACE_ID>'' where workspace_id is null;';
  end if;
end $$;

alter table public.monitored_channels
  alter column workspace_id set not null;

alter table public.monitored_channels
  drop constraint if exists monitored_channels_pkey;

alter table public.monitored_channels
  add primary key (workspace_id, channel_id);
