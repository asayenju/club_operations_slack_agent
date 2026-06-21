import hashlib
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import delete_missing, existing_keys, upsert_chunks
from ingestion_api.driveSheet import list_all_sheets
from ingestion_api.embeddings import embed_documents, to_pgvector
from ingestion_api.google_sheets import fetch_sheet_rows, row_to_text

"""
document_repo and embedding will be called from Amen's branch
"""


GOOGLE_SHEET_SOURCE = "gsheet"


class SheetChunk(TypedDict):
    chunk_key: str
    content: str
    content_hash: str
    row_index: int


class IngestionResult(TypedDict):
    sheet_id: str
    inserted_or_changed: int
    unchanged: int
    deleted: int
    total: int


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_chunks(rows: list[dict[str, Any]]) -> list[SheetChunk]:
    """Converts each non-empty row into a chunk keyed by its content hash."""
    chunks: list[SheetChunk] = []
    for i, row in enumerate(rows):
        text = row_to_text(row)
        if not text.strip():
            continue
        digest = content_hash(text)
        chunks.append({
            "chunk_key": f"row_{i}:{digest[:12]}",
            "content": text,
            "content_hash": digest,
            "row_index": i,
        })
    return chunks


def ingest_all_sheets() -> list[IngestionResult]:
    """Discovers all accessible Google Sheets and ingests each one."""
    sheets = list_all_sheets()
    return [ingest_sheet(sheet["sheet_id"]) for sheet in sheets]


def ingest_sheet(sheet_id: str) -> IngestionResult:
    """Incrementally ingests a Google Sheet — only embeds rows that are new or changed."""
    normalized_id = sheet_id.strip()
    if not normalized_id:
        raise ValueError("sheet_id must not be empty")

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id

    rows = fetch_sheet_rows(normalized_id)
    chunks = build_chunks(rows)

    seen_keys = existing_keys(workspace_id, GOOGLE_SHEET_SOURCE, normalized_id)
    current_keys = {chunk["chunk_key"] for chunk in chunks}
    changed_chunks = [chunk for chunk in chunks if chunk["chunk_key"] not in seen_keys]

    now = datetime.now(timezone.utc).isoformat()

    if changed_chunks:
        vectors = embed_documents([chunk["content"] for chunk in changed_chunks])
        if len(vectors) != len(changed_chunks):
            raise RuntimeError(
                "Voyage returned a different number of embeddings than requested"
            )

        rows_to_insert: list[dict[str, Any]] = []
        for chunk, vector in zip(changed_chunks, vectors, strict=True):
            rows_to_insert.append({
                "workspace_id": workspace_id,
                "source": GOOGLE_SHEET_SOURCE,
                "source_id": normalized_id,
                "chunk_key": chunk["chunk_key"],
                "content": chunk["content"],
                "content_hash": chunk["content_hash"],
                "metadata": {
                    "row_index": chunk["row_index"],
                    "last_ingested": now,
                },
                "embedding": to_pgvector(vector),
                "updated_at": now,
            })
        upsert_chunks(rows_to_insert)

    deleted = delete_missing(workspace_id, GOOGLE_SHEET_SOURCE, normalized_id, current_keys)

    result: IngestionResult = {
        "sheet_id": normalized_id,
        "inserted_or_changed": len(changed_chunks),
        "unchanged": len(chunks) - len(changed_chunks),
        "deleted": deleted,
        "total": len(chunks),
    }
    print(
        f"[{normalized_id}]: "
        f"{result['inserted_or_changed']} new/changed, "
        f"{result['unchanged']} unchanged, "
        f"{result['deleted']} deleted, "
        f"{result['total']} total"
    )
    return result
