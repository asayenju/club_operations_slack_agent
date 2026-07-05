create table if not exists public.reconciliation_proposals (
    id uuid primary key,
    workspace_id text not null,
    status text not null check (
        status in ('pending', 'confirmed', 'expired', 'rejected', 'superseded')
    ),
    source_evidence jsonb not null default '[]'::jsonb,
    proposed_action jsonb not null default '{}'::jsonb,
    slack_channel_id text,
    slack_message_ts text,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    confirmed_by_user_id text,
    confirmed_at timestamptz,
    audit_log jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);

create unique index if not exists reconciliation_proposals_message_ref_idx
    on public.reconciliation_proposals (workspace_id, slack_channel_id, slack_message_ts)
    where slack_channel_id is not null
      and slack_message_ts is not null;

create index if not exists reconciliation_proposals_pending_idx
    on public.reconciliation_proposals (workspace_id, expires_at)
    where status = 'pending';

alter table public.reconciliation_proposals enable row level security;
