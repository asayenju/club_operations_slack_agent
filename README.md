# Club Operations Ingestion API

A FastAPI service for future student organization document and spreadsheet
ingestion webhooks.

## Requirements

- Docker and Docker Compose

## Local setup

Create a local environment file:

```bash
cp .env.example .env
```

Fill in the required values in `.env`, then run:

```bash
docker compose up --build
```

The ingestion API will be available at `http://localhost:8000`.
The Slack bot will connect using Socket Mode when `SLACK_BOT_TOKEN` and
`SLACK_APP_TOKEN` are set in `.env`.

The active Slack bot is currently a simple Bolt test app that responds to
messages containing `hello`. It also supports `/decide` for recording club
decisions into the existing Supabase `documents` table. Decisions are stored as
sentence-aware chunks and embedded with Voyage before insertion. Slack Real-time
Search is implemented separately under `tools/` as a function/tool for a future
LLM integration.

Required `.env` values for `/decide`:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
VOYAGE_API_KEY=...
VOYAGE_EMBED_MODEL=...
VOYAGE_EMBED_DIMENSION=...
```

`SUPABASE_SERVICE_KEY` is also accepted as an alias for
`SUPABASE_SERVICE_ROLE_KEY`. If `VOYAGE_EMBED_MODEL` is not set, the bot uses
`voyage-3.5-lite`. If `VOYAGE_EMBED_DIMENSION` is not set, the bot requests
1024-dimensional embeddings.

Do not expose the Supabase service key or `VOYAGE_API_KEY` to clients. They are
server-side values used by the Slack bot container.

Check the ingestion API:

```bash
curl http://localhost:8000/health
```

Run only the Slack bot:

```bash
docker compose up --build slack-bot
```

Test the bot by inviting it to a public channel and sending:

```text
hello
```

You can also test it in Slack by sending `hello` in a channel or DM where the
bot is present.

Test `/decide` in Slack:

```text
/decide We approved $300 for tabling supplies.
```

On success, the bot posts a public confirmation that echoes the decision. Empty
input, duplicate content, embedding failures, and database failures are shown
only to the user who ran the command.

Internally, `/decide` chunks each decision before embedding. Each chunk is stored
as its own `documents` row with metadata that links it back to the full decision.
The current implementation uses local deterministic sentence packing rather
than LangChain, while keeping the chunking boundary isolated for a future
semantic chunker.

The Slack app manifest includes `/decide`, but the Slack app must be updated or
reinstalled for the slash command to appear in the workspace.

## Connected Drive folders

Docs and Sheets are discovered from explicitly connected Drive folders instead
of scanning every file visible to the club Google account.

Before using folder sync, run this migration in the Supabase SQL editor:

```text
supabase/migrations/20260623_drive_folder_sync.sql
```

Then update or reinstall the Slack app manifest and connect a folder:

```text
/connect-folder https://drive.google.com/drive/folders/<folder_id>
```

The initial scan recursively discovers Google Docs and Sheets in all
subfolders. Files are dispatched to the existing heading-based Docs ingestor or
the full-rewrite Sheets ingestor. Folder and file membership is stored in:

- `connected_folders`
- `connected_files`
- `drive_sync_state`

Disconnect a folder and remove source documents no longer referenced by another
connected root:

```text
/disconnect-folder https://drive.google.com/drive/folders/<folder_id>
```

The `drive-sync-worker` Docker Compose service polls the Drive Changes API. A
change identifies affected connected roots; those roots are rescanned, but only
files with a changed Drive `modifiedTime` are re-ingested.

Configure the interval in seconds:

```text
DRIVE_POLL_INTERVAL_SECONDS=300
```

Internal API equivalents are also available:

```bash
curl -X POST http://localhost:8000/drive/connect \
  -H "Content-Type: application/json" \
  -d '{"folder":"https://drive.google.com/drive/folders/<folder_id>","user_id":"U123"}'

curl -X POST http://localhost:8000/drive/sync

curl -X POST http://localhost:8000/drive/disconnect \
  -H "Content-Type: application/json" \
  -d '{"folder":"<folder_id>"}'
```

## Slack RTS tool

Slack Real-time Search lives in `tools/slack_search.py`. It exposes a
Claude-compatible tool metadata object and a Python function that a future LLM
router can call:

```python
from tools.slack_search import SLACK_RTS_SEARCH_TOOL, search_slack_public_context
```

The tool searches public Slack messages only. It requires a short-lived
`action_token` from a Slack interaction and must not log or expose that token.
See `tools/README.md` for the tool contract and edge cases.

## Google Docs ingestion

The ingestion service uses the backend-only Supabase secret key. Configure:

```text
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
VOYAGE_API_KEY=...
WORKSPACE_ID=...
GOOGLE_TOKEN_PATH=secrets/club_token.json
```

Never expose `SUPABASE_SERVICE_KEY`, `VOYAGE_API_KEY`, `client_secret.json`, or
the generated Google token to a browser or commit them to Git.

Create a Google OAuth Desktop client with the Docs, Drive, and Sheets APIs
enabled. Download it as `client_secret.json`, sign into the dedicated club
Google account, and run:

```bash
python -m tools.google_auth_bootstrap
```

This writes the reusable OAuth token to `secrets/club_token.json`.

The `documents` table must include `workspace_id`, `source`, `source_id`,
`chunk_key`, `content`, `content_hash`, `metadata`, `embedding`, and
`updated_at`, with a unique constraint on:

```text
(workspace_id, source, source_id, chunk_key)
```

Ingest one shared Google Doc using its ID:

```bash
python -m ingestion_api.ingest_docs <google_doc_id>
```

Or call the API:

```bash
curl -X POST http://localhost:8000/ingest/doc \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"google-doc-id"}'
```

Sections are split by Google Docs heading hierarchy. Oversized sections are
split rather than truncated, and unchanged chunks are not re-embedded.

## Google Sheets ingestion

Reads all tabs from Sheets found below connected Drive folders. When Drive marks
a Sheet as changed, the file is fully rewritten: all row embeddings are
prepared first, then the prior rows for that Sheet are replaced.

Ingest a single sheet by its ID (found in the sheet URL):

```bash
python -m ingestion_api.ingest_sheets <google_sheet_id>
```

Or call the API:

```bash
# Ingest one sheet
curl -X POST http://localhost:8000/ingest/sheet \
  -H "Content-Type: application/json" \
  -d '{"sheet_id":"google-sheet-id"}'

```

Each row becomes a chunk keyed by stable tab ID, content hash, and duplicate
occurrence. `row_index` is retained only as ordering metadata, so inserting or
reordering unrelated rows does not redefine their identities. Multi-tab Sheets
are supported.

The existing webhook can still trigger a direct rewrite:

```bash
curl -X POST http://localhost:8000/webhooks/spreadsheets \
  -H "Content-Type: application/json" \
  -d '{"sheet_id":"google-sheet-id"}'
```

## Ingestion setup

The ingestion API currently provides a placeholder endpoint for later document
sync logic:

```bash
curl -X POST http://localhost:8000/webhooks/documents \
  -H "Content-Type: application/json" \
  -d '{"document_id":"example"}'
```

This endpoint acknowledges the payload but does not write to Supabase yet.

## Development

Run tests locally after installing dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Or, using the existing virtualenv:

```bash
.venv/bin/python -m pytest -q
```

Validate Docker Compose:

```bash
docker compose config --quiet
```

Build the Slack bot image:

```bash
docker compose build slack-bot
```

Ingestion routes live in `ingestion_api/main.py`; shared settings live in
`common/config.py`.

## Reference documentation

- [Slack Bolt for Python](docs/slack-bolt-python-reference.md)
