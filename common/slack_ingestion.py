import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterator, TypedDict

from slack_sdk.errors import SlackApiError

from ingestion_api.documents_repo import (
    delete_chunk_key,
    delete_missing,
    existing_key_state,
    upsert_chunks,
)
from ingestion_api.embeddings import embed_documents, to_pgvector

_HISTORY_PAGE_SIZE = 200
_MAX_BACKOFF_RETRIES = 5
_INTER_CALL_DELAY_SECONDS = 1.2
_EMBED_SUB_BATCH_SIZE = 20

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


def list_monitored_channels(supabase_client: Any, workspace_id: str) -> list[dict[str, Any]]:
    """Return all enabled rows from the monitored_channels table for one workspace."""
    rows = (
        supabase_client
        .table("monitored_channels")
        .select(
            "channel_id,channel_name,backfill_limit,oldest_ts_backfilled,"
            "initial_backfill_complete,last_reconciled_at,last_reconciled_ts"
        )
        .eq("workspace_id", workspace_id)
        .eq("enabled", True)
        .execute()
        .data
    )
    return rows


def delete_monitored_channels_for_workspace(supabase_client: Any, workspace_id: str) -> int:
    """Stop watching every channel for a workspace (issue #64 -- called when
    an install is removed via app_uninstalled/tokens_revoked). Returns the
    number of rows deleted."""
    rows = (
        supabase_client
        .table("monitored_channels")
        .delete()
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    return len(rows)


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
        "author_id": msg["user_id"],
        "channel_id": msg["channel_id"],
        "metadata": {
            "channel_name": msg["channel_name"],
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
    delete_chunk_key(workspace_id, SLACK_SOURCE, channel_id, chunk_key)


# ---------------------------------------------------------------------------
# Slice 3 — Backfill
# ---------------------------------------------------------------------------

def _slack_call_with_backoff(fn: Any, *args: Any, max_retries: int = _MAX_BACKOFF_RETRIES, **kwargs: Any) -> Any:
    """Call a Slack SDK function, retrying on rate limits and pacing calls proactively.

    Standard (non-Marketplace) Slack apps get tight, shared-workspace rate
    limits on conversations.history/replies, so every call site paces itself
    rather than only reacting to 429s.
    """
    for attempt in range(max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            time.sleep(_INTER_CALL_DELAY_SECONDS)
            return result
        except SlackApiError as exc:
            error = exc.response.get("error", "unknown_error")
            if error != "ratelimited" or attempt == max_retries:
                raise
            headers = getattr(exc.response, "headers", {}) or {}
            retry_after = int(headers.get("Retry-After", "1"))
            time.sleep(retry_after)
    raise RuntimeError("unreachable")  # pragma: no cover


def _paginate_history(
    client: Any,
    channel_id: str,
    oldest: str | None = None,
    limit: int | None = None,
    state: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield raw messages from conversations.history, paginating via cursor.

    `state` (if given) is mutated with `exhausted=True` once Slack reports no
    further pages, or `exhausted=False` if the walk stopped early because
    `limit` (this run's message budget) was reached.
    """
    if state is None:
        state = {}
    fetched = 0
    cursor: str | None = None
    while True:
        page_size = _HISTORY_PAGE_SIZE
        if limit is not None:
            remaining = limit - fetched
            if remaining <= 0:
                state["exhausted"] = False
                return
            page_size = min(page_size, remaining)

        kwargs: dict[str, Any] = {"channel": channel_id, "limit": page_size}
        if cursor:
            kwargs["cursor"] = cursor
        if oldest:
            kwargs["oldest"] = oldest

        response = _slack_call_with_backoff(client.conversations_history, **kwargs)
        messages: list[dict[str, Any]] = response.get("messages", [])
        for raw in messages:
            yield raw
        fetched += len(messages)

        cursor = (response.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor or not messages:
            state["exhausted"] = True
            return


def _paginate_replies(
    client: Any,
    channel_id: str,
    thread_ts: str,
) -> Iterator[dict[str, Any]]:
    """Yield reply messages (excluding the thread root) from conversations.replies."""
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"channel": channel_id, "ts": thread_ts, "limit": _HISTORY_PAGE_SIZE}
        if cursor:
            kwargs["cursor"] = cursor
        response = _slack_call_with_backoff(client.conversations_replies, **kwargs)
        messages: list[dict[str, Any]] = response.get("messages", [])
        for raw in messages:
            if raw.get("ts") == thread_ts:
                continue  # conversations.replies includes the root itself
            yield raw
        cursor = (response.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor or not messages:
            return


def _update_channel_progress(supabase_client: Any, workspace_id: str, channel_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    (
        supabase_client
        .table("monitored_channels")
        .update(fields)
        .eq("workspace_id", workspace_id)
        .eq("channel_id", channel_id)
        .execute()
    )


class BackfillResult(TypedDict):
    ingested: int
    failed: int
    errors: list[str]
    deleted: int


def _empty_result(deleted: int = 0) -> BackfillResult:
    return BackfillResult(ingested=0, failed=0, errors=[], deleted=deleted)


def _embed_with_fault_isolation(
    messages: list[SlackMessage],
) -> tuple[list[tuple[SlackMessage, list[float]]], list[str]]:
    """Embed messages in sub-batches so one bad message doesn't drop the whole run.

    A failing sub-batch is retried message-by-message to isolate which
    message actually failed; only that message is dropped/reported.
    """
    succeeded: list[tuple[SlackMessage, list[float]]] = []
    errors: list[str] = []
    for i in range(0, len(messages), _EMBED_SUB_BATCH_SIZE):
        batch = messages[i:i + _EMBED_SUB_BATCH_SIZE]
        try:
            vectors = embed_documents([m["text"] for m in batch])
            if len(vectors) != len(batch):
                raise RuntimeError("embedding count mismatch")
            succeeded.extend(zip(batch, vectors, strict=True))
        except Exception:
            for msg in batch:
                try:
                    vectors = embed_documents([msg["text"]])
                    if len(vectors) != 1:
                        raise RuntimeError("embedding count mismatch")
                    succeeded.append((msg, vectors[0]))
                except Exception as msg_exc:
                    errors.append(f"{msg['channel_id']}:{msg['ts']}: {msg_exc}")
    return succeeded, errors


def backfill_channel(
    slack_client: Any,
    supabase_client: Any,
    workspace_id: str,
    channel: dict[str, Any],
    *,
    full_walk: bool = False,
) -> BackfillResult:
    """Fetch a monitored channel's history and ingest/reconcile it into `documents`.

    Two modes:
    - `full_walk=False` (default, used for the initial bounded backfill):
      resumable via `channel["oldest_ts_backfilled"]`/`backfill_limit`, only
      ingests messages not already stored. Cheap, but does not detect edits
      or deletions.
    - `full_walk=True` (used for scheduled reconciliation): walks the entire
      channel history (ignoring the resume bound and budget), diffs against
      stored content hashes to catch edits, and — only if the walk completes
      without error — reconciles deletions. This is more expensive, which is
      why it's the scheduled/on-demand reconciliation path, not every run.

    A failure embedding/upserting one message does not drop the rest of the
    channel's run.
    """
    channel_id = channel["channel_id"]
    channel_name = channel["channel_name"]
    limit = None if full_walk else channel.get("backfill_limit", 200)
    oldest = None if full_walk else channel.get("oldest_ts_backfilled")

    key_state = existing_key_state(workspace_id, SLACK_SOURCE, channel_id)
    existing_hashes = {key: state["content_hash"] for key, state in key_state.items()}
    stored_meta = {key: state["metadata"] for key, state in key_state.items()}
    seen = set(key_state.keys())

    raw_top_level: list[dict[str, Any]] = []
    min_ts_seen: str | None = None
    max_ts_seen: str | None = None
    pagination_state: dict[str, Any] = {}

    try:
        for raw in _paginate_history(slack_client, channel_id, oldest=oldest, limit=limit, state=pagination_state):
            ts = raw.get("ts")
            if ts and (min_ts_seen is None or ts < min_ts_seen):
                min_ts_seen = ts
            if ts and (max_ts_seen is None or ts > max_ts_seen):
                max_ts_seen = ts
            raw_top_level.append(raw)
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown_error")
        _update_channel_progress(
            supabase_client,
            workspace_id,
            channel_id,
            last_backfill_error=error,
            last_backfill_error_at=datetime.now(timezone.utc).isoformat(),
        )
        return _empty_result()

    # Pass 2: fetch thread replies for threads that are new or whose latest
    # reply advanced since the last run — avoids re-walking every thread on
    # every run. Threads we skip are tracked so the deletion-reconciliation
    # diff below doesn't mistake "we didn't re-check this thread" for
    # "these replies were deleted."
    all_raw = list(raw_top_level)
    latest_reply_by_ts: dict[str, str] = {}
    skipped_thread_ts: set[str] = set()
    for raw in raw_top_level:
        reply_count = raw.get("reply_count") or 0
        latest_reply = raw.get("latest_reply")
        if not reply_count or not latest_reply:
            continue
        parent_ts = raw.get("ts")
        latest_reply_by_ts[parent_ts] = latest_reply
        parent_key = f"{channel_id}:{parent_ts}"
        thread_ts = raw.get("thread_ts") or parent_ts
        previously_seen_latest_reply = stored_meta.get(parent_key, {}).get("latest_reply_ts")
        if previously_seen_latest_reply == latest_reply:
            skipped_thread_ts.add(thread_ts)
            continue  # no new replies since last time
        try:
            all_raw.extend(_paginate_replies(slack_client, channel_id, thread_ts))
        except SlackApiError:
            skipped_thread_ts.add(thread_ts)  # one thread failing shouldn't abort the channel

    normalized: list[SlackMessage] = []
    fetched_keys: set[str] = set()
    for raw in all_raw:
        msg = normalize_message(raw, channel_id, channel_name)
        if msg is None:
            continue
        chunk_key = f"{msg['channel_id']}:{msg['ts']}"
        fetched_keys.add(chunk_key)
        normalized.append(msg)

    to_ingest: list[SlackMessage] = []
    for msg in normalized:
        chunk_key = f"{msg['channel_id']}:{msg['ts']}"
        if chunk_key not in seen:
            to_ingest.append(msg)  # new message
        elif full_walk and existing_hashes.get(chunk_key) != _content_hash(msg["text"]):
            to_ingest.append(msg)  # edited since last reconciliation

    # Deletion reconciliation requires the fetched set to represent the
    # entire channel — only safe when this was a full, uninterrupted walk.
    deleted_count = 0
    progress: dict[str, Any] = {}
    if full_walk and pagination_state.get("exhausted"):
        keep_keys = fetched_keys | {
            key for key, meta in stored_meta.items() if meta.get("thread_ts") in skipped_thread_ts
        }
        deleted_count = delete_missing(workspace_id, SLACK_SOURCE, channel_id, keep_keys)
        now_iso = datetime.now(timezone.utc).isoformat()
        progress["last_reconciled_at"] = now_iso
        if max_ts_seen is not None:
            progress["last_reconciled_ts"] = max_ts_seen
        if min_ts_seen is not None:
            progress["oldest_ts_backfilled"] = min_ts_seen
        progress["initial_backfill_complete"] = True
    elif not full_walk:
        if min_ts_seen is not None:
            progress["oldest_ts_backfilled"] = min_ts_seen
        if pagination_state.get("exhausted"):
            progress["initial_backfill_complete"] = True
    if progress:
        _update_channel_progress(supabase_client, workspace_id, channel_id, **progress)

    if not to_ingest:
        return _empty_result(deleted=deleted_count)

    now = datetime.now(timezone.utc).isoformat()
    embedded, embed_errors = _embed_with_fault_isolation(to_ingest)

    rows: list[dict[str, Any]] = []
    for msg, vector in embedded:
        metadata: dict[str, Any] = {
            "channel_name": msg["channel_name"],
            "ts": msg["ts"],
            "permalink": msg["permalink"],
            "thread_ts": msg["thread_ts"],
            "last_ingested": now,
        }
        if msg["ts"] in latest_reply_by_ts:
            metadata["latest_reply_ts"] = latest_reply_by_ts[msg["ts"]]
        rows.append({
            "workspace_id": workspace_id,
            "source": SLACK_SOURCE,
            "source_id": msg["channel_id"],
            "chunk_key": f"{msg['channel_id']}:{msg['ts']}",
            "content": msg["text"],
            "content_hash": _content_hash(msg["text"]),
            "author_id": msg["user_id"],
            "channel_id": msg["channel_id"],
            "metadata": metadata,
            "embedding": to_pgvector(vector),
            "updated_at": now,
        })
    if rows:
        upsert_chunks(rows)
    return BackfillResult(ingested=len(rows), failed=len(embed_errors), errors=embed_errors, deleted=deleted_count)


# ---------------------------------------------------------------------------
# Slice 6 — Shared orchestration (single implementation for all call sites)
# ---------------------------------------------------------------------------

def run_channel_backfill(
    slack_client: Any,
    supabase_client: Any,
    workspace_id: str,
    *,
    force_full_walk: bool = False,
    log_prefix: str = "backfill",
) -> None:
    """Run backfill/reconciliation across all monitored channels.

    Used by the on-demand endpoint, the scheduled daily reconcile job, and
    the Bolt app's startup thread alike, so there is exactly one place that
    decides "does this channel get a bounded backfill or a full reconcile"
    and exactly one place that isolates one channel's failure from the rest.

    `force_full_walk=True` always does a full reconcile (the scheduled daily
    job). Otherwise each channel's mode is decided by its own
    `initial_backfill_complete` flag — channels still catching up get a
    bounded backfill, channels already caught up get reconciled.
    """
    channels = list_monitored_channels(supabase_client, workspace_id)
    for ch in channels:
        channel_label = ch.get("channel_name") or ch.get("channel_id", "?")
        full_walk = force_full_walk or bool(ch.get("initial_backfill_complete"))
        try:
            result = backfill_channel(slack_client, supabase_client, workspace_id, ch, full_walk=full_walk)
            print(
                f"[{log_prefix}] #{channel_label}: {result['ingested']} ingested, "
                f"{result['failed']} failed, {result['deleted']} deleted"
            )
        except Exception as exc:
            print(f"[{log_prefix}] #{channel_label}: unexpected error, skipping: {exc}")
