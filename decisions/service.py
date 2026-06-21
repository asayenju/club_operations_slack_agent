from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

from decisions.chunking import DecisionChunk, DecisionChunker, SentenceDecisionChunker


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        ...


class DocumentsRepository(Protocol):
    def find_by_chunk_key(self, chunk_key: str) -> dict[str, Any] | None:
        ...

    def insert_many(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class DecisionRecord:
    payloads: list[dict[str, Any]]
    inserted: list[dict[str, Any]]

    @property
    def payload(self) -> dict[str, Any]:
        return self.payloads[0]


class DecisionAlreadyStored(RuntimeError):
    def __init__(self, existing: dict[str, Any]):
        self.existing = existing
        super().__init__("Decision is already stored")


class DecisionService:
    def __init__(
        self,
        documents_repository: DocumentsRepository,
        embedding_client: EmbeddingClient,
        chunker: DecisionChunker | None = None,
    ):
        self.documents_repository = documents_repository
        self.embedding_client = embedding_client
        self.chunker = chunker or SentenceDecisionChunker()

    def store_decision(
        self,
        command: dict[str, Any],
        received_at: datetime | None = None,
    ) -> DecisionRecord:
        content = normalize_decision_text(str(command.get("text", "")))
        if not content:
            raise ValueError("decision text must not be empty")

        decision_hash = hash_content(content)
        chunks = self.chunker.chunk(content)
        if not chunks:
            raise ValueError("decision text must not be empty")

        existing = self.documents_repository.find_by_chunk_key(
            build_chunk_key(decision_hash, 0)
        )
        if existing is not None:
            raise DecisionAlreadyStored(existing)

        embeddings = self.embedding_client.embed_many([chunk.text for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise ValueError("embedding count must match chunk count")

        timestamp = received_at or datetime.now(UTC)
        payloads = [
            build_document_payload(
                command=command,
                chunk=chunk,
                decision_hash=decision_hash,
                source_text_length=len(content),
                embedding=embedding,
                received_at=timestamp,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        inserted = self.documents_repository.insert_many(payloads)
        return DecisionRecord(payloads=payloads, inserted=inserted)


def normalize_decision_text(text: str) -> str:
    return text.strip()


def hash_content(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def build_chunk_key(decision_hash: str, chunk_index: int) -> str:
    return f"decide:{decision_hash}:{chunk_index:04d}"


def build_document_payload(
    command: dict[str, Any],
    chunk: DecisionChunk,
    decision_hash: str,
    source_text_length: int,
    embedding: list[float],
    received_at: datetime,
) -> dict[str, Any]:
    timestamp = received_at.astimezone(UTC).isoformat()
    trigger_id = command.get("trigger_id")
    chunk_key = build_chunk_key(decision_hash, chunk.index)
    content_hash = hash_content(f"{decision_hash}:{chunk.index}:{chunk.text}")
    metadata = {
        "received_at": timestamp,
        "decision_hash": decision_hash,
        "chunk_index": chunk.index,
        "chunk_count": chunk.count,
        "source_text_length": source_text_length,
        "chunk_text_length": len(chunk.text),
        "team_id": command.get("team_id"),
        "team_domain": command.get("team_domain"),
        "enterprise_id": command.get("enterprise_id"),
        "enterprise_name": command.get("enterprise_name"),
        "channel_id": command.get("channel_id"),
        "channel_name": command.get("channel_name"),
        "user_id": command.get("user_id"),
        "user_name": command.get("user_name"),
        "command": command.get("command"),
        "trigger_id": trigger_id,
        "has_response_url": bool(command.get("response_url")),
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}

    return {
        "workspace_id": command.get("team_id"),
        "source": "slack_decide",
        "source_id": trigger_id,
        "chunk_key": chunk_key,
        "content": chunk.text,
        "content_hash": content_hash,
        "author_id": command.get("user_id"),
        "channel_id": command.get("channel_id"),
        "metadata": metadata,
        "embedding": embedding,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
