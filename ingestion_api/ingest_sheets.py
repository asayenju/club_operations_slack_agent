import hashlib
import re
import sys
from datetime import datetime, timezone
from typing import Any, TypedDict

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import delete_missing, existing_keys, upsert_chunks
from ingestion_api.embeddings import embed_documents, to_pgvector
from ingestion_api.google_docs import GOOGLE_READ_SCOPES

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


GSHEET_SOURCE = "gsheet"
MAX_ROWS_PER_BATCH = 200


class SheetChunk(TypedDict):
    chunk_key: str
    content: str
    content_hash: str
    sheet_name: str
    row_index: int


class SheetIngestionResult(TypedDict):
    spreadsheet_id: str
    title: str
    inserted_or_changed: int
    unchanged: int
    deleted: int
    total: int


def get_sheets_service() -> Any:
    token_path = get_ingestion_settings().google_token_path
    if not token_path.exists():
        raise FileNotFoundError(
            f"Google OAuth token not found at {token_path}. "
            "Run: python -m tools.google_auth_bootstrap"
        )
    credentials = Credentials.from_authorized_user_file(str(token_path), GOOGLE_READ_SCOPES)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _row_to_text(headers: list[str], values: list[str]) -> str:
    """Format a spreadsheet row as 'Header: value | Header: value ...'"""
    parts = []
    for header, value in zip(headers, values):
        header = header.strip()
        value = value.strip()
        if header and value:
            parts.append(f"{header}: {value}")
    return " | ".join(parts)


def fetch_sheet_data(spreadsheet_id: str) -> tuple[str, list[tuple[str, list[list[str]]]]]:
    """
    Returns (spreadsheet_title, [(sheet_name, rows), ...]).
    rows[0] is treated as the header row.
    """
    service = get_sheets_service()
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    title = str(spreadsheet.get("properties", {}).get("title") or "untitled").strip()
    sheet_names = [
        s["properties"]["title"]
        for s in spreadsheet.get("sheets", [])
    ]

    sheets_data: list[tuple[str, list[list[str]]]] = []
    for sheet_name in sheet_names:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_name)
            .execute()
        )
        rows: list[list[str]] = result.get("values", [])
        sheets_data.append((sheet_name, rows))

    return title, sheets_data


def build_chunks(
    title: str,
    sheets_data: list[tuple[str, list[list[str]]]],
    spreadsheet_id: str,
) -> list[SheetChunk]:
    chunks: list[SheetChunk] = []

    for sheet_name, rows in sheets_data:
        if len(rows) < 2:
            continue

        headers = [str(h) for h in rows[0]]
        max_cols = len(headers)

        for row_idx, row in enumerate(rows[1:], start=1):
            padded = list(row) + [""] * (max_cols - len(row))
            content = _row_to_text(headers, padded[:max_cols])
            if not content:
                continue

            digest = _content_hash(content)
            safe_sheet = re.sub(r"[^a-zA-Z0-9_-]", "_", sheet_name)
            chunk_key = f"{spreadsheet_id}:{safe_sheet}:{row_idx:04d}"

            chunks.append({
                "chunk_key": chunk_key,
                "content": content,
                "content_hash": digest,
                "sheet_name": sheet_name,
                "row_index": row_idx,
            })

    return chunks


def ingest_sheet(spreadsheet_id: str) -> SheetIngestionResult:
    normalized_id = spreadsheet_id.strip()
    if not normalized_id:
        raise ValueError("spreadsheet_id must not be empty")

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id

    title, sheets_data = fetch_sheet_data(normalized_id)
    chunks = build_chunks(title, sheets_data, normalized_id)

    seen_keys = existing_keys(workspace_id, GSHEET_SOURCE, normalized_id)
    current_keys = {chunk["chunk_key"] for chunk in chunks}
    changed_chunks = [c for c in chunks if c["chunk_key"] not in seen_keys]

    now = datetime.now(timezone.utc).isoformat()

    if changed_chunks:
        vectors = embed_documents([c["content"] for c in changed_chunks])
        if len(vectors) != len(changed_chunks):
            raise RuntimeError("Voyage returned a different number of embeddings than requested")

        rows: list[dict[str, Any]] = []
        for chunk, vector in zip(changed_chunks, vectors, strict=True):
            rows.append({
                "workspace_id": workspace_id,
                "source": GSHEET_SOURCE,
                "source_id": normalized_id,
                "chunk_key": chunk["chunk_key"],
                "content": chunk["content"],
                "content_hash": chunk["content_hash"],
                "metadata": {
                    "title": title,
                    "sheet_name": chunk["sheet_name"],
                    "row_index": chunk["row_index"],
                    "last_ingested": now,
                },
                "embedding": to_pgvector(vector),
                "updated_at": now,
            })
        upsert_chunks(rows)

    deleted = delete_missing(workspace_id, GSHEET_SOURCE, normalized_id, current_keys)

    result: SheetIngestionResult = {
        "spreadsheet_id": normalized_id,
        "title": title,
        "inserted_or_changed": len(changed_chunks),
        "unchanged": len(chunks) - len(changed_chunks),
        "deleted": deleted,
        "total": len(chunks),
    }
    print(
        f"[{normalized_id}] '{title}': "
        f"{result['inserted_or_changed']} new/changed, "
        f"{result['unchanged']} unchanged, "
        f"{result['deleted']} deleted, "
        f"{result['total']} total"
    )
    return result


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m ingestion_api.ingest_sheets <google_spreadsheet_id>")
        raise SystemExit(1)
    ingest_sheet(sys.argv[1])


if __name__ == "__main__":
    main()
