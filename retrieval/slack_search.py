from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from retrieval.models import RetrievedChunk


class SlackSearchError(RuntimeError):
    pass


def search_slack_public_context(
    client: WebClient,
    query: str,
    action_token: str,
    limit: int = 10,
) -> list[RetrievedChunk]:
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

    return [_message_to_chunk(message) for message in _message_results(response)]


def _message_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    results = response.get("results") or {}
    messages = results.get("messages") or []
    return [message for message in messages if isinstance(message, dict)]


def _message_to_chunk(message: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        source="slack",
        text=_message_text(message),
        permalink=message.get("permalink"),
        channel_id=message.get("channel_id"),
        channel_name=message.get("channel_name"),
        author_user_id=message.get("author_user_id"),
        author_name=message.get("author_name"),
        timestamp=message.get("message_ts"),
        metadata={
            "team_id": message.get("team_id"),
            "is_author_bot": message.get("is_author_bot"),
            "context_messages": message.get("context_messages") or {},
        },
    )


def _message_text(message: dict[str, Any]) -> str:
    return str(message.get("content") or message.get("text") or "").strip()
