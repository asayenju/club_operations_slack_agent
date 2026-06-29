"""
Retrieval evaluation using a held-out test set (not self-consistency).

Dataset: data/eval_decide_dataset.json
  - 75 train chunks are seeded into Supabase via scripts/seed_eval_data.py
  - 25 test queries are paraphrases of 25 train entries with ground-truth labels.

Metrics per k in {3, 5, 10, 20}:
  recall@k    = fraction of queries whose expected chunk appears in top-k results
  precision@k = fraction of top-k results that are relevant (1/k per hit, else 0)
  MRR         = mean reciprocal rank of the expected chunk

Usage:
    python scripts/eval_retrieval_k.py

Required env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY, WORKSPACE_ID
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import match_documents
from ingestion_api.embeddings import embed_documents

DATASET_PATH = Path(__file__).parent.parent / "data" / "eval_decide_dataset.json"
K_VALUES = [3, 5, 10, 20]
SOURCE = "slack_decide"


def best_k(recall: dict[int, float], threshold: float = 0.80) -> int:
    """Return the smallest k whose recall meets threshold; fall back to the largest k."""
    candidates = [k for k, r in recall.items() if r >= threshold]
    return min(candidates) if candidates else max(recall)


def run_eval() -> None:
    dataset = json.loads(DATASET_PATH.read_text())
    test_cases = dataset["test"]
    n = len(test_cases)
    assert n == 25, f"Expected 25 test cases, got {n}"

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id

    queries = [tc["query"] for tc in test_cases]
    expected_keys = [tc["expected_chunk_key"] for tc in test_cases]

    print(f"Embedding {n} test queries...")
    vectors = embed_documents(queries, input_type="query")

    if len(vectors) != n:
        print(f"VoyageAI returned {len(vectors)} embeddings for {n} queries — aborting.")
        sys.exit(1)

    max_k = max(K_VALUES)
    rows: list[dict] = []

    print(f"\nRunning retrieval at k={max_k} for each query...\n")

    for i, (tc, vector, expected_key) in enumerate(
        zip(test_cases, vectors, expected_keys, strict=True), start=1
    ):
        results = match_documents(
            workspace_id=workspace_id,
            query_embedding=vector,
            limit=max_k,
            sources=[SOURCE],
        )
        returned_keys = [r["chunk_key"] for r in results]

        try:
            rank = returned_keys.index(expected_key) + 1
        except ValueError:
            rank = None

        row: dict = {
            "query": tc["query"],
            "expected_chunk_key": expected_key,
            "rank": rank,
        }
        for k in K_VALUES:
            hit = rank is not None and rank <= k
            row[f"k{k}_hit"] = hit
            row[f"k{k}_precision"] = round(1 / k, 4) if hit else 0.0

        rows.append(row)

        rank_str = f"rank={rank}" if rank else "NOT FOUND"
        hit_str = " ".join(f"k{k}={'✓' if row[f'k{k}_hit'] else '✗'}" for k in K_VALUES)
        print(f"  [{i:02d}/{n}] {hit_str}  {rank_str}")
        print(f"         Q: {tc['query'][:70]}")
        print(f"         → {expected_key}")

    recall = {k: sum(1 for r in rows if r[f"k{k}_hit"]) / n for k in K_VALUES}
    precision = {k: sum(r[f"k{k}_precision"] for r in rows) / n for k in K_VALUES}
    mrr = sum((1 / r["rank"]) for r in rows if r["rank"] is not None) / n

    print(f"\n{'=' * 55}")
    print(f"  EVAL RESULTS  (n={n} test queries, source={SOURCE!r})")
    print(f"{'=' * 55}")
    print(f"  {'k':>4}  {'recall':>8}  {'precision':>10}  {'hits':>5}")
    print(f"  {'-' * 35}")
    for k in K_VALUES:
        hits = sum(1 for r in rows if r[f"k{k}_hit"])
        print(f"  {k:>4}  {recall[k]:>8.2%}  {precision[k]:>10.4f}  {hits:>5}/{n}")
    print(f"  {'MRR':>4}  {mrr:>8.4f}")
    print(f"{'=' * 55}")
    print(f"  Recommended k = {best_k(recall)}")

    misses = [r for r in rows if r["rank"] is None or r["rank"] > max_k]
    if misses:
        print(f"\n  Missed queries ({len(misses)}):")
        for r in misses:
            print(f"    - {r['query'][:65]}")
            print(f"      expected: {r['expected_chunk_key']}")

    output_dir = Path(__file__).parent.parent / "eval_results"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = output_dir / f"eval_{timestamp}.json"
    csv_path = output_dir / f"eval_{timestamp}.csv"

    payload = {
        "timestamp": timestamp,
        "k_values": K_VALUES,
        "source": SOURCE,
        "n_test": n,
        "recall": {str(k): round(v, 4) for k, v in recall.items()},
        "precision": {str(k): round(v, 4) for k, v in precision.items()},
        "mrr": round(mrr, 4),
        "best_k": best_k(recall),
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2))

    fieldnames = (
        ["query", "expected_chunk_key", "rank"]
        + [f"k{k}_hit" for k in K_VALUES]
        + [f"k{k}_precision" for k in K_VALUES]
    )
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  JSON → {json_path}")
    print(f"  CSV  → {csv_path}")


if __name__ == "__main__":
    run_eval()
