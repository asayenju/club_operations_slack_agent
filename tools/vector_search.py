from typing import Any

from ingestion_api.documents_repo import match_documents
from ingestion_api.embeddings import embed_documents
from tools.models import Citation, Evidence


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

KNOWLEDGE_SEARCH_TOOL = {
    "name": "search_knowledge",
    "description": (
        "Semantic search over ingested Google Docs and Google Sheets. "
        "Use for questions about club documents, budgets, rosters, meeting notes, or policies."
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


DEFAULT_MIN_SIMILARITY = 0.70  # aligns with MIN_SIMILARITY in scripts/eval_retrieval_k.py


class DocumentSearchError(RuntimeError):
    pass


def search_decisions(
    query: str,
    workspace_id: str,
    limit: int = 5,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[Evidence]:
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")

    clamped_limit = min(max(limit, 1), 20)

    # VoyageAI requires input_type="query" for retrieval (vs "document" for storage)
    [vector] = embed_documents([normalized], input_type="query")
    rows = match_documents(workspace_id, vector, limit=clamped_limit, sources=["slack_decide"])

    results = [_row_to_evidence(row) for row in rows]
    return [ev for ev in results if ev.similarity is not None and ev.similarity >= min_similarity]


def search_knowledge(
    query: str,
    workspace_id: str,
    limit: int = 5,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[Evidence]:
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")

    clamped_limit = min(max(limit, 1), 20)

    [vector] = embed_documents([normalized], input_type="query")
    rows = match_documents(workspace_id, vector, limit=clamped_limit, sources=["gdoc", "gsheet"])

    results = [_row_to_evidence(row) for row in rows]
    return [ev for ev in results if ev.similarity is not None and ev.similarity >= min_similarity]


def _build_citation(source: str, row: dict[str, Any], meta: dict[str, Any]) -> Citation:
    if source == "slack_decide":
        channel = meta.get("channel_name") or row.get("channel_id") or "Slack"
        received_at = meta.get("received_at", "")
        date = received_at[:10] if received_at else "unknown date"
        label = f"#{channel} — {date}"
    elif source == "gdoc":
        title = meta.get("title", "")
        heading = meta.get("heading_path", "") or meta.get("heading", "")
        if title and heading:
            label = f"{title} › {heading}"
        elif title:
            label = title
        else:
            label = "Google Doc"
    elif source == "gsheet":
        title = meta.get("title", "")
        sheet_name = meta.get("sheet_name", "")
        if title and sheet_name:
            label = f"{title} › {sheet_name}"
        elif title:
            label = title
        else:
            label = "Google Sheet"
    else:
        label = source or "Unknown"

    return Citation(source=source, label=label)


def _row_to_evidence(row: dict[str, Any]) -> Evidence:
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        import json
        meta = json.loads(meta)

    source = row.get("source", "")
    citation = _build_citation(source, row, meta)

    author: str | None = None
    timestamp: str | None = None

    if source == "slack_decide":
        author = meta.get("user_name") or row.get("author_id") or None
        timestamp = meta.get("received_at")
    elif source in ("gdoc", "gsheet"):
        timestamp = meta.get("modified_time")

    return Evidence(
        source=source,
        text=row.get("content", ""),
        citation=citation,
        similarity=row.get("similarity"),
        score=None,
        timestamp=timestamp,
        author=author,
        metadata={
            "chunk_key": row.get("chunk_key"),
            "decision_hash": meta.get("decision_hash"),
        },
    )
