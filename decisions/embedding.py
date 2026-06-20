from typing import Any

import httpx


class EmbeddingError(RuntimeError):
    pass


class VoyageEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 15.0,
        http_client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.http_client = http_client or httpx.Client(timeout=timeout)

    def embed(self, text: str) -> list[float]:
        try:
            response = self.http_client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": [text], "model": self.model},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError("Voyage embedding request failed") from exc

        return _extract_embedding(response.json())


def _extract_embedding(payload: dict[str, Any]) -> list[float]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise EmbeddingError("Voyage embedding response did not include data")

    embedding = data[0].get("embedding") if isinstance(data[0], dict) else None
    if not isinstance(embedding, list) or not embedding:
        raise EmbeddingError("Voyage embedding response did not include an embedding")

    try:
        return [float(value) for value in embedding]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("Voyage embedding contained non-numeric values") from exc
