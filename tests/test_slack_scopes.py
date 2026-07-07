import pytest
from slack_sdk.errors import SlackApiError

from common.slack_scopes import SlackScopeError, verify_slack_scopes


class _FakeResponse:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)


class _FakeClient:
    def __init__(self, auth_error=None, history_error=None):
        self.auth_error = auth_error
        self.history_error = history_error

    def auth_test(self):
        if self.auth_error:
            raise SlackApiError("auth failed", _FakeResponse({"error": self.auth_error}))
        return {"ok": True}

    def conversations_history(self, channel, limit):
        if self.history_error:
            raise SlackApiError(
                "history failed",
                _FakeResponse({"error": self.history_error, "needed": "channels:history"}),
            )
        return {"ok": True, "messages": []}


def test_verify_slack_scopes_happy_path_without_channel():
    verify_slack_scopes(_FakeClient())


def test_verify_slack_scopes_happy_path_with_channel():
    verify_slack_scopes(_FakeClient(), sample_channel_id="C01")


def test_verify_slack_scopes_raises_on_invalid_auth():
    with pytest.raises(SlackScopeError, match="auth_test failed"):
        verify_slack_scopes(_FakeClient(auth_error="invalid_auth"))


def test_verify_slack_scopes_raises_on_missing_scope():
    with pytest.raises(SlackScopeError, match="missing a required scope"):
        verify_slack_scopes(_FakeClient(history_error="missing_scope"), sample_channel_id="C01")


def test_verify_slack_scopes_raises_on_other_history_error():
    with pytest.raises(SlackScopeError, match="conversations.history check failed"):
        verify_slack_scopes(_FakeClient(history_error="channel_not_found"), sample_channel_id="C01")
