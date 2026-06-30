"""
Ingest a single /decide statement from Slack into Supabase.

Called from the Slack Bolt app when a /decide slash command is received.
Each statement is stored as a single chunk under source='slack_decide',
source_id=channel_id, so all decisions for a channel share a source_id.

Usage (from Slack Bolt handler):
    from ingestion_api.ingest_decide import ingest_decide_statement

    ingest_decide_statement(
        statement="We approved $500 for the spring gala venue.",
        workspace_id=body["team_id"],
        channel_id=body["channel_id"],
        channel_name=body["channel_name"],
        user_id=body["user_id"],
        user_name=body["user_name"],
        received_at=datetime.now(timezone.utc).isoformat(),
    )
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from ingestion_api.documents_repo import upsert_chunks
from ingestion_api.embeddings import embed_documents, to_pgvector


DECIDE_SOURCE = "slack_decide"


def _content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _timestamp_ms(received_at: str) -> str:
    """Return a compact ms-precision string suitable for chunk_key use."""
    try:
        dt = datetime.fromisoformat(received_at)
        return str(int(dt.timestamp() * 1000))
    except (ValueError, OSError):
        return re.sub(r"[^0-9]", "", received_at)[:13]


def ingest_decide_statement(
    statement: str,
    workspace_id: str,
    channel_id: str,
    channel_name: str,
    user_id: str,
    user_name: str,
    received_at: str | None = None,
) -> dict[str, Any]:
    """
    Embed and upsert a single /decide statement.

    Returns the row dict that was written to Supabase.
    Raises ValueError for blank statements or missing workspace/channel.
    """
    normalized = statement.strip()
    if not normalized:
        raise ValueError("statement must not be empty")
    if not workspace_id or not workspace_id.strip():
        raise ValueError("workspace_id must not be empty")
    if not channel_id or not channel_id.strip():
        raise ValueError("channel_id must not be empty")

    ts = received_at or datetime.now(timezone.utc).isoformat()
    digest = _content_hash(normalized)
    chunk_key = f"decide:{digest[:8]}:{_timestamp_ms(ts)}"

    [vector] = embed_documents([normalized])
    now = datetime.now(timezone.utc).isoformat()

    row: dict[str, Any] = {
        "workspace_id": workspace_id,
        "source": DECIDE_SOURCE,
        "source_id": channel_id,
        "chunk_key": chunk_key,
        "content": normalized,
        "content_hash": digest,
        "author_id": user_id,
        "channel_id": channel_id,
        "metadata": {
            "user_name": user_name,
            "channel_name": channel_name,
            "decision_hash": digest,
            "received_at": ts,
        },
        "embedding": to_pgvector(vector),
        "updated_at": now,
    }
    upsert_chunks([row])
    return row
