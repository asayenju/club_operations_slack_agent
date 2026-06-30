"""
Seed eval datasets into Supabase (train split only).

For --source decide:
  Clears eval_dataset_v1 chunks, then seeds 75 train entries from
  data/eval_decide_dataset.json as source="slack_decide".

For --source knowledge:
  Clears eval_knowledge_v1 chunks, then seeds 75 train entries from
  data/eval_knowledge_dataset.json preserving each chunk's source field
  (either "gdoc" or "gsheet") and its metadata dict.

Usage:
    python scripts/seed_eval_data.py --source decide
    python scripts/seed_eval_data.py --source knowledge

Required env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY, WORKSPACE_ID
"""

import argparse
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


_SOURCE_CONFIG = {
    "decide": {
        "dataset": Path(__file__).parent.parent / "data" / "eval_decide_dataset.json",
        "source": "slack_decide",
        "source_id": "eval_dataset_v1",
        "n_train": 75,
    },
    "knowledge": {
        "dataset": Path(__file__).parent.parent / "data" / "eval_knowledge_dataset.json",
        "source": None,  # each chunk carries its own source field
        "source_id": "eval_knowledge_v1",
        "n_train": 75,
    },
}


def clear_eval_chunks(workspace_id: str, source_id: str, source: str | None) -> int:
    client = get_supabase_client()
    query = (
        client.table("documents")
        .delete()
        .eq("workspace_id", workspace_id)
        .eq("source_id", source_id)
    )
    if source is not None:
        query = query.eq("source", source)
    resp = query.execute()
    deleted = len(resp.data or [])
    print(f"Cleared {deleted} existing eval chunks (source_id={source_id!r}).")
    return deleted


def seed(workspace_id: str, train_chunks: list[dict], source_id: str, default_source: str | None) -> None:
    texts = [c["content"] for c in train_chunks]
    print(f"Embedding {len(texts)} train chunks...")
    vectors = embed_documents(texts)

    if len(vectors) != len(train_chunks):
        print(
            f"VoyageAI returned {len(vectors)} embeddings for "
            f"{len(train_chunks)} texts — aborting."
        )
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for chunk, vector in zip(train_chunks, vectors, strict=True):
        source = default_source if default_source is not None else chunk["source"]
        chunk_metadata = chunk.get("metadata") or {}
        rows.append({
            "workspace_id": workspace_id,
            "source": source,
            "source_id": source_id,
            "chunk_key": chunk["chunk_key"],
            "content": chunk["content"],
            "content_hash": content_hash(chunk["content"]),
            "metadata": {**chunk_metadata, "topic": chunk.get("topic", ""), "eval": True},
            "embedding": to_pgvector(vector),
            "updated_at": now,
        })

    upsert_chunks(rows)
    print(f"Seeded {len(rows)} train chunks into Supabase.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed eval data into Supabase.")
    parser.add_argument(
        "--source",
        choices=["decide", "knowledge"],
        default="decide",
        help="Which dataset to seed (default: decide)",
    )
    args = parser.parse_args()

    cfg = _SOURCE_CONFIG[args.source]
    dataset = json.loads(cfg["dataset"].read_text())
    train_chunks = dataset["train"]
    assert len(train_chunks) == cfg["n_train"], (
        f"Expected {cfg['n_train']} train chunks, got {len(train_chunks)}"
    )

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id

    print(f"Workspace: {workspace_id}  source={args.source!r}")
    clear_eval_chunks(workspace_id, cfg["source_id"], cfg["source"])
    seed(workspace_id, train_chunks, cfg["source_id"], cfg["source"])
    print("Done.")


if __name__ == "__main__":
    main()
