from typing import Any

import httpx


class EmbeddingError(RuntimeError):
    pass


class VoyageEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        output_dimension: int,
        timeout: float = 15.0,
        http_client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.output_dimension = output_dimension
        self.timeout = timeout
        self.http_client = http_client or httpx.Client(timeout=timeout)

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = self.http_client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": self.model,
                    "input_type": "document",
                    "output_dimension": self.output_dimension,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError("Voyage embedding request failed") from exc

        return _extract_embeddings(response.json(), expected_count=len(texts))


def _extract_embedding(payload: dict[str, Any]) -> list[float]:
    return _extract_embeddings(payload, expected_count=1)[0]


def _extract_embeddings(
    payload: dict[str, Any],
    expected_count: int | None = None,
) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise EmbeddingError("Voyage embedding response did not include data")

    if expected_count is not None and len(data) != expected_count:
        raise EmbeddingError("Voyage embedding response count did not match request")

    embeddings: list[list[float]] = []
    for item in data:
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingError("Voyage embedding response did not include an embedding")

        try:
            embeddings.append([float(value) for value in embedding])
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("Voyage embedding contained non-numeric values") from exc

    return embeddings
