create table if not exists public.connected_folders (
  workspace_id text not null,
  folder_id text not null,
  folder_name text not null,
  connected_by text,
  connected_at timestamptz not null default now(),
  last_scanned_at timestamptz,
  primary key (workspace_id, folder_id)
);

create table if not exists public.connected_files (
  workspace_id text not null,
  folder_id text not null,
  file_id text not null,
  file_name text not null,
  mime_type text not null,
  modified_time timestamptz,
  last_ingested_at timestamptz,
  primary key (workspace_id, folder_id, file_id),
  foreign key (workspace_id, folder_id)
    references public.connected_folders (workspace_id, folder_id)
    on delete cascade
);

create index if not exists connected_files_file_idx
  on public.connected_files (workspace_id, file_id);

create table if not exists public.drive_sync_state (
  workspace_id text primary key,
  page_token text not null,
  updated_at timestamptz not null default now()
);

alter table public.connected_folders enable row level security;
alter table public.connected_files enable row level security;
alter table public.drive_sync_state enable row level security;

comment on table public.connected_folders is
  'Drive roots explicitly connected by a Slack workspace.';
comment on table public.connected_files is
  'Folders and supported files discovered below each connected Drive root.';
comment on table public.drive_sync_state is
  'Account-wide Drive Changes API cursor per Slack workspace.';
