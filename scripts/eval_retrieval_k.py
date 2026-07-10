"""
Retrieval evaluation using a held-out test set (not self-consistency).

Datasets:
  decide  → data/eval_decide_dataset.json
              75 train chunks seeded via: python scripts/seed_eval_data.py --source decide
              25 test queries are paraphrases of 25 train entries with ground-truth labels.

  knowledge → data/eval_knowledge_dataset.json
              75 train chunks (40 gdoc + 35 gsheet) seeded via:
                python scripts/seed_eval_data.py --source knowledge
              24 regular test queries + 1 no-evidence query (expected_chunk_key=null).

Metrics per k in {3, 5, 10, 20}:
  recall@k    = fraction of queries whose expected chunk appears in top-k results
  precision@k = fraction of top-k results that are relevant (1/k per hit, else 0)
  MRR         = mean reciprocal rank of the expected chunk

No-evidence queries (knowledge eval only):
  A query about a topic absent from the corpus. PASS if best similarity < MIN_SIMILARITY.

Usage:
    python scripts/eval_retrieval_k.py --tool decide
    python scripts/eval_retrieval_k.py --tool knowledge

    # Both in sequence (CI):
    python scripts/eval_retrieval_k.py --tool decide && \\
    python scripts/eval_retrieval_k.py --tool knowledge

Prerequisites:
    1. Seed eval data:
         python scripts/seed_eval_data.py --source decide
         python scripts/seed_eval_data.py --source knowledge
    2. Set env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY, WORKSPACE_ID

No live Slack or Claude required. Supabase and VoyageAI are the only external deps.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.config import get_ingestion_settings
from ingestion_api.documents_repo import match_documents
from ingestion_api.embeddings import embed_documents
from tools.vector_search import DEFAULT_MIN_SIMILARITY

K_VALUES = [3, 5, 10, 20]
MIN_SIMILARITY = DEFAULT_MIN_SIMILARITY  # threshold for no-evidence queries, kept in sync with production

_TOOL_CONFIG = {
    "decide": {
        "dataset": Path(__file__).parent.parent / "data" / "eval_decide_dataset.json",
        "sources": ["slack_decide"],
        "n_test": 25,
    },
    "knowledge": {
        "dataset": Path(__file__).parent.parent / "data" / "eval_knowledge_dataset.json",
        "sources": ["gdoc", "gsheet"],
        "n_test": 25,
    },
}


def best_k(recall: dict[int, float], threshold: float = 0.80) -> int:
    """Return the smallest k whose recall meets threshold; fall back to the largest k."""
    candidates = [k for k, r in recall.items() if r >= threshold]
    return min(candidates) if candidates else max(recall)


def run_eval(tool: str, output_dir: Path | None = None) -> None:
    cfg = _TOOL_CONFIG[tool]
    dataset = json.loads(cfg["dataset"].read_text())
    all_test_cases = dataset["test"]
    assert len(all_test_cases) == cfg["n_test"], (
        f"Expected {cfg['n_test']} test cases, got {len(all_test_cases)}"
    )

    regular_cases = [tc for tc in all_test_cases if not tc.get("no_evidence")]
    no_evidence_cases = [tc for tc in all_test_cases if tc.get("no_evidence")]
    n = len(regular_cases)

    settings = get_ingestion_settings()
    workspace_id = settings.required_workspace_id

    all_queries = [tc["query"] for tc in all_test_cases]
    print(f"Embedding {len(all_queries)} test queries (tool={tool!r})...")
    all_vectors = embed_documents(all_queries, input_type="query")

    if len(all_vectors) != len(all_test_cases):
        print(
            f"VoyageAI returned {len(all_vectors)} embeddings for "
            f"{len(all_test_cases)} queries — aborting."
        )
        sys.exit(1)

    regular_vectors = all_vectors[: len(regular_cases)]
    no_evidence_vectors = all_vectors[len(regular_cases):]

    max_k = max(K_VALUES)
    rows: list[dict] = []

    print(f"\nRunning retrieval at k={max_k} for {n} regular queries...\n")

    for i, (tc, vector) in enumerate(
        zip(regular_cases, regular_vectors, strict=True), start=1
    ):
        expected_key = tc["expected_chunk_key"]
        results = match_documents(
            workspace_id=workspace_id,
            query_embedding=vector,
            limit=max_k,
            sources=cfg["sources"],
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
    print(f"  EVAL RESULTS  (n={n} queries, tool={tool!r}, sources={cfg['sources']})")
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

    no_evidence_results: list[dict] = []
    if no_evidence_cases:
        print(f"\n  NO-EVIDENCE CASES  (threshold={MIN_SIMILARITY})")
        print(f"  {'-' * 45}")
        for i, (tc, vector) in enumerate(
            zip(no_evidence_cases, no_evidence_vectors, strict=True), start=1
        ):
            results = match_documents(
                workspace_id=workspace_id,
                query_embedding=vector,
                limit=max_k,
                sources=cfg["sources"],
            )
            best_sim = max((r.get("similarity") or 0.0 for r in results), default=0.0)
            passed = best_sim < MIN_SIMILARITY
            status = "PASS" if passed else "FAIL"
            no_evidence_results.append(
                {"query": tc["query"], "best_similarity": round(best_sim, 4), "passed": passed}
            )
            print(
                f"  [{i}/{len(no_evidence_cases)}] {status}  "
                f"best_sim={best_sim:.4f}  {tc['query'][:55]!r}"
            )

    output_dir = output_dir or Path(__file__).parent.parent / "eval_results"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = output_dir / f"eval_{tool}_{timestamp}.json"
    csv_path = output_dir / f"eval_{tool}_{timestamp}.csv"

    payload = {
        "timestamp": timestamp,
        "tool": tool,
        "sources": cfg["sources"],
        "k_values": K_VALUES,
        "n_test": n,
        "recall": {str(k): round(v, 4) for k, v in recall.items()},
        "precision": {str(k): round(v, 4) for k, v in precision.items()},
        "mrr": round(mrr, 4),
        "best_k": best_k(recall),
        "no_evidence_results": no_evidence_results,
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run retrieval evaluation for decide or knowledge tools."
    )
    parser.add_argument(
        "--tool",
        choices=["decide", "knowledge"],
        default="decide",
        help="Which retrieval tool to evaluate (default: decide)",
    )
    args = parser.parse_args()
    run_eval(args.tool)


if __name__ == "__main__":
    main()
