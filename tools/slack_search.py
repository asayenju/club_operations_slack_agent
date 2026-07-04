from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from tools.models import Citation, Evidence


SLACK_RTS_SEARCH_TOOL = {
    "name": "search_slack_public_context",
    "description": (
        "Search public Slack messages in real time using Slack's "
        "assistant.search.context API. Requires a short-lived Slack action_token "
        "from the current Slack interaction. Never log or expose the action_token."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The natural-language search query to run against public Slack messages.",
            },
            "action_token": {
                "type": "string",
                "description": (
                    "Sensitive short-lived Slack action token from the current "
                    "Slack interaction. Required for bot-token real-time search."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of Slack chunks to return. Defaults to 10 and is clamped to 20.",
                "default": 10,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query", "action_token"],
        "additionalProperties": False,
    },
}


class SlackSearchError(RuntimeError):
    pass


def search_slack_public_context(
    client: WebClient,
    query: str,
    action_token: str,
    limit: int = 10,
) -> list[Evidence]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if not action_token:
        raise ValueError("action_token is required for bot-token Slack RTS search")

    payload = {
        "query": normalized_query,
        "action_token": action_token,
        "channel_types": ["public_channel"],
        "content_types": ["messages"],
        "include_context_messages": True,
        "limit": min(max(limit, 1), 20),
    }

    try:
        response = client.api_call("assistant.search.context", json=payload)
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown_error")
        raise SlackSearchError(f"Slack RTS search failed: {error}") from exc

    if not response.get("ok", False):
        raise SlackSearchError(
            f"Slack RTS search failed: {response.get('error', 'unknown_error')}"
        )

    return [_message_to_evidence(message) for message in _message_results(response)]


def _message_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    results = response.get("results") or {}
    messages = results.get("messages") or []
    return [message for message in messages if isinstance(message, dict)]


def _message_to_evidence(message: dict[str, Any]) -> Evidence:
    channel_name = message.get("channel_name", "")
    message_ts = message.get("message_ts", "")
    channel_part = f"#{channel_name}" if channel_name else "Slack"
    label = f"{channel_part} — {message_ts}" if message_ts else channel_part

    return Evidence(
        source="slack",
        text=_message_text(message),
        citation=Citation(source="slack", label=label),
        similarity=None,  # Slack RTS is keyword search, no pgvector score
        score=None,
        timestamp=message_ts or None,
        author=message.get("author_name"),
        metadata={
            "permalink": message.get("permalink"),
            "channel_id": message.get("channel_id"),
            "channel_name": channel_name,
            "team_id": message.get("team_id"),
            "is_author_bot": message.get("is_author_bot"),
            "context_messages": message.get("context_messages") or {},
        },
    )


def _message_text(message: dict[str, Any]) -> str:
    return str(message.get("content") or message.get("text") or "").strip()
