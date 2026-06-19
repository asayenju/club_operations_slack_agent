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

Fill in `SUPABASE_URL` and `SUPABASE_ANON_KEY`, then run:

```bash
docker compose up --build
```

The ingestion API will be available at `http://localhost:8000`.
The Slack bot will connect using Socket Mode when `SLACK_BOT_TOKEN` and
`SLACK_APP_TOKEN` are set in `.env`.

The active Slack bot is currently a simple Bolt test app that responds to
messages containing `hello`. Slack Real-time Search is implemented separately
under `tools/` as a function/tool for a future LLM integration.

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

## Placeholder ingestion webhooks

The ingestion API currently provides placeholder endpoints for later document
and spreadsheet sync logic:

```bash
curl -X POST http://localhost:8000/webhooks/documents \
  -H "Content-Type: application/json" \
  -d '{"document_id":"example"}'

curl -X POST http://localhost:8000/webhooks/spreadsheets \
  -H "Content-Type: application/json" \
  -d '{"spreadsheet_id":"example"}'
```

These endpoints acknowledge payloads but do not write to Supabase yet.

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
