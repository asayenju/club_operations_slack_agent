# Slack Ingestion Setup

## Monitored channels

Channels to backfill/ingest are configured in the `monitored_channels` Supabase
table (see `migrations/0001_slack_backfill_schema.sql`), not environment
variables — this lets the channel list change at runtime without a redeploy.

There is no admin UI yet. Add a channel via the Supabase SQL editor:

```sql
insert into public.monitored_channels (channel_id, channel_name, backfill_limit)
values ('C0123456789', 'general', 200);
```

Set `enabled = false` to stop ingesting a channel without deleting its row
(and its resume/reconciliation state).

## Required Slack scopes

- `channels:history` — read public channel history (and thread replies, which
  use the same scope; Slack has no separate scope for threads).
- `groups:history` — same, for private channels the bot has been invited to.

Run `common.slack_scopes.verify_slack_scopes(client, sample_channel_id=...)`
against a real monitored channel once after granting scopes (and after any
scope change) to confirm the bot token actually has access before relying on
backfill against real data. A `missing_scope` error there means the Slack app
needs the scope added and the app reinstalled to the workspace.

## Known risks

- `documents.embedding` has no declared vector dimension (`extensions.vector`,
  not `vector(1024)`). This works as long as the embedding model
  (`voyage-3.5-lite`, 1024-dim) never changes. If `_EMBED_MODEL` in
  `ingestion_api/embeddings.py` is ever changed to a model with a different
  output dimension, existing rows and the HNSW index will not be
  automatically migrated — mixing dimensions in one column will error or
  silently produce meaningless similarity scores. Re-embed all rows and
  consider migrating the column to a fixed `vector(n)` type if this happens.
- Two duplicate HNSW indexes currently exist on `documents.embedding`
  (`documents_embedding_idx`, `documents_embedding_hnsw_idx`) — redundant
  write-time cost. See `migrations/0002_drop_duplicate_embedding_index.sql`.
