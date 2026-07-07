from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from common.config import get_ingestion_settings


@lru_cache
def get_supabase_client() -> Client:
    settings = get_ingestion_settings()
    return create_client(
        settings.required_supabase_url,
        settings.required_supabase_service_key,
    )


def existing_keys(workspace_id: str, source: str, source_id: str) -> set[str]:
    response = (
        get_supabase_client()
        .table("documents")
        .select("chunk_key")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
    )
    return {row["chunk_key"] for row in response.data or []}


def existing_key_state(workspace_id: str, source: str, source_id: str) -> dict[str, dict[str, Any]]:
    """Return {chunk_key: {"content_hash": ..., "metadata": ...}} for a source.

    Used to detect both content edits (content_hash) and thread activity
    (metadata.latest_reply_ts) in a single query instead of two identical
    scans over the same rows.
    """
    response = (
        get_supabase_client()
        .table("documents")
        .select("chunk_key,content_hash,metadata")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
    )
    return {
        row["chunk_key"]: {
            "content_hash": row["content_hash"],
            "metadata": row.get("metadata") or {},
        }
        for row in response.data or []
    }


def list_by_source(
    workspace_id: str,
    source: str,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """List all rows for a workspace/source with no vector search or similarity threshold.

    Used where a semantic-search cutoff would risk false negatives (e.g.
    detecting whether a decision exists at all, not just whether one is a
    close match to a query).
    """
    query = (
        get_supabase_client()
        .table("documents")
        .select("source,content,source_id,chunk_key,author_id,channel_id,metadata,created_at")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
    )
    if since:
        query = query.gte("created_at", since)
    response = query.execute()
    return response.data or []


def upsert_chunks(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    (
        get_supabase_client()
        .table("documents")
        .upsert(
            rows,
            on_conflict="workspace_id,source,source_id,chunk_key",
        )
        .execute()
    )


def replace_source_chunks(
    workspace_id: str,
    source: str,
    source_id: str,
    rows: list[dict[str, Any]],
) -> int:
    current_keys = {str(row["chunk_key"]) for row in rows}
    upsert_chunks(rows)
    return delete_missing(workspace_id, source, source_id, current_keys)


def delete_source(workspace_id: str, source: str, source_id: str) -> int:
    keys = existing_keys(workspace_id, source, source_id)
    if not keys:
        return 0

    (
        get_supabase_client()
        .table("documents")
        .delete()
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
    )
    return len(keys)


def delete_chunk_key(workspace_id: str, source: str, source_id: str, chunk_key: str) -> int:
    """Delete a single row by its exact chunk_key — O(1), no full-key scan."""
    response = (
        get_supabase_client()
        .table("documents")
        .delete()
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .eq("chunk_key", chunk_key)
        .execute()
    )
    return len(response.data or [])


def delete_missing(
    workspace_id: str,
    source: str,
    source_id: str,
    current_keys: set[str],
) -> int:
    stale_keys = existing_keys(workspace_id, source, source_id) - current_keys
    if not stale_keys:
        return 0

    (
        get_supabase_client()
        .table("documents")
        .delete()
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .in_("chunk_key", sorted(stale_keys))
        .execute()
    )
    return len(stale_keys)


def match_documents(
    workspace_id: str,
    query_embedding: list[float],
    limit: int = 10,
    sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    response = (
        get_supabase_client()
        .rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_count": limit,
                "filter_workspace": workspace_id,
                "filter_sources": sources,
            },
        )
        .execute()
    )
    return response.data or []
