import hashlib
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import replace_source_chunks
from ingestion_api.embeddings import embed_documents, to_pgvector
from ingestion_api.google_sheets import fetch_sheet_rows, row_to_text


GOOGLE_SHEET_SOURCE = "gsheet"


class SheetChunk(TypedDict):
    chunk_key: str
    content: str
    content_hash: str
    row_index: int
    tab_id: str
    tab_name: str


class IngestionResult(TypedDict):
    sheet_id: str
    inserted_or_changed: int
    unchanged: int
    deleted: int
    total: int


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_chunks(rows: list[dict[str, Any]]) -> list[SheetChunk]:
    """Use content identity; row_index remains ordering metadata only."""
    chunks: list[SheetChunk] = []
    duplicate_counts: dict[tuple[str, str], int] = {}

    for row_index, row in enumerate(rows):
        tab_id = str(row.get("__tab_id__", "0"))
        tab_name = str(row.get("__tab_name__", "Sheet1"))
        content = row_to_text(
            {
                key: value
                for key, value in row.items()
                if key not in ("__tab_id__", "__tab_name__")
            }
        )
        if not content.strip():
            continue

        digest = content_hash(content)
        duplicate_key = (tab_id, digest)
        duplicate_number = duplicate_counts.get(duplicate_key, 0)
        duplicate_counts[duplicate_key] = duplicate_number + 1
        chunks.append(
            {
                "chunk_key": f"{tab_id}:{digest[:12]}:{duplicate_number}",
                "content": content,
                "content_hash": digest,
                "row_index": row_index,
                "tab_id": tab_id,
                "tab_name": tab_name,
            }
        )

    return chunks


def ingest_sheet(sheet_id: str) -> IngestionResult:
    """Fully replace a changed Sheet after embeddings are ready."""
    normalized_id = sheet_id.strip()
    if not normalized_id:
        raise ValueError("sheet_id must not be empty")

    workspace_id = get_ingestion_settings().required_workspace_id
    chunks = build_chunks(fetch_sheet_rows(normalized_id))
    vectors = embed_documents([chunk["content"] for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(
            "Voyage returned a different number of embeddings than requested"
        )

    now = datetime.now(timezone.utc).isoformat()
    rows_to_insert: list[dict[str, Any]] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        rows_to_insert.append(
            {
                "workspace_id": workspace_id,
                "source": GOOGLE_SHEET_SOURCE,
                "source_id": normalized_id,
                "chunk_key": chunk["chunk_key"],
                "content": chunk["content"],
                "content_hash": chunk["content_hash"],
                "metadata": {
                    "row_index": chunk["row_index"],
                    "tab_id": chunk["tab_id"],
                    "tab_name": chunk["tab_name"],
                    "last_ingested": now,
                },
                "embedding": to_pgvector(vector),
                "updated_at": now,
            }
        )

    deleted = replace_source_chunks(
        workspace_id,
        GOOGLE_SHEET_SOURCE,
        normalized_id,
        rows_to_insert,
    )
    result: IngestionResult = {
        "sheet_id": normalized_id,
        "inserted_or_changed": len(chunks),
        "unchanged": 0,
        "deleted": deleted,
        "total": len(chunks),
    }
    print(
        f"[{normalized_id}]: {len(chunks)} inserted, "
        f"{deleted} replaced, {len(chunks)} total"
    )
    return result
