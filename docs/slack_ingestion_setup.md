# Slack Ingestion Setup

## Monitored channels

Channels to backfill/ingest are configured in the `monitored_channels` Supabase
table (see `supabase/migrations/20260703000100_monitored_channels.sql`), not
environment variables — this lets the channel list change at runtime without
a redeploy.

There is no admin UI yet. Add a channel via the Supabase SQL editor:

```sql
insert into public.monitored_channels (channel_id, channel_name, backfill_limit)
values ('C0123456789', 'general', 200);
```

Set `enabled = false` to stop ingesting a channel without deleting its row
(and its resume/reconciliation state).

## Channel types and Slack access

Slack ingestion supports explicitly monitored public channels and explicitly
monitored private channels. A channel being present in `monitored_channels`
does not grant Slack access by itself:

- Public channels must be visible to the installed app.
- Private channels must have the bot invited as a member before backfill or
  real-time events can work.

This ingestion setup does not ingest arbitrary private channels, group DMs, or
member DMs just because the app has broad scopes. It only processes channels
listed in `monitored_channels`.

## Required Slack scopes

Of the full bot manifest (`student-org-agent/manifest.json`, which also grants
scopes for other features like `/decide` and `/ask`), the scopes relevant to
Slack ingestion are:

- `channels:history` — read public channel history (and thread replies, which
  use the same scope; Slack has no separate scope for threads).
- `groups:history` — read private channel history for private channels the bot
  has been added to.

Event subscriptions relevant to Slack ingestion:

- `message.channels` — new and changed messages in public channels.
- `message.groups` — new and changed messages in private channels where the
  bot is present.

Run `common.slack_scopes.verify_slack_scopes(client, sample_channel_id=...)`
against a real monitored channel once after granting scopes (and after any
scope change) to confirm the bot token actually has access before relying on
backfill against real data. A `missing_scope` error there means the Slack app
needs the scope added and the app reinstalled to the workspace. For private
channels, also verify the bot has been invited to that channel; Slack will not
let the bot read private-channel history merely because the channel ID exists
in Supabase.

After changing OAuth scopes or event subscriptions in
`student-org-agent/manifest.json`, update or reinstall the Slack app in the
workspace before testing. Existing bot tokens do not automatically gain newly
declared scopes until Slack applies the app update.

## Known risks

- The canonical schema (`supabase/create_documents_table.sql`) declares
  `embedding vector(1024) NOT NULL`, matching `EMBED_DIMENSION` in
  `ingestion_api/embeddings.py` (Voyage `voyage-3.5-lite`). If that model or
  dimension ever changes, existing rows and the HNSW index will not be
  automatically migrated — mixing dimensions in one column will error or
  silently produce meaningless similarity scores. Re-embed all rows and
  update the column type if this happens. If your live Supabase instance
  predates `supabase/create_documents_table.sql`, confirm its `embedding`
  column actually has a declared dimension (`\d documents` in psql, or the
  Supabase table editor) rather than assuming it matches this script.
- Some live Supabase instances may have picked up a duplicate HNSW index
  on `documents.embedding` from manual dashboard changes (e.g. both
  `documents_embedding_idx` and `documents_embedding_hnsw_idx`) —
  redundant write-time cost. Check `pg_indexes` for the `documents` table
  before running `supabase/migrations/20260703000000_drop_duplicate_embedding_index.sql`.
