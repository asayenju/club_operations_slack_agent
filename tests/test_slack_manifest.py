import json
from pathlib import Path


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "student-org-agent" / "manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_includes_public_and_private_channel_history_scopes():
    bot_scopes = set(_manifest()["oauth_config"]["scopes"]["bot"])

    assert "channels:history" in bot_scopes
    assert "groups:history" in bot_scopes


def test_manifest_subscribes_to_public_and_private_channel_message_events():
    bot_events = set(_manifest()["settings"]["event_subscriptions"]["bot_events"])

    assert "message.channels" in bot_events
    assert "message.groups" in bot_events
