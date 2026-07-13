"""Issue #62: Slack traffic is served over HTTP with real signature
verification, not Socket Mode. These tests boot the actual FastAPI app
(student-org-agent/app.py's http_app) and hit it with real HTTP requests --
not mocks -- to prove the signature check has teeth."""

import hashlib
import hmac
import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
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
        slack_bot_token=None,
        slack_app_token=None,
    ))

    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app_http", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sign(body: bytes, ts: str) -> str:
    basestring = f"v0:{ts}:".encode() + body
    digest = hmac.new(SIGNING_SECRET.encode(), basestring, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_slack_events_rejects_forged_signature(monkeypatch):
    module = _load_http_app(monkeypatch)
    client = TestClient(module.http_app)
    body = b'{"type":"url_verification","challenge":"abc123"}'
    ts = str(int(time.time()))

    response = client.post(
        "/slack/events",
        content=body,
        headers={
            "X-Slack-Signature": "v0=" + "0" * 64,
            "X-Slack-Request-Timestamp": ts,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401


def test_slack_events_rejects_stale_timestamp(monkeypatch):
    module = _load_http_app(monkeypatch)
    client = TestClient(module.http_app)
    body = b'{"type":"url_verification","challenge":"abc123"}'
    stale_ts = str(int(time.time()) - 60 * 60)  # 1 hour old

    response = client.post(
        "/slack/events",
        content=body,
        headers={
            "X-Slack-Signature": _sign(body, stale_ts),
            "X-Slack-Request-Timestamp": stale_ts,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401


def test_slack_events_accepts_correctly_signed_request(monkeypatch):
    module = _load_http_app(monkeypatch)
    client = TestClient(module.http_app)
    body = b'{"type":"url_verification","challenge":"abc123"}'
    ts = str(int(time.time()))

    response = client.post(
        "/slack/events",
        content=body,
        headers={
            "X-Slack-Signature": _sign(body, ts),
            "X-Slack-Request-Timestamp": ts,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


def test_health_endpoint_does_not_require_signature(monkeypatch):
    module = _load_http_app(monkeypatch)
    client = TestClient(module.http_app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "slack-bot"}


def test_install_route_is_registered(monkeypatch):
    module = _load_http_app(monkeypatch)

    paths = {getattr(r, "path", None) for r in module.http_app.routes}

    assert "/slack/install" in paths
    assert "/slack/oauth_redirect" in paths
    assert "/slack/events" in paths
