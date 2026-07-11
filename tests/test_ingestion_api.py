from fastapi.testclient import TestClient
from types import SimpleNamespace

import pytest

from common import slack_ingestion
from common.slack_scopes import SlackScopeError
from ingestion_api import main
from ingestion_api.drive_sync import FolderSyncResult


def build_client(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "development")
    monkeypatch.setattr(main.settings, "ingestion_api_key", None)
    # _get_slack_client now resolves a per-workspace bot token from the
    # slack_installations table (issue #61) instead of a static env var --
    # stub it out so lifespan/backfill tests don't hit real Supabase.
    monkeypatch.setattr(main, "_get_slack_client", lambda: SimpleNamespace())
    return TestClient(main.app)


def test_health_returns_ok(monkeypatch):
    client = build_client(monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
        "service": "ingestion-api",
    }


def test_document_webhook_accepts_payload(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post("/webhooks/documents", json={"document_id": "doc-123"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "documents"}


def test_spreadsheet_webhook_accepts_payload(monkeypatch):
    client = build_client(monkeypatch)

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
    monkeypatch.setattr("ingestion_api.main.ingest_doc", lambda doc_id, workspace_id: expected)
    client = build_client(monkeypatch)

    response = client.post("/ingest/doc", json={"doc_id": "doc-123", "workspace_id": "T123"})

    assert response.status_code == 200
    assert response.json() == expected


def test_ingest_doc_endpoint_rejects_empty_doc_id(monkeypatch):
    client = build_client(monkeypatch)

    response = client.post("/ingest/doc", json={"doc_id": ""})

    assert response.status_code == 422



def test_ingest_doc_endpoint_rejects_whitespace_only_doc_id(monkeypatch):
    client = build_client(monkeypatch)

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
        lambda workspace_id: service,
    )
    client = build_client(monkeypatch)

    response = client.post(
        "/drive/connect",
        json={"folder": "root", "user_id": "U123", "workspace_id": "T123"},
    )

    assert response.status_code == 200
    assert response.json()["ingested"] == 2


def test_disconnect_drive_folder_endpoint(monkeypatch):
    service = SimpleNamespace(disconnect_folder=lambda folder: 2)
    monkeypatch.setattr(
        "ingestion_api.main.DriveSyncService.from_settings",
        lambda workspace_id: service,
    )
    client = build_client(monkeypatch)

    response = client.post("/drive/disconnect", json={"folder": "root", "workspace_id": "T123"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "disconnected",
        "purged_sources": 2,
    }


def test_sync_drive_endpoint_queues_poll(monkeypatch):
    calls = []
    service = SimpleNamespace(poll_changes=lambda: calls.append("polled"))
    monkeypatch.setattr(
        "ingestion_api.main.DriveSyncService.from_settings",
        lambda workspace_id: service,
    )
    client = build_client(monkeypatch)

    response = client.post("/drive/sync", json={"workspace_id": "T123"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "drive"}
    assert calls == ["polled"]


def test_ingestion_api_rejects_bad_api_key(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "production")
    monkeypatch.setattr(main.settings, "ingestion_api_key", "secret")
    client = TestClient(main.app)

    response = client.post("/webhooks/documents", json={"document_id": "doc-123"})

    assert response.status_code == 401


def test_ingestion_api_accepts_configured_api_key(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "production")
    monkeypatch.setattr(main.settings, "ingestion_api_key", "secret")
    client = TestClient(main.app)

    response = client.post(
        "/webhooks/documents",
        json={"document_id": "doc-123"},
        headers={"X-Ingestion-Api-Key": "secret"},
    )

    assert response.status_code == 202


def test_get_slack_client_resolves_bot_token_from_installation_store(monkeypatch):
    fake_bot = SimpleNamespace(bot_token="xoxb-resolved-token")
    fake_store = SimpleNamespace(find_bot=lambda **kwargs: fake_bot)
    monkeypatch.setattr(main, "SupabaseInstallationStore", lambda supabase: fake_store)
    monkeypatch.setattr(main, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(main.settings, "workspace_id", "T123")

    client = main._get_slack_client()

    assert client.token == "xoxb-resolved-token"


def test_get_slack_client_raises_when_workspace_not_installed(monkeypatch):
    fake_store = SimpleNamespace(find_bot=lambda **kwargs: None)
    monkeypatch.setattr(main, "SupabaseInstallationStore", lambda supabase: fake_store)
    monkeypatch.setattr(main, "_get_supabase", lambda: SimpleNamespace())
    monkeypatch.setattr(main.settings, "workspace_id", "T_NOT_INSTALLED")

    with pytest.raises(RuntimeError, match="No Slack installation found"):
        main._get_slack_client()


def test_slack_backfill_endpoint_accepts_request(monkeypatch):
    monkeypatch.setattr(main, "verify_slack_scopes", lambda *a, **k: None)
    monkeypatch.setattr(main, "list_monitored_channels", lambda supabase, workspace_id: [])
    monkeypatch.setattr(slack_ingestion, "list_monitored_channels", lambda supabase, workspace_id: [])
    client = build_client(monkeypatch)

    with client:
        response = client.post("/ingest/slack/backfill")

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "source": "slack_backfill"}


def test_lifespan_registers_daily_reconcile_job(monkeypatch):
    monkeypatch.setattr(main, "verify_slack_scopes", lambda *a, **k: None)
    monkeypatch.setattr(main, "list_monitored_channels", lambda supabase, workspace_id: [])
    client = build_client(monkeypatch)

    with client:
        jobs = main.scheduler.get_jobs()

    assert any(job.id == "slack_reconcile" for job in jobs)


def test_lifespan_fails_startup_when_slack_scopes_invalid(monkeypatch):
    def raise_scope_error(*args, **kwargs):
        raise SlackScopeError("missing a required scope")

    monkeypatch.setattr(main, "verify_slack_scopes", raise_scope_error)
    monkeypatch.setattr(main, "list_monitored_channels", lambda supabase, workspace_id: [])
    client = build_client(monkeypatch)

    with pytest.raises(SlackScopeError):
        with client:
            pass
