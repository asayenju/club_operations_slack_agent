import pytest

from tools.slack_search import (
    SLACK_RTS_SEARCH_TOOL,
    SlackSearchError,
    search_slack_public_context,
)


class FakeSlackClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def api_call(self, method, json):
        self.calls.append({"method": method, "json": json})
        return self.response


FAKE_MESSAGE = {
    "author_name": "Asha",
    "author_user_id": "U123",
    "team_id": "T123",
    "channel_id": "C123",
    "channel_name": "general",
    "message_ts": "1710000000.000100",
    "content": "We decided to table on Friday.",
    "is_author_bot": False,
    "permalink": "https://example.slack.com/archives/C123/p1710000000000100",
    "context_messages": {"before": [], "after": []},
}


def test_slack_rts_tool_metadata_is_claude_compatible():
    assert SLACK_RTS_SEARCH_TOOL["name"] == "search_slack_public_context"
    assert "description" in SLACK_RTS_SEARCH_TOOL

    input_schema = SLACK_RTS_SEARCH_TOOL["input_schema"]
    assert input_schema["type"] == "object"
    assert input_schema["required"] == ["query", "action_token"]
    assert input_schema["additionalProperties"] is False
    assert "query" in input_schema["properties"]
    assert "action_token" in input_schema["properties"]
    assert "limit" in input_schema["properties"]
    assert input_schema["properties"]["limit"]["default"] == 10
    assert input_schema["properties"]["limit"]["maximum"] == 20
    assert "Sensitive" in input_schema["properties"]["action_token"]["description"]


def test_search_slack_public_context_normalizes_messages():
    client = FakeSlackClient({"ok": True, "results": {"messages": [FAKE_MESSAGE]}})

    results = search_slack_public_context(
        client=client,
        query="What did we decide about tabling?",
        action_token="action-token",
        limit=10,
    )

    assert client.calls == [
        {
            "method": "assistant.search.context",
            "json": {
                "query": "What did we decide about tabling?",
                "action_token": "action-token",
                "channel_types": ["public_channel"],
                "content_types": ["messages"],
                "include_context_messages": True,
                "limit": 10,
            },
        }
    ]
    assert len(results) == 1
    ev = results[0]
    assert ev.source == "slack"
    assert ev.text == "We decided to table on Friday."
    assert ev.author == "Asha"
    assert ev.timestamp == "1710000000.000100"
    assert ev.similarity is None
    assert ev.score is None
    assert ev.citation.source == "slack"
    assert ev.citation.label == "#general — 1710000000.000100"
    assert ev.metadata["permalink"] == "https://example.slack.com/archives/C123/p1710000000000100"
    assert ev.metadata["channel_name"] == "general"


def test_search_slack_public_context_requires_action_token():
    client = FakeSlackClient({"ok": True, "results": {"messages": []}})

    with pytest.raises(ValueError, match="action_token"):
        search_slack_public_context(client=client, query="budget", action_token="")


def test_search_slack_public_context_raises_for_slack_error():
    client = FakeSlackClient({"ok": False, "error": "missing_scope"})

    with pytest.raises(SlackSearchError, match="missing_scope"):
        search_slack_public_context(
            client=client,
            query="budget",
            action_token="action-token",
        )


def test_search_slack_public_context_clamps_limit_to_api_max():
    client = FakeSlackClient({"ok": True, "results": {"messages": []}})

    search_slack_public_context(
        client=client,
        query="budget",
        action_token="action-token",
        limit=50,
    )

    assert client.calls[0]["json"]["limit"] == 20


def test_search_slack_citation_falls_back_when_no_channel_name():
    message = {**FAKE_MESSAGE, "channel_name": "", "message_ts": "1710000000.000100"}
    client = FakeSlackClient({"ok": True, "results": {"messages": [message]}})

    results = search_slack_public_context(client=client, query="q", action_token="tok")
    assert results[0].citation.label == "Slack — 1710000000.000100"


def test_search_slack_citation_label_slack_only_when_no_ts():
    message = {**FAKE_MESSAGE, "channel_name": "", "message_ts": ""}
    client = FakeSlackClient({"ok": True, "results": {"messages": [message]}})

    results = search_slack_public_context(client=client, query="q", action_token="tok")
    assert results[0].citation.label == "Slack"
    assert results[0].timestamp is None
