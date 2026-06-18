import os
import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from retrieval.models import RetrievedChunk
from retrieval.slack_search import SlackSearchError, search_slack_public_context


DEFAULT_RESULT_LIMIT = 10

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    token_verification_enabled=os.environ.get(
        "SLACK_TOKEN_VERIFICATION_ENABLED", "false"
    ).lower()
    == "true",
)


@app.event("app_mention")
def handle_app_mention(event, client, say):
    query = extract_query(event.get("text", ""), event.get("bot_id"))
    if not query:
        say(
            text="Ask me what to search for, for example: `@student-org-agent what did we decide about tabling?`",
            thread_ts=event.get("ts"),
        )
        return

    action_token = event.get("action_token")
    try:
        chunks = search_slack_public_context(
            client=client,
            query=query,
            action_token=action_token,
            limit=DEFAULT_RESULT_LIMIT,
        )
    except (SlackSearchError, ValueError) as exc:
        say(text=f"I couldn't search Slack yet: {exc}", thread_ts=event.get("ts"))
        return

    say(
        text=format_chunks_response(query, chunks),
        thread_ts=event.get("ts"),
        unfurl_links=False,
        unfurl_media=False,
    )


def extract_query(text: str, bot_id: str | None = None) -> str:
    query = text or ""
    query = re.sub(r"<@[A-Z0-9]+>", "", query)
    if bot_id:
        query = query.replace(bot_id, "")
    return " ".join(query.split())


def format_chunks_response(query: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return f"No public Slack results found for: `{query}`"

    lines = [f"Top public Slack results for: `{query}`"]
    for index, chunk in enumerate(chunks, start=1):
        location = chunk.channel_name or chunk.channel_id or "unknown channel"
        author = chunk.author_name or chunk.author_user_id or "unknown author"
        text = _truncate(chunk.text, 280)
        citation = f" <{chunk.permalink}|Open>" if chunk.permalink else ""
        lines.append(f"{index}. *#{location}* - {author}: {text}{citation}")
    return "\n".join(lines)


def _truncate(text: str, max_length: int) -> str:
    clean_text = " ".join((text or "").split())
    if len(clean_text) <= max_length:
        return clean_text
    return f"{clean_text[: max_length - 3].rstrip()}..."


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
