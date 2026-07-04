from fastapi.testclient import TestClient

import ingestion_api.main as ingestion_main
from ingestion_api.main import app, scheduler


def test_health_returns_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
        "service": "ingestion-api",
    }


def test_document_webhook_accepts_payload():
    client = TestClient(app)

    response = client.post("/webhooks/documents", json={"document_id": "doc-123"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "documents"}


def test_spreadsheet_webhook_accepts_payload():
    client = TestClient(app)

    response = client.post("/webhooks/spreadsheets", json={"spreadsheet_id": "sheet-123"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "spreadsheets"}


def test_slack_backfill_endpoint_accepts_request(monkeypatch):
    monkeypatch.setattr(ingestion_main, "list_monitored_channels", lambda supabase: [])

    with TestClient(app) as client:
        response = client.post("/ingest/slack/backfill")

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "slack_backfill"}


def test_lifespan_registers_daily_reconcile_job():
    with TestClient(app):
        jobs = scheduler.get_jobs()

    assert any(job.id == "slack_reconcile" for job in jobs)
