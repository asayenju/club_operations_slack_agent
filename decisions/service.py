from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class DocumentsRepository(Protocol):
    def find_by_content_hash(self, content_hash: str) -> dict[str, Any] | None:
        ...

    def insert(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class DecisionRecord:
    payload: dict[str, Any]
    inserted: dict[str, Any]


class DecisionAlreadyStored(RuntimeError):
    def __init__(self, existing: dict[str, Any]):
        self.existing = existing
        super().__init__("Decision is already stored")


class DecisionService:
    def __init__(
        self,
        documents_repository: DocumentsRepository,
        embedding_client: EmbeddingClient,
    ):
        self.documents_repository = documents_repository
        self.embedding_client = embedding_client

    def store_decision(
        self,
        command: dict[str, Any],
        received_at: datetime | None = None,
    ) -> DecisionRecord:
        content = normalize_decision_text(str(command.get("text", "")))
        if not content:
            raise ValueError("decision text must not be empty")

        content_hash = hash_content(content)
        existing = self.documents_repository.find_by_content_hash(content_hash)
        if existing is not None:
            raise DecisionAlreadyStored(existing)

        embedding = self.embedding_client.embed(content)
        payload = build_document_payload(
            command=command,
            content=content,
            content_hash=content_hash,
            embedding=embedding,
            received_at=received_at or datetime.now(UTC),
        )
        inserted = self.documents_repository.insert(payload)
        return DecisionRecord(payload=payload, inserted=inserted)


def normalize_decision_text(text: str) -> str:
    return text.strip()


def hash_content(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def build_document_payload(
    command: dict[str, Any],
    content: str,
    content_hash: str,
    embedding: list[float],
    received_at: datetime,
) -> dict[str, Any]:
    timestamp = received_at.astimezone(UTC).isoformat()
    trigger_id = command.get("trigger_id")
    metadata = {
        "received_at": timestamp,
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
        "text_length": len(content),
        "has_response_url": bool(command.get("response_url")),
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}

    return {
        "workspace_id": command.get("team_id"),
        "source": "slack_decide",
        "source_id": trigger_id,
        "chunk_key": f"decide:{content_hash}",
        "content": content,
        "content_hash": content_hash,
        "author_id": command.get("user_id"),
        "channel_id": command.get("channel_id"),
        "metadata": metadata,
        "embedding": embedding,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
