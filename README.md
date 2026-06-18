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
`SLACK_APP_TOKEN` are set in `.env`. The bot listens for public channel
mentions and uses Slack's Real-time Search API to return public Slack message
chunks with citations.

Check the ingestion API:

```bash
curl http://localhost:8000/health
```

Run only the Slack bot:

```bash
docker compose up --build slack-bot
```

Test the bot by inviting it to a public channel and mentioning it with a query:

```text
@student-org-agent what did we decide about tabling?
```

The Slack app manifest must include `app_mentions:read`, `search:read.public`,
`chat:write`, and the `app_mention` event subscription. Private-channel search
is intentionally deferred until a user OAuth flow is added.

## Ingestion setup

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

Ingestion routes live in `ingestion_api/main.py`; shared settings live in
`common/config.py`.
