import pytest
import httpx

from decisions.embedding import EmbeddingError, VoyageEmbeddingClient, _extract_embedding


class FakeHTTPClient:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}]},
            request=httpx.Request("POST", url),
        )


def test_voyage_embedding_client_sends_document_input_type():
    http_client = FakeHTTPClient()
    client = VoyageEmbeddingClient(
        api_key="voyage-key",
        model="voyage-3.5-lite",
        output_dimension=1024,
        http_client=http_client,
    )

    assert client.embed("We approved snacks.") == [0.1, 0.2]
    assert http_client.calls[0]["json"] == {
        "input": ["We approved snacks."],
        "model": "voyage-3.5-lite",
        "input_type": "document",
        "output_dimension": 1024,
    }
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer voyage-key"


def test_extract_embedding_returns_numeric_vector():
    payload = {"data": [{"embedding": [1, 2.5, "3"]}]}

    assert _extract_embedding(payload) == [1.0, 2.5, 3.0]


def test_extract_embedding_rejects_missing_data():
    with pytest.raises(EmbeddingError):
        _extract_embedding({"data": []})


def test_extract_embedding_rejects_non_numeric_values():
    with pytest.raises(EmbeddingError):
        _extract_embedding({"data": [{"embedding": ["nope"]}]})
