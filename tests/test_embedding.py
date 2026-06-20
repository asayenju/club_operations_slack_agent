import pytest

from decisions.embedding import EmbeddingError, _extract_embedding


def test_extract_embedding_returns_numeric_vector():
    payload = {"data": [{"embedding": [1, 2.5, "3"]}]}

    assert _extract_embedding(payload) == [1.0, 2.5, 3.0]


def test_extract_embedding_rejects_missing_data():
    with pytest.raises(EmbeddingError):
        _extract_embedding({"data": []})


def test_extract_embedding_rejects_non_numeric_values():
    with pytest.raises(EmbeddingError):
        _extract_embedding({"data": [{"embedding": ["nope"]}]})
