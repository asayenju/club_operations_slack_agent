import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_retrieval_k import best_k


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
