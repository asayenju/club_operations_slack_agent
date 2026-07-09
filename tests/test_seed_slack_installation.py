from types import SimpleNamespace

import pytest
from slack_sdk.errors import SlackApiError

from tools import seed_slack_installation


class _FakeAuthTestResponse(dict):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}


class _FakeWebClient:
    def __init__(self, token, response=None, error=None):
        self.token = token
        self._response = response
        self._error = error

    def auth_test(self):
        if self._error:
            raise SlackApiError("auth_test failed", SimpleNamespace(get=lambda k, d=None: self._error))
        return self._response


def test_main_exits_when_no_bot_token(monkeypatch, capsys):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        seed_slack_installation.main()

    assert "Set SLACK_BOT_TOKEN" in capsys.readouterr().out


def test_main_exits_when_auth_test_fails(monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-old-token")
    monkeypatch.setattr(
        seed_slack_installation, "WebClient",
        lambda token: _FakeWebClient(token, error="invalid_auth"),
    )

    with pytest.raises(SystemExit):
        seed_slack_installation.main()

    assert "invalid_auth" in capsys.readouterr().out


def test_main_seeds_installation_store_from_existing_token(monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-old-token")
    monkeypatch.setattr(
        seed_slack_installation, "WebClient",
        lambda token: _FakeWebClient(
            token,
            response=_FakeAuthTestResponse(
                {"team_id": "T123", "user_id": "U_BOT", "bot_id": "B123"},
                headers={"x-oauth-scopes": "chat:write,channels:history"},
            ),
        ),
    )
    monkeypatch.setattr(seed_slack_installation, "get_slack_settings", lambda: SimpleNamespace(
        supabase_url="http://fake", supabase_service_role_key="fake.fake.fake",
    ))

    saved_bots = []

    class FakeStore:
        def __init__(self, supabase):
            pass

        def save_bot(self, bot):
            saved_bots.append(bot)

    monkeypatch.setattr(seed_slack_installation, "SupabaseInstallationStore", FakeStore)

    seed_slack_installation.main()

    assert len(saved_bots) == 1
    bot = saved_bots[0]
    assert bot.team_id == "T123"
    assert bot.bot_token == "xoxb-old-token"
    assert bot.bot_user_id == "U_BOT"
    assert bot.bot_id == "B123"
    assert list(bot.bot_scopes) == ["chat:write", "channels:history"]
    assert "Seeded slack_installations for team_id='T123'" in capsys.readouterr().out
