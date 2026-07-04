from functools import lru_cache
from typing import Any

import voyageai

from common.config import get_ingestion_settings

EMBED_MODEL = "voyage-3.5-lite"
EMBED_DIMENSION = 1024


@lru_cache
def get_embedding_client() -> voyageai.Client:
    api_key = get_ingestion_settings().required_voyage_api_key
    return voyageai.Client(api_key=api_key)


def embed_documents(
    texts: list[str],
    input_type: str = "document",
) -> list[list[float]]:
    if not texts:
        return []

    response: Any = get_embedding_client().embed(
        texts,
        model=EMBED_MODEL,
        input_type=input_type,
        output_dimension=EMBED_DIMENSION,
    )
    return response.embeddings


def to_pgvector(vector: list[float]) -> list[float]:
    return [round(value, 6) for value in vector]
