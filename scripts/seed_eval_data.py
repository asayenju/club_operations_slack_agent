"""
Seed the eval decide dataset into Supabase (train split only).

Clears any existing eval:train:* chunks for this workspace, then
ingests the 75 train entries from data/eval_decide_dataset.json.

Usage:
    python scripts/seed_eval_data.py

Required env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY, WORKSPACE_ID
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import get_supabase_client, upsert_chunks
from ingestion_api.embeddings import embed_documents, to_pgvector


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

DATASET_PATH = Path(__file__).parent.parent / "data" / "eval_decide_dataset.json"
SOURCE = "slack_decide"
EVAL_SOURCE_ID = "eval_dataset_v1"


def clear_eval_chunks(workspace_id: str) -> int:
    client = get_supabase_client()
    resp = (
        client.table("documents")
        .delete()
        .eq("workspace_id", workspace_id)
        .eq("source", SOURCE)
        .eq("source_id", EVAL_SOURCE_ID)
        .execute()
    )
    deleted = len(resp.data or [])
    print(f"Cleared {deleted} existing eval chunks.")
    return deleted


def seed(workspace_id: str, train_chunks: list[dict]) -> None:
    texts = [c["content"] for c in train_chunks]
    print(f"Embedding {len(texts)} train chunks...")
    vectors = embed_documents(texts)

    if len(vectors) != len(train_chunks):
        print(f"VoyageAI returned {len(vectors)} embeddings for {len(train_chunks)} texts — aborting.")
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for chunk, vector in zip(train_chunks, vectors, strict=True):
        rows.append({
            "workspace_id": workspace_id,
            "source": SOURCE,
            "source_id": EVAL_SOURCE_ID,
            "chunk_key": chunk["chunk_key"],
            "content": chunk["content"],
            "content_hash": content_hash(chunk["content"]),
            "metadata": {"topic": chunk.get("topic", ""), "eval": True},
            "embedding": to_pgvector(vector),
            "updated_at": now,
        })

    upsert_chunks(rows)
    print(f"Seeded {len(rows)} train chunks into Supabase.")


def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text())
    train_chunks = dataset["train"]
    assert len(train_chunks) == 75, f"Expected 75 train chunks, got {len(train_chunks)}"

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id

    print(f"Workspace: {workspace_id}")
    clear_eval_chunks(workspace_id)
    seed(workspace_id, train_chunks)
    print("Done.")


if __name__ == "__main__":
    main()
