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

Check the ingestion API:

```bash
curl http://localhost:8000/health
```

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
