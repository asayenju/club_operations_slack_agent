import hashlib
import re
import sys
from datetime import datetime, timezone
from typing import Any, TypedDict

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import (
    delete_missing,
    existing_keys,
    upsert_chunks,
)
from ingestion_api.embeddings import embed_documents, to_pgvector
from ingestion_api.google_docs import DocumentSection, extract_sections, fetch_doc


MAX_CHARS = 6000
GOOGLE_DOC_SOURCE = "gdoc"


class DocumentChunk(TypedDict):
    chunk_key: str
    content: str
    content_hash: str
    heading: str
    heading_path: str


class IngestionResult(TypedDict):
    doc_id: str
    title: str
    inserted_or_changed: int
    unchanged: int
    deleted: int
    total: int


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be positive")

    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= limit:
        return [normalized]

    parts: list[str] = []
    current = ""

    for paragraph in re.split(r"\n\s*\n", normalized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.extend(
                paragraph[start : start + limit]
                for start in range(0, len(paragraph), limit)
            )
        elif current and len(current) + len(paragraph) + 2 > limit:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph

    if current:
        parts.append(current)

    return parts


def build_chunks(sections: list[DocumentSection]) -> list[DocumentChunk]:
    chunks_by_key: dict[str, DocumentChunk] = {}

    for section in sections:
        for part in split_text(section["text"]):
            digest = content_hash(part)
            key = f'{section["heading_path"]}:{digest[:12]}'
            chunks_by_key[key] = {
                "chunk_key": key,
                "content": part,
                "content_hash": digest,
                "heading": section["heading"],
                "heading_path": section["heading_path"],
            }

    return list(chunks_by_key.values())


def ingest_doc(doc_id: str) -> IngestionResult:
    normalized_doc_id = doc_id.strip()
    if not normalized_doc_id:
        raise ValueError("doc_id must not be empty")

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id
    title, sections = extract_sections(fetch_doc(normalized_doc_id))
    chunks = build_chunks(sections)

    seen_keys = existing_keys(workspace_id, GOOGLE_DOC_SOURCE, normalized_doc_id)
    current_keys = {chunk["chunk_key"] for chunk in chunks}
    changed_chunks = [
        chunk for chunk in chunks if chunk["chunk_key"] not in seen_keys
    ]
    now = datetime.now(timezone.utc).isoformat()

    if changed_chunks:
        vectors = embed_documents(
            [chunk["content"] for chunk in changed_chunks]
        )
        if len(vectors) != len(changed_chunks):
            raise RuntimeError(
                "Voyage returned a different number of embeddings than requested"
            )

        rows: list[dict[str, Any]] = []
        for chunk, vector in zip(changed_chunks, vectors, strict=True):
            rows.append(
                {
                    "workspace_id": workspace_id,
                    "source": GOOGLE_DOC_SOURCE,
                    "source_id": normalized_doc_id,
                    "chunk_key": chunk["chunk_key"],
                    "content": chunk["content"],
                    "content_hash": chunk["content_hash"],
                    "metadata": {
                        "title": title,
                        "heading": chunk["heading"],
                        "heading_path": chunk["heading_path"],
                        "last_ingested": now,
                    },
                    "embedding": to_pgvector(vector),
                    "updated_at": now,
                }
            )
        upsert_chunks(rows)

    deleted = delete_missing(
        workspace_id,
        GOOGLE_DOC_SOURCE,
        normalized_doc_id,
        current_keys,
    )
    result: IngestionResult = {
        "doc_id": normalized_doc_id,
        "title": title,
        "inserted_or_changed": len(changed_chunks),
        "unchanged": len(chunks) - len(changed_chunks),
        "deleted": deleted,
        "total": len(chunks),
    }
    print(
        f"[{normalized_doc_id}] '{title}': "
        f"{result['inserted_or_changed']} new/changed, "
        f"{result['unchanged']} unchanged, "
        f"{result['deleted']} deleted, "
        f"{result['total']} total"
    )
    return result


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m ingestion_api.ingest_docs <google_doc_id>")
        raise SystemExit(1)
    ingest_doc(sys.argv[1])


if __name__ == "__main__":
    main()
