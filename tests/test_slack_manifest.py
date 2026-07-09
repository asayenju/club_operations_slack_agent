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
