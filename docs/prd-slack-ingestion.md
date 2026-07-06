# PRD: Slack Message Ingestion for RAG

## Problem
The student-org agent can only answer questions using Slack's real-time search API, which is limited to recent/keyword-matchable messages. There's no durable, searchable store of channel history, so the agent can't ground answers in older context or do semantic (vector) retrieval.

## Goal
Continuously ingest messages from a configured set of Slack channels into a vector store (Supabase + pgvector, embedded via Voyage) so they can be retrieved for RAG, while keeping the store in sync with edits and deletions.

## Non-goals
- Ingesting DMs or private channels not explicitly monitored.
- Full historical backfill beyond a bounded `backfill_limit` per channel.
- Building the retrieval/RAG query path itself (separate work).

## Design

**Channel config**: `monitored_channels` table in Supabase (`channel_id`, `channel_name`, `enabled`, `backfill_limit`) controls which channels are ingested.

**Normalization** (`common/slack_ingestion.py`): Raw Slack events are filtered (bot messages, system subtypes like joins/leaves/topic changes) and normalized into a `SlackMessage` shape before storage.

**Persistence**: Each message is embedded (Voyage) and upserted into a chunks table keyed by `{channel_id}:{ts}`, content-hashed to detect duplicate/unchanged content. Edits re-embed and upsert; deletions remove the chunk by diffing against `existing_keys`.

**Ingestion paths**:
1. **Real-time** — `student-org-agent/app.py` listens to Slack's `message` event (new, `message_changed`, `message_deleted` subtypes) and ingests/updates/deletes the corresponding chunk immediately, but only for channels in the monitored set.
2. **Backfill** — `backfill_channel()` pulls up to `limit` recent messages via `conversations_history`, skips ones already stored, embeds and upserts the rest. Triggered two ways:
   - Automatically in a background thread on agent startup.
   - On demand via `POST /ingest/slack/backfill` on the ingestion API, which runs it as a FastAPI background task across all monitored channels.

**Config**: New required settings (`supabase_url`, `supabase_service_key`, `voyage_api_key`, `workspace_id`) added to both `SlackSettings` and `IngestionSettings`, validated lazily via `.required_*` properties that raise if unset.

## Testing
`tests/test_slack_ingestion.py` covers normalization filtering, content hashing/idempotency, and backfill skip-existing behavior.

## Rollout
- Requires `monitored_channels` table to exist in Supabase before deploy.
- Secrets (`SUPABASE_SERVICE_KEY`, `VOYAGE_API_KEY`, etc.) must be set in the environment — none are committed to the repo.
