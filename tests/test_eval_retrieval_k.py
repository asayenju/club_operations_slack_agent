import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_retrieval_k import MIN_SIMILARITY, best_k, run_eval


# ── best_k ────────────────────────────────────────────────────────────────────

def test_best_k_returns_smallest_k_meeting_threshold():
    recall = {3: 0.60, 5: 0.80, 10: 0.90, 20: 1.00}
    assert best_k(recall) == 5


def test_best_k_returns_smallest_when_multiple_meet_threshold():
    recall = {3: 0.85, 5: 0.90, 10: 0.95, 20: 1.00}
    assert best_k(recall) == 3


def test_best_k_falls_back_to_largest_k_when_none_meet_threshold():
    recall = {3: 0.50, 5: 0.60, 10: 0.70, 20: 0.79}
    assert best_k(recall) == 20


def test_best_k_exact_threshold_qualifies():
    recall = {3: 0.79, 5: 0.80, 10: 0.90}
    assert best_k(recall) == 5


def test_best_k_custom_threshold():
    recall = {3: 0.60, 5: 0.70, 10: 0.95, 20: 1.00}
    assert best_k(recall, threshold=0.95) == 10


def test_best_k_all_qualify_returns_minimum():
    recall = {3: 1.00, 5: 1.00, 10: 1.00, 20: 1.00}
    assert best_k(recall) == 3


def test_best_k_single_k_meets_threshold():
    recall = {20: 0.90}
    assert best_k(recall) == 20


def test_best_k_single_k_misses_threshold_still_returns_it():
    recall = {5: 0.50}
    assert best_k(recall) == 5


# ── dataset integrity ──────────────────────────────────────────────────────────

DATASET_PATH = Path(__file__).parent.parent / "data" / "eval_decide_dataset.json"


@pytest.fixture(scope="module")
def dataset():
    import json
    return json.loads(DATASET_PATH.read_text())


def test_dataset_has_correct_split_sizes(dataset):
    assert len(dataset["train"]) == 75
    assert len(dataset["test"]) == 25


def test_train_chunk_keys_are_unique(dataset):
    keys = [c["chunk_key"] for c in dataset["train"]]
    assert len(keys) == len(set(keys)), "Duplicate chunk_keys in train split"


def test_test_expected_keys_all_exist_in_train(dataset):
    train_keys = {c["chunk_key"] for c in dataset["train"]}
    for tc in dataset["test"]:
        assert tc["expected_chunk_key"] in train_keys, (
            f"Test case expected_chunk_key {tc['expected_chunk_key']!r} "
            "not found in train split"
        )


def test_test_queries_are_not_exact_matches_of_train_content(dataset):
    train_content = {c["content"].lower() for c in dataset["train"]}
    for tc in dataset["test"]:
        assert tc["query"].lower() not in train_content, (
            f"Test query is an exact copy of a train chunk: {tc['query']!r}"
        )


def test_test_expected_keys_are_unique(dataset):
    keys = [tc["expected_chunk_key"] for tc in dataset["test"]]
    assert len(keys) == len(set(keys)), "Duplicate expected_chunk_keys in test split — each train entry should appear at most once"


def test_all_train_chunks_have_required_fields(dataset):
    for chunk in dataset["train"]:
        assert "chunk_key" in chunk
        assert "content" in chunk
        assert chunk["content"].strip(), f"Empty content for {chunk['chunk_key']}"


def test_all_test_cases_have_required_fields(dataset):
    for tc in dataset["test"]:
        assert "query" in tc
        assert "expected_chunk_key" in tc
        assert tc["query"].strip(), "Empty query in test case"


# ── knowledge dataset integrity ───────────────────────────────────────────────

KNOWLEDGE_DATASET_PATH = Path(__file__).parent.parent / "data" / "eval_knowledge_dataset.json"


@pytest.fixture(scope="module")
def knowledge_dataset():
    return json.loads(KNOWLEDGE_DATASET_PATH.read_text())


@pytest.fixture(scope="module")
def knowledge_regular(knowledge_dataset):
    return [tc for tc in knowledge_dataset["test"] if not tc.get("no_evidence")]


@pytest.fixture(scope="module")
def knowledge_no_evidence(knowledge_dataset):
    return [tc for tc in knowledge_dataset["test"] if tc.get("no_evidence")]


def test_knowledge_dataset_has_correct_split_sizes(knowledge_dataset):
    assert len(knowledge_dataset["train"]) == 75
    assert len(knowledge_dataset["test"]) == 25


def test_knowledge_train_chunk_keys_are_unique(knowledge_dataset):
    keys = [c["chunk_key"] for c in knowledge_dataset["train"]]
    assert len(keys) == len(set(keys))


def test_knowledge_train_chunks_have_valid_source(knowledge_dataset):
    valid = {"gdoc", "gsheet"}
    for chunk in knowledge_dataset["train"]:
        assert chunk.get("source") in valid, (
            f"chunk {chunk['chunk_key']} has invalid source {chunk.get('source')!r}"
        )


def test_knowledge_train_has_both_gdoc_and_gsheet(knowledge_dataset):
    sources = {c["source"] for c in knowledge_dataset["train"]}
    assert "gdoc" in sources
    assert "gsheet" in sources


def test_knowledge_gdoc_chunks_have_title_in_metadata(knowledge_dataset):
    for chunk in knowledge_dataset["train"]:
        if chunk["source"] == "gdoc":
            meta = chunk.get("metadata", {})
            assert meta.get("title"), (
                f"gdoc chunk {chunk['chunk_key']} missing metadata.title"
            )


def test_knowledge_gsheet_chunks_have_title_in_metadata(knowledge_dataset):
    for chunk in knowledge_dataset["train"]:
        if chunk["source"] == "gsheet":
            meta = chunk.get("metadata", {})
            assert meta.get("title"), (
                f"gsheet chunk {chunk['chunk_key']} missing metadata.title"
            )


def test_knowledge_regular_expected_keys_exist_in_train(knowledge_dataset, knowledge_regular):
    train_keys = {c["chunk_key"] for c in knowledge_dataset["train"]}
    for tc in knowledge_regular:
        assert tc["expected_chunk_key"] in train_keys, (
            f"expected_chunk_key {tc['expected_chunk_key']!r} not in train"
        )


def test_knowledge_regular_expected_keys_are_unique(knowledge_regular):
    keys = [tc["expected_chunk_key"] for tc in knowledge_regular]
    assert len(keys) == len(set(keys)), "Duplicate expected_chunk_keys in regular test cases"


def test_knowledge_has_exactly_one_no_evidence_case(knowledge_no_evidence):
    assert len(knowledge_no_evidence) == 1


def test_knowledge_no_evidence_case_has_null_expected_key(knowledge_no_evidence):
    assert knowledge_no_evidence[0]["expected_chunk_key"] is None


def test_knowledge_queries_are_not_exact_matches_of_train_content(knowledge_dataset, knowledge_regular):
    train_content = {c["content"].lower() for c in knowledge_dataset["train"]}
    for tc in knowledge_regular:
        assert tc["query"].lower() not in train_content, (
            f"Test query is an exact copy of train content: {tc['query']!r}"
        )


def test_knowledge_covers_gdoc_and_gsheet_test_queries(knowledge_regular):
    source_types = {tc.get("source_type") for tc in knowledge_regular}
    assert "gdoc" in source_types
    assert "gsheet" in source_types


# ── no-evidence threshold logic ───────────────────────────────────────────────

def _no_evidence_passed(results: list[dict]) -> bool:
    best_sim = max((r.get("similarity") or 0.0 for r in results), default=0.0)
    return best_sim < MIN_SIMILARITY


def test_no_evidence_passes_when_best_similarity_below_threshold():
    results = [{"similarity": 0.40}, {"similarity": 0.55}]
    assert _no_evidence_passed(results) is True


def test_no_evidence_fails_when_best_similarity_at_or_above_threshold():
    results = [{"similarity": 0.70}, {"similarity": 0.85}]
    assert _no_evidence_passed(results) is False


def test_no_evidence_passes_when_results_empty():
    # empty → default=0.0 → 0.0 < 0.70 → PASS
    assert _no_evidence_passed([]) is True


def test_no_evidence_fails_at_exact_threshold():
    results = [{"similarity": MIN_SIMILARITY}]
    assert _no_evidence_passed(results) is False


def test_no_evidence_handles_none_similarity():
    # similarity=None in row should be treated as 0.0 (via "or 0.0")
    results = [{"similarity": None}]
    assert _no_evidence_passed(results) is True


# ── run_eval("knowledge") integration ─────────────────────────────────────────

FAKE_VECTOR = [0.1] * 1024


class _FakeSettings:
    required_workspace_id = "T_TEST"


def _make_match_stub(knowledge_dataset, no_evidence_similarity: float):
    """
    Returns a fake match_documents that:
    - For regular queries: returns the expected chunk key at rank 1 (perfect recall).
    - For the single no-evidence query (last call): returns a result with a
      controlled similarity value.
    """
    regular = [tc for tc in knowledge_dataset["test"] if not tc.get("no_evidence")]
    call_iter = iter(regular)

    def fake_match(workspace_id, query_embedding, limit, sources):
        try:
            tc = next(call_iter)
            return [{"chunk_key": tc["expected_chunk_key"], "similarity": 0.92}]
        except StopIteration:
            # no-evidence call
            return [{"chunk_key": "eval:know:001", "similarity": no_evidence_similarity}]

    return fake_match


def _latest_eval_json(tool: str) -> Path:
    """Return the most recently written eval JSON for a given tool name."""
    output_dir = Path(__file__).parent.parent / "eval_results"
    files = sorted(output_dir.glob(f"eval_{tool}_*.json"), key=lambda p: p.stat().st_mtime)
    assert files, f"No eval_{tool}_*.json found in {output_dir}"
    return files[-1]


def test_run_eval_knowledge_calls_match_with_gdoc_gsheet_sources(monkeypatch, knowledge_dataset):
    captured_sources = []
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.get_ingestion_settings", lambda: _FakeSettings()
    )
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR] * len(texts),
    )

    def capturing_match(workspace_id, query_embedding, limit, sources):
        captured_sources.append(list(sources))
        return []

    monkeypatch.setattr("scripts.eval_retrieval_k.match_documents", capturing_match)
    run_eval("knowledge")

    for sources in captured_sources:
        assert set(sources) == {"gdoc", "gsheet"}, (
            f"Expected sources={{gdoc, gsheet}} but got {sources}"
        )
    assert "slack_decide" not in {s for call in captured_sources for s in call}


def test_run_eval_knowledge_no_evidence_pass_written_to_json(monkeypatch, knowledge_dataset):
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.get_ingestion_settings", lambda: _FakeSettings()
    )
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR] * len(texts),
    )
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.match_documents",
        _make_match_stub(knowledge_dataset, no_evidence_similarity=0.40),
    )

    run_eval("knowledge")

    payload = json.loads(_latest_eval_json("knowledge").read_text())
    assert payload["tool"] == "knowledge"
    assert payload["sources"] == ["gdoc", "gsheet"]
    assert len(payload["no_evidence_results"]) == 1
    assert payload["no_evidence_results"][0]["passed"] is True
    assert payload["no_evidence_results"][0]["best_similarity"] == pytest.approx(0.40, abs=1e-3)


def test_run_eval_knowledge_no_evidence_fail_written_to_json(monkeypatch, knowledge_dataset):
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.get_ingestion_settings", lambda: _FakeSettings()
    )
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR] * len(texts),
    )
    monkeypatch.setattr(
        "scripts.eval_retrieval_k.match_documents",
        _make_match_stub(knowledge_dataset, no_evidence_similarity=0.85),
    )

    run_eval("knowledge")

    payload = json.loads(_latest_eval_json("knowledge").read_text())
    assert payload["no_evidence_results"][0]["passed"] is False


# ── seed_eval_data knowledge branch ──────────────────────────────────────────

def test_seed_knowledge_uses_chunk_own_source_field(monkeypatch, knowledge_dataset):
    """Each chunk's own 'source' field (gdoc/gsheet) must be passed to upsert, not a fixed value."""
    from scripts.seed_eval_data import seed

    upserted = []
    monkeypatch.setattr("scripts.seed_eval_data.embed_documents", lambda texts: [[0.1] * 1024] * len(texts))
    monkeypatch.setattr("scripts.seed_eval_data.to_pgvector", lambda v: v)
    monkeypatch.setattr("scripts.seed_eval_data.upsert_chunks", lambda rows: upserted.extend(rows))

    train_chunks = knowledge_dataset["train"]
    seed(workspace_id="T_TEST", train_chunks=train_chunks, source_id="eval_knowledge_v1", default_source=None)

    sources_written = {r["source"] for r in upserted}
    assert "gdoc" in sources_written
    assert "gsheet" in sources_written
    assert "slack_decide" not in sources_written


def test_seed_knowledge_preserves_chunk_metadata(monkeypatch, knowledge_dataset):
    from scripts.seed_eval_data import seed

    upserted = []
    monkeypatch.setattr("scripts.seed_eval_data.embed_documents", lambda texts: [[0.1] * 1024] * len(texts))
    monkeypatch.setattr("scripts.seed_eval_data.to_pgvector", lambda v: v)
    monkeypatch.setattr("scripts.seed_eval_data.upsert_chunks", lambda rows: upserted.extend(rows))

    train_chunks = knowledge_dataset["train"]
    seed(workspace_id="T_TEST", train_chunks=train_chunks, source_id="eval_knowledge_v1", default_source=None)

    # gdoc chunks must carry title + heading_path in metadata
    gdoc_rows = [r for r in upserted if r["source"] == "gdoc"]
    assert gdoc_rows, "No gdoc rows were upserted"
    for row in gdoc_rows:
        assert row["metadata"].get("title"), f"gdoc row {row['chunk_key']} missing title in metadata"

    # gsheet chunks must carry title in metadata
    gsheet_rows = [r for r in upserted if r["source"] == "gsheet"]
    assert gsheet_rows, "No gsheet rows were upserted"
    for row in gsheet_rows:
        assert row["metadata"].get("title"), f"gsheet row {row['chunk_key']} missing title in metadata"
