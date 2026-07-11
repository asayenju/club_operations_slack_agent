"""Issue #71 review (Hailee): socket_mode_enabled was flipped to false, but
every features.slash_commands[] entry was missing its own `url` -- distinct
from event_subscriptions.request_url and interactivity.request_url per
Slack's manifest schema. Without it, slash commands silently no-op in HTTP
mode. This pins that fix so it can't regress unnoticed the same way again.
"""

import json
from pathlib import Path


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "student-org-agent" / "manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def test_socket_mode_is_disabled():
    manifest = _manifest()
    assert manifest["settings"]["socket_mode_enabled"] is False


def test_every_slash_command_has_its_own_request_url():
    manifest = _manifest()
    commands = manifest["features"]["slash_commands"]
    assert len(commands) > 0
    for command in commands:
        assert command.get("url"), f"{command['command']} is missing its own request url"


def test_event_subscriptions_and_interactivity_have_request_urls():
    manifest = _manifest()
    settings = manifest["settings"]
    assert settings["event_subscriptions"]["request_url"]
    assert settings["interactivity"]["request_url"]


def test_oauth_redirect_url_is_configured():
    manifest = _manifest()
    assert manifest["oauth_config"]["redirect_urls"]


def test_manifest_includes_public_and_private_channel_history_scopes():
    bot_scopes = set(_manifest()["oauth_config"]["scopes"]["bot"])

    assert "channels:history" in bot_scopes
    assert "groups:history" in bot_scopes


def test_manifest_subscribes_to_public_and_private_channel_message_events():
    bot_events = set(_manifest()["settings"]["event_subscriptions"]["bot_events"])

    assert "message.channels" in bot_events
    assert "message.groups" in bot_events


def test_oauth_install_flow_requests_exactly_the_manifests_bot_scopes(monkeypatch):
    """Review feedback (Aman, PR #70): the OAuth install flow's BOT_SCOPES
    list is separate Python code, not derived from manifest.json -- when the
    manifest's declared scopes changed (private channel support, #58) the
    runtime OAuth scopes silently didn't, so new installs wouldn't actually
    request what the manifest advertises. Pin the two to match exactly so
    that class of drift fails a test instead of shipping silently."""
    import importlib.util

    monkeypatch.setenv("SLACK_CLIENT_ID", "manifest-check-client-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "manifest-check-client-secret")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "manifest-check-signing-secret")

    module_path = Path(__file__).resolve().parents[1] / "student-org-agent" / "app.py"
    spec = importlib.util.spec_from_file_location("student_org_agent_app_manifest_check", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    manifest_scopes = set(_manifest()["oauth_config"]["scopes"]["bot"])
    assert set(module.BOT_SCOPES) == manifest_scopes
