from fastapi.testclient import TestClient
from types import SimpleNamespace

from ingestion_api.drive_sync import FolderSyncResult
from ingestion_api.main import app


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


def test_ingest_doc_endpoint_runs_ingestion(monkeypatch):
    expected = {
        "doc_id": "doc-123",
        "title": "Meeting Notes",
        "inserted_or_changed": 2,
        "unchanged": 1,
        "deleted": 0,
        "total": 3,
    }
    monkeypatch.setattr("ingestion_api.main.ingest_doc", lambda doc_id: expected)
    client = TestClient(app)

    response = client.post("/ingest/doc", json={"doc_id": "doc-123"})

    assert response.status_code == 200
    assert response.json() == expected


def test_ingest_doc_endpoint_rejects_empty_doc_id():
    client = TestClient(app)

    response = client.post("/ingest/doc", json={"doc_id": ""})

    assert response.status_code == 422



def test_ingest_doc_endpoint_rejects_whitespace_only_doc_id():
    client = TestClient(app)

    response = client.post("/ingest/doc", json={"doc_id": "   "})

    assert response.status_code == 422


def test_connect_drive_folder_endpoint(monkeypatch):
    service = SimpleNamespace(
        connect_folder=lambda folder, connected_by: FolderSyncResult(
            folder_id="root",
            folder_name="Club Files",
            discovered=3,
            ingested=2,
            unchanged=1,
            removed=0,
        )
    )
    monkeypatch.setattr(
        "ingestion_api.main.DriveSyncService.from_settings",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post(
        "/drive/connect",
        json={"folder": "root", "user_id": "U123"},
    )

    assert response.status_code == 200
    assert response.json()["ingested"] == 2


def test_sync_drive_endpoint_queues_poll(monkeypatch):
    calls = []
    service = SimpleNamespace(poll_changes=lambda: calls.append("polled"))
    monkeypatch.setattr(
        "ingestion_api.main.DriveSyncService.from_settings",
        lambda: service,
    )
    client = TestClient(app)

    response = client.post("/drive/sync")

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "drive"}
    assert calls == ["polled"]
