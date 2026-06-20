from datetime import UTC, datetime

import pytest

from decisions.service import (
    DecisionAlreadyStored,
    DecisionService,
    build_document_payload,
    hash_content,
    normalize_decision_text,
)


class FakeDocumentsRepository:
    def __init__(self, existing=None):
        self.existing = existing
        self.inserted_payloads = []

    def find_by_content_hash(self, content_hash):
        return self.existing

    def insert(self, payload):
        self.inserted_payloads.append(payload)
        return {"id": "doc-123", **payload}


class FakeEmbeddingClient:
    def __init__(self, embedding=None, error=None):
        self.embedding = embedding or [0.1, 0.2, 0.3]
        self.error = error
        self.inputs = []

    def embed(self, text):
        self.inputs.append(text)
        if self.error:
            raise self.error
        return self.embedding


def slash_command(text="We approved $300 for tabling."):
    return {
        "team_id": "T123",
        "team_domain": "student-org",
        "enterprise_id": "E123",
        "channel_id": "C123",
        "channel_name": "general",
        "user_id": "U123",
        "user_name": "ashwin",
        "command": "/decide",
        "text": text,
        "trigger_id": "trigger-123",
        "response_url": "https://hooks.slack.com/commands/123",
    }


def test_normalize_decision_text_trims_only():
    assert normalize_decision_text("  We   keep   spacing.  ") == "We   keep   spacing."


def test_hash_content_hashes_trimmed_content_only():
    assert hash_content("Decision") == hash_content("Decision")
    assert hash_content("Decision") != hash_content("Decision ")


def test_build_document_payload_maps_slack_command_fields():
    received_at = datetime(2026, 6, 20, 12, 30, tzinfo=UTC)
    content = "We approved $300 for tabling."
    content_hash = hash_content(content)

    payload = build_document_payload(
        command=slash_command(content),
        content=content,
        content_hash=content_hash,
        embedding=[0.1, 0.2],
        received_at=received_at,
    )

    assert payload["workspace_id"] == "T123"
    assert payload["source"] == "slack_decide"
    assert payload["source_id"] == "trigger-123"
    assert payload["chunk_key"] == f"decide:{content_hash}"
    assert payload["content"] == content
    assert payload["content_hash"] == content_hash
    assert payload["author_id"] == "U123"
    assert payload["channel_id"] == "C123"
    assert payload["embedding"] == [0.1, 0.2]
    assert payload["created_at"] == "2026-06-20T12:30:00+00:00"
    assert payload["updated_at"] == "2026-06-20T12:30:00+00:00"
    assert payload["metadata"]["has_response_url"] is True
    assert payload["metadata"]["text_length"] == len(content)
    assert "response_url" not in payload["metadata"]
    assert "id" not in payload


def test_store_decision_inserts_payload_with_embedding():
    repository = FakeDocumentsRepository()
    embedding_client = FakeEmbeddingClient([1.0, 2.0])
    service = DecisionService(repository, embedding_client)

    record = service.store_decision(
        slash_command("  We approved snacks.  "),
        received_at=datetime(2026, 6, 20, 12, 30, tzinfo=UTC),
    )

    assert embedding_client.inputs == ["We approved snacks."]
    assert repository.inserted_payloads == [record.payload]
    assert record.payload["content"] == "We approved snacks."
    assert record.payload["embedding"] == [1.0, 2.0]


def test_store_decision_skips_duplicate_content():
    repository = FakeDocumentsRepository(existing={"id": "existing"})
    service = DecisionService(repository, FakeEmbeddingClient())

    with pytest.raises(DecisionAlreadyStored):
        service.store_decision(slash_command())

    assert repository.inserted_payloads == []


def test_store_decision_fails_before_insert_when_embedding_fails():
    repository = FakeDocumentsRepository()
    service = DecisionService(repository, FakeEmbeddingClient(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        service.store_decision(slash_command())

    assert repository.inserted_payloads == []
