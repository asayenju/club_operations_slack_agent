from typing import Any

from ingestion_api.documents_repo import match_documents
from ingestion_api.embeddings import embed_documents
from tools.models import RetrievedChunk


DECIDE_SEARCH_TOOL = {
    "name": "search_decisions",
    "description": (
        "Semantic search over past club /decide statements. "
        "Use for questions about past decisions, votes, or club policies."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language question or topic to search for.",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of chunks to return. Defaults to 5, clamped to 20."
                ),
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


class DocumentSearchError(RuntimeError):
    pass


def search_decisions(
    query: str,
    workspace_id: str,
    limit: int = 5,
) -> list[RetrievedChunk]:
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")

    clamped_limit = min(max(limit, 1), 20)

    # VoyageAI requires input_type="query" for retrieval (vs "document" for storage)
    [vector] = embed_documents([normalized], input_type="query")
    rows = match_documents(workspace_id, vector, limit=clamped_limit, sources=["slack_decide"])

    return [_row_to_chunk(row) for row in rows]


def _row_to_chunk(row: dict[str, Any]) -> RetrievedChunk:
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        import json
        meta = json.loads(meta)
    return RetrievedChunk(
        source=row.get("source", ""),
        text=row.get("content", ""),
        channel_id=row.get("channel_id"),
        author_user_id=row.get("author_id"),
        author_name=meta.get("user_name"),
        channel_name=meta.get("channel_name"),
        metadata={
            "chunk_key": row.get("chunk_key"),
            "similarity": row.get("similarity"),
            "decision_hash": meta.get("decision_hash"),
            "received_at": meta.get("received_at"),
        },
    )
