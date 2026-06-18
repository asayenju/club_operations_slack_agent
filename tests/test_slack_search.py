import pytest

from retrieval.slack_search import SlackSearchError, search_slack_public_context


class FakeSlackClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def api_call(self, method, json):
        self.calls.append({"method": method, "json": json})
        return self.response


def test_search_slack_public_context_normalizes_messages():
    client = FakeSlackClient(
        {
            "ok": True,
            "results": {
                "messages": [
                    {
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
                ]
            },
        }
    )

    chunks = search_slack_public_context(
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
    assert len(chunks) == 1
    assert chunks[0].source == "slack"
    assert chunks[0].text == "We decided to table on Friday."
    assert chunks[0].channel_name == "general"
    assert chunks[0].author_name == "Asha"
    assert chunks[0].permalink == "https://example.slack.com/archives/C123/p1710000000000100"


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
