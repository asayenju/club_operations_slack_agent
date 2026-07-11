from types import SimpleNamespace

import pytest

from common import google_oauth_flow


class _FakeFlow:
    def __init__(self, credentials_refresh_token="refresh-token-abc"):
        self.redirect_uri = None
        self.authorization_url_calls = []
        self.fetch_token_calls = []
        self.credentials = SimpleNamespace(refresh_token=credentials_refresh_token)

    def authorization_url(self, **kwargs):
        self.authorization_url_calls.append(kwargs)
        return "https://accounts.google.com/o/oauth2/auth?fake=1", "fake-state"

    def fetch_token(self, **kwargs):
        self.fetch_token_calls.append(kwargs)


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.fly.dev")
    from common.config import get_ingestion_settings
    get_ingestion_settings.cache_clear()
    yield
    get_ingestion_settings.cache_clear()


def test_redirect_uri_combines_base_url_and_path(settings_env):
    assert google_oauth_flow.redirect_uri() == "https://example.fly.dev/google/oauth_redirect"


def test_build_authorization_url_passes_offline_access_and_state(settings_env, monkeypatch):
    fake_flow = _FakeFlow()
    monkeypatch.setattr(google_oauth_flow, "_build_flow", lambda: fake_flow)

    url = google_oauth_flow.build_authorization_url("T123|U456")

    assert url == "https://accounts.google.com/o/oauth2/auth?fake=1"
    assert fake_flow.authorization_url_calls == [{
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": "T123|U456",
    }]


def test_exchange_code_for_refresh_token_returns_token(settings_env, monkeypatch):
    fake_flow = _FakeFlow(credentials_refresh_token="refresh-secret")
    monkeypatch.setattr(google_oauth_flow, "_build_flow", lambda: fake_flow)

    token = google_oauth_flow.exchange_code_for_refresh_token("auth-code-123")

    assert token == "refresh-secret"
    assert fake_flow.fetch_token_calls == [{"code": "auth-code-123"}]


def test_exchange_code_raises_when_no_refresh_token_returned(settings_env, monkeypatch):
    fake_flow = _FakeFlow(credentials_refresh_token=None)
    monkeypatch.setattr(google_oauth_flow, "_build_flow", lambda: fake_flow)

    with pytest.raises(google_oauth_flow.MissingRefreshToken):
        google_oauth_flow.exchange_code_for_refresh_token("auth-code-123")
