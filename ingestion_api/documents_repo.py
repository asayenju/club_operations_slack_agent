from typing import Any

from supabase import Client, create_client

from common.config import get_ingestion_settings

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        s = get_ingestion_settings()
        _client = create_client(s.required_supabase_url, s.required_supabase_service_key)
    return _client


def existing_keys(workspace_id: str, source: str, source_id: str) -> set[str]:
    rows = (
        _get_client()
        .table("documents")
        .select("chunk_key")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
        .data
    )
    return {r["chunk_key"] for r in rows}


def existing_key_hashes(workspace_id: str, source: str, source_id: str) -> dict[str, str]:
    """Return {chunk_key: content_hash} for a channel, used to detect edits."""
    rows = (
        _get_client()
        .table("documents")
        .select("chunk_key,content_hash")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
        .data
    )
    return {r["chunk_key"]: r["content_hash"] for r in rows}


def existing_metadata(workspace_id: str, source: str, source_id: str) -> dict[str, dict[str, Any]]:
    """Return {chunk_key: metadata} for a channel, used to detect thread activity."""
    rows = (
        _get_client()
        .table("documents")
        .select("chunk_key,metadata")
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .execute()
        .data
    )
    return {r["chunk_key"]: (r.get("metadata") or {}) for r in rows}


def upsert_chunks(rows: list[dict[str, Any]]) -> None:
    _get_client().table("documents").upsert(
        rows, on_conflict="workspace_id,source,source_id,chunk_key"
    ).execute()


def delete_missing(
    workspace_id: str,
    source: str,
    source_id: str,
    current_keys: set[str],
) -> int:
    existing = existing_keys(workspace_id, source, source_id)
    to_delete = existing - current_keys
    if not to_delete:
        return 0
    (
        _get_client()
        .table("documents")
        .delete()
        .eq("workspace_id", workspace_id)
        .eq("source", source)
        .eq("source_id", source_id)
        .in_("chunk_key", list(to_delete))
        .execute()
    )
    return len(to_delete)
