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


def existing_key_hashes(workspace_id: str, source: str, source_id: str) -> dict[str, str]:
    """Return {chunk_key: content_hash} for a source, used to detect edits."""
    response = (
        get_supabase_client()
        .table("documents")
        .select("chunk_key,content_hash")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
    )
    return {row["chunk_key"]: row["content_hash"] for row in response.data or []}


def existing_metadata(workspace_id: str, source: str, source_id: str) -> dict[str, dict[str, Any]]:
    """Return {chunk_key: metadata} for a source, used to detect thread activity."""
    response = (
        get_supabase_client()
        .table("documents")
        .select("chunk_key,metadata")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
    )
    return {row["chunk_key"]: (row.get("metadata") or {}) for row in response.data or []}


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
    deleted = delete_source(workspace_id, source, source_id)
    upsert_chunks(rows)
    return deleted


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
