import voyageai

from common.config import get_ingestion_settings

_voyage_client: voyageai.Client | None = None
_EMBED_MODEL = "voyage-3.5-lite"


def _get_client() -> voyageai.Client:
    global _voyage_client
    if _voyage_client is None:
        s = get_ingestion_settings()
        _voyage_client = voyageai.Client(api_key=s.required_voyage_api_key)
    return _voyage_client


def embed_documents(texts: list[str]) -> list[list[float]]:
    result = _get_client().embed(texts, model=_EMBED_MODEL, input_type="document")
    return result.embeddings


def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vector) + "]"
