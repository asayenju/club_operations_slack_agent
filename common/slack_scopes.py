from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

REQUIRED_HISTORY_SCOPES = ("channels:history", "groups:history")


class SlackScopeError(RuntimeError):
    pass


def verify_slack_scopes(client: WebClient, sample_channel_id: str | None = None) -> None:
    """Confirm the bot token is valid and (if a channel is given) has history access.

    Raises SlackScopeError with an actionable message on auth or missing_scope
    failures rather than letting backfill fail deep inside pagination.
    """
    try:
        client.auth_test()
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown_error")
        raise SlackScopeError(
            f"Slack auth_test failed ({error}); the resolved bot token for this "
            "workspace is invalid or missing. Complete the OAuth install flow at "
            "/slack/install, or check the corresponding row in slack_installations."
        ) from exc

    if not sample_channel_id:
        return

    try:
        client.conversations_history(channel=sample_channel_id, limit=1)
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown_error")
        if error == "missing_scope":
            needed = exc.response.get("needed", "/".join(REQUIRED_HISTORY_SCOPES))
            raise SlackScopeError(
                f"Bot token is missing a required scope ({needed}). "
                f"Grant {' and '.join(REQUIRED_HISTORY_SCOPES)} in the Slack app config "
                "and reinstall the app to the workspace. For private channels, also "
                "confirm the bot has been added to the channel before testing history "
                "or real-time ingestion."
            ) from exc
        raise SlackScopeError(f"Slack conversations.history check failed: {error}") from exc
