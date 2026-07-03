import os
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from common.slack_ingestion import (
    backfill_channel,
    delete_slack_message,
    ingest_slack_message,
    list_monitored_channels,
    normalize_message,
)

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    token_verification_enabled=os.environ.get(
        "SLACK_TOKEN_VERIFICATION_ENABLED", "false"
    ).lower()
    == "true",
)


def _get_supabase():
    from supabase import create_client
    from common.config import get_slack_settings
    s = get_slack_settings()
    return create_client(s.required_supabase_url, s.required_supabase_service_key)


def _get_workspace_id() -> str:
    from common.config import get_slack_settings
    return get_slack_settings().required_workspace_id


# ---------------------------------------------------------------------------
# Slice 3 — Startup backfill
# ---------------------------------------------------------------------------

def _run_backfill() -> None:
    try:
        supabase = _get_supabase()
        workspace_id = _get_workspace_id()
        channels = list_monitored_channels(supabase)
        for ch in channels:
            count = backfill_channel(
                app.client,
                workspace_id,
                ch["channel_id"],
                ch["channel_name"],
                ch.get("backfill_limit", 200),
            )
            print(f"[backfill] #{ch['channel_name']}: {count} messages ingested")
    except Exception as exc:
        print(f"[backfill] failed: {exc}")


# ---------------------------------------------------------------------------
# Existing handlers
# ---------------------------------------------------------------------------

@app.message("hello")
def message_hello(message, say):
    say(build_hello_response(message["user"]))


def build_hello_response(user_id: str) -> dict:
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Hey there <@{user_id}>!"},
            }
        ],
        "text": f"Hey there <@{user_id}>!",
    }


# ---------------------------------------------------------------------------
# Slice 4 — Real-time message ingestion
# ---------------------------------------------------------------------------

_monitored_channel_ids: set[str] | None = None
_monitored_lock = threading.Lock()


def _get_monitored_ids() -> set[str]:
    global _monitored_channel_ids
    with _monitored_lock:
        if _monitored_channel_ids is None:
            try:
                supabase = _get_supabase()
                rows = list_monitored_channels(supabase)
                _monitored_channel_ids = {r["channel_id"] for r in rows}
            except Exception as exc:
                print(f"[monitored_channels] failed to load: {exc}")
                return set()
    return _monitored_channel_ids


@app.event("message")
def handle_message(event, logger):
    channel_id = event.get("channel", "")
    if channel_id not in _get_monitored_ids():
        return

    subtype = event.get("subtype")
    workspace_id = _get_workspace_id()

    try:
        if subtype == "message_deleted":
            ts = event.get("deleted_ts", "")
            if ts:
                delete_slack_message(workspace_id, channel_id, ts)

        elif subtype == "message_changed":
            raw = event.get("message", {})
            channel_name = event.get("channel_name", channel_id)
            msg = normalize_message(raw, channel_id, channel_name)
            if msg:
                ingest_slack_message(workspace_id, msg)

        elif subtype is None:
            channel_name = event.get("channel_name", channel_id)
            msg = normalize_message(event, channel_id, channel_name)
            if msg:
                ingest_slack_message(workspace_id, msg)

    except Exception as exc:
        logger.error(f"[handle_message] ingestion failed for {channel_id}: {exc}")


if __name__ == "__main__":
    threading.Thread(target=_run_backfill, daemon=True).start()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
