"""Issue #62: Slack traffic is served over HTTP with real signature
verification, not Socket Mode. These tests boot the actual FastAPI app
(student-org-agent/app.py's http_app) and hit it with real HTTP requests --
not mocks -- to prove the signature check has teeth."""

import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from reconciliation.approval import ReconciliationApprovalPolicy
from slack_sdk.oauth.installation_store.models import Bot

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

    class FakeInstallationStore:
        def __init__(self, supabase):
            pass

        def find_bot(self, *, enterprise_id, team_id, is_enterprise_install=False):
            return Bot(
                app_id="A_TEST",
                enterprise_id=enterprise_id,
                team_id=team_id,
                bot_token="xoxb-test",
                bot_id="B_TEST",
                bot_user_id="U_BOT",
                bot_scopes="reactions:read,chat:write",
                installed_at=time.time(),
            )

    monkeypatch.setattr(
        "common.slack_installation_store.SupabaseInstallationStore",
        FakeInstallationStore,
    )
    monkeypatch.setattr(
        "slack_sdk.WebClient.auth_test",
        lambda self, token=None: {
            "ok": True,
            "url": "https://student-org-test.slack.com/",
            "team": "Student Org Test",
            "user": "student-org-agent",
            "team_id": "T123",
            "user_id": "U_BOT",
            "bot_id": "B_TEST",
        },
    )

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


def test_signed_reaction_event_confirms_matching_proposal(monkeypatch):
    module = _load_http_app(monkeypatch)
    lookups = []
    confirmations = []

    class FakeService:
        def find_by_slack_message(self, workspace_id, channel_id, message_ts):
            lookups.append((workspace_id, channel_id, message_ts))
            return SimpleNamespace(id="proposal-123")

        def confirm(self, **kwargs):
            confirmations.append(kwargs)

    monkeypatch.setattr(
        module,
        "build_reconciliation_proposal_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        module,
        "build_reconciliation_approval_policy",
        lambda workspace_id: ReconciliationApprovalPolicy(
            lead_user_ids=frozenset({"UAPPROVER"}),
            approval_reaction="white_check_mark",
        ),
    )
    payload = {
        "type": "event_callback",
        "team_id": "T123",
        "api_app_id": "A_TEST",
        "event_id": "Ev_TEST",
        "event_time": int(time.time()),
        "authorizations": [
            {
                "enterprise_id": None,
                "team_id": "T123",
                "user_id": "U_BOT",
                "is_bot": True,
                "is_enterprise_install": False,
            }
        ],
        "event": {
            "type": "reaction_added",
            "team": "T123",
            "user": "UAPPROVER",
            "reaction": "white_check_mark",
            "item": {
                "type": "message",
                "channel": "C_RECON",
                "ts": "1710000000.000100",
            },
            "event_ts": "1710000001.000100",
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    ts = str(int(time.time()))

    response = TestClient(module.http_app).post(
        "/slack/events",
        content=body,
        headers={
            "X-Slack-Signature": _sign(body, ts),
            "X-Slack-Request-Timestamp": ts,
            "Content-Type": "application/json",
        },
    )
    for _ in range(50):
        if confirmations:
            break
        time.sleep(0.01)

    assert response.status_code == 200
    assert lookups == [("T123", "C_RECON", "1710000000.000100")]
    assert confirmations == [
        {
            "workspace_id": "T123",
            "proposal_id": "proposal-123",
            "approving_user_id": "UAPPROVER",
        }
    ]


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
