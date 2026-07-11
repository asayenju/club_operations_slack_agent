"""Issue #66: /google/oauth_redirect actually saves per-workspace Google
credentials. Boots the real FastAPI app and hits it with real HTTP
requests, mocking only the true external boundaries (Google's token
exchange, Supabase)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

SIGNING_SECRET = "test-signing-secret"


def _load_http_app(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "client-id-test")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SIGNING_SECRET)

    monkeypatch.setattr("common.config.get_slack_settings", lambda: SimpleNamespace(
        supabase_url="http://fake",
        supabase_service_role_key="fake.fake.fake",
        slack_signing_secret=SIGNING_SECRET,
        slack_client_id="client-id-test",
        slack_client_secret="client-secret-test",
        slack_port=3000,
    ))

    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app_google_oauth", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_oauth_redirect_saves_credentials_for_the_workspace_in_state(monkeypatch):
    module = _load_http_app(monkeypatch)
    monkeypatch.setattr(module, "exchange_code_for_refresh_token", lambda code: "refresh-secret")
    saved = []
    monkeypatch.setattr(
        module,
        "WorkspaceGoogleCredentialsStore",
        lambda supabase: SimpleNamespace(
            save=lambda workspace_id, token, scopes, connected_by_user_id=None: saved.append(
                (workspace_id, token, connected_by_user_id)
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "GoogleOAuthStateStore",
        lambda supabase: SimpleNamespace(consume=lambda state: ("T123", "U456")),
    )
    monkeypatch.setattr(module, "_get_supabase", lambda: SimpleNamespace())
    client = TestClient(module.http_app)

    response = client.get("/google/oauth_redirect", params={"code": "auth-code", "state": "opaque-test-token"})

    assert response.status_code == 200
    assert saved == [("T123", "refresh-secret", "U456")]


def test_oauth_redirect_rejects_missing_code(monkeypatch):
    module = _load_http_app(monkeypatch)
    client = TestClient(module.http_app)

    response = client.get("/google/oauth_redirect", params={"state": "T123|U456"})

    assert response.status_code == 400


def test_oauth_redirect_surfaces_google_error_without_saving(monkeypatch):
    module = _load_http_app(monkeypatch)
    client = TestClient(module.http_app)

    response = client.get("/google/oauth_redirect", params={"error": "access_denied", "state": "T123|U456"})

    assert response.status_code == 400
    assert "access_denied" in response.text


def test_oauth_redirect_returns_502_when_token_exchange_fails(monkeypatch):
    module = _load_http_app(monkeypatch)

    def _raise(code):
        raise RuntimeError("token exchange failed")

    monkeypatch.setattr(module, "exchange_code_for_refresh_token", _raise)
    monkeypatch.setattr(
        module,
        "GoogleOAuthStateStore",
        lambda supabase: SimpleNamespace(consume=lambda state: ("T123", "U456")),
    )
    monkeypatch.setattr(module, "_get_supabase", lambda: SimpleNamespace())
    client = TestClient(module.http_app)

    response = client.get("/google/oauth_redirect", params={"code": "auth-code", "state": "opaque-test-token"})

    assert response.status_code == 502
