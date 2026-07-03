import hashlib
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from ingestion_api.documents_repo import delete_missing, existing_keys, upsert_chunks
from ingestion_api.embeddings import embed_documents, to_pgvector

SLACK_SOURCE = "slack"

SYSTEM_SUBTYPES: set[str] = {
    "bot_message",
    "channel_join",
    "channel_leave",
    "channel_archive",
    "channel_unarchive",
    "channel_name",
    "channel_purpose",
    "channel_topic",
    "group_join",
    "group_leave",
}


class SlackMessage(TypedDict):
    channel_id: str
    channel_name: str
    ts: str
    user_id: str
    text: str
    permalink: str
    thread_ts: str | None


# ---------------------------------------------------------------------------
# Slice 1 — Normalization + channel config
# ---------------------------------------------------------------------------

def normalize_message(raw: dict[str, Any], channel_id: str, channel_name: str) -> SlackMessage | None:
    """Return a SlackMessage or None if the message should be filtered out."""
    if raw.get("bot_id"):
        return None
    if raw.get("subtype") in SYSTEM_SUBTYPES:
        return None
    text = raw.get("text", "").strip()
    if not text:
        return None
    return SlackMessage(
        channel_id=channel_id,
        channel_name=channel_name,
        ts=raw["ts"],
        user_id=raw.get("user", ""),
        text=text,
        permalink=raw.get("permalink", ""),
        thread_ts=raw.get("thread_ts"),
    )


def list_monitored_channels(supabase_client: Any) -> list[dict[str, Any]]:
    """Return all enabled rows from the monitored_channels table."""
    rows = (
        supabase_client
        .table("monitored_channels")
        .select("channel_id,channel_name,backfill_limit")
        .eq("enabled", True)
        .execute()
        .data
    )
    return rows


# ---------------------------------------------------------------------------
# Slice 2 — Persistence
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def ingest_slack_message(workspace_id: str, msg: SlackMessage) -> None:
    """Embed and upsert a Slack message. Idempotent — safe to call on edits."""
    now = datetime.now(timezone.utc).isoformat()
    chunk_key = f"{msg['channel_id']}:{msg['ts']}"
    digest = _content_hash(msg["text"])
    vectors = embed_documents([msg["text"]])
    upsert_chunks([{
        "workspace_id": workspace_id,
        "source": SLACK_SOURCE,
        "source_id": msg["channel_id"],
        "chunk_key": chunk_key,
        "content": msg["text"],
        "content_hash": digest,
        "metadata": {
            "channel_id": msg["channel_id"],
            "channel_name": msg["channel_name"],
            "user_id": msg["user_id"],
            "ts": msg["ts"],
            "permalink": msg["permalink"],
            "thread_ts": msg["thread_ts"],
            "last_ingested": now,
        },
        "embedding": to_pgvector(vectors[0]),
        "updated_at": now,
    }])


def delete_slack_message(workspace_id: str, channel_id: str, ts: str) -> None:
    """Remove a single Slack message chunk from the vector store."""
    chunk_key = f"{channel_id}:{ts}"
    current_keys = existing_keys(workspace_id, SLACK_SOURCE, channel_id)
    delete_missing(workspace_id, SLACK_SOURCE, channel_id, current_keys - {chunk_key})


# ---------------------------------------------------------------------------
# Slice 3 — Backfill
# ---------------------------------------------------------------------------

def backfill_channel(
    slack_client: Any,
    workspace_id: str,
    channel_id: str,
    channel_name: str,
    limit: int = 200,
) -> int:
    """Fetch up to `limit` recent messages and ingest ones not already stored.

    Returns the count of messages inserted.
    """
    response = slack_client.conversations_history(channel=channel_id, limit=limit)
    messages: list[dict[str, Any]] = response.get("messages", [])

    valid = [
        m for raw in messages
        if (m := normalize_message(raw, channel_id, channel_name)) is not None
    ]
    if not valid:
        return 0

    seen = existing_keys(workspace_id, SLACK_SOURCE, channel_id)
    new_msgs = [m for m in valid if f"{m['channel_id']}:{m['ts']}" not in seen]
    if not new_msgs:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    vectors = embed_documents([m["text"] for m in new_msgs])
    if len(vectors) != len(new_msgs):
        raise RuntimeError("Voyage returned a different number of embeddings than requested")

    rows: list[dict[str, Any]] = []
    for msg, vector in zip(new_msgs, vectors, strict=True):
        rows.append({
            "workspace_id": workspace_id,
            "source": SLACK_SOURCE,
            "source_id": msg["channel_id"],
            "chunk_key": f"{msg['channel_id']}:{msg['ts']}",
            "content": msg["text"],
            "content_hash": _content_hash(msg["text"]),
            "metadata": {
                "channel_id": msg["channel_id"],
                "channel_name": msg["channel_name"],
                "user_id": msg["user_id"],
                "ts": msg["ts"],
                "permalink": msg["permalink"],
                "thread_ts": msg["thread_ts"],
                "last_ingested": now,
            },
            "embedding": to_pgvector(vector),
            "updated_at": now,
        })
    upsert_chunks(rows)
    return len(rows)
