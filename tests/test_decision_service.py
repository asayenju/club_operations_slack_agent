from datetime import UTC, datetime

import pytest

from decisions.chunking import DecisionChunk, SentenceDecisionChunker
from decisions.service import (
    DecisionAlreadyStored,
    DecisionService,
    build_chunk_key,
    build_document_payload,
    hash_content,
    normalize_decision_text,
)


class FakeDocumentsRepository:
    def __init__(self, existing=None):
        self.existing = existing
        self.duplicate_checks = []
        self.inserted_payload_batches = []

    def find_by_chunk_key(self, chunk_key, workspace_id, source):
        self.duplicate_checks.append(
            {
                "chunk_key": chunk_key,
                "workspace_id": workspace_id,
                "source": source,
            }
        )
        return self.existing

    def insert_many(self, payloads):
        self.inserted_payload_batches.append(payloads)
        return [{"id": f"doc-{index}", **payload} for index, payload in enumerate(payloads)]


class FakeEmbeddingClient:
    def __init__(self, embeddings=None, error=None):
        self.embeddings = embeddings or [[0.1, 0.2, 0.3]]
        self.error = error
        self.inputs = []

    def embed(self, text):
        return self.embed_many([text])[0]

    def embed_many(self, texts):
        self.inputs.append(texts)
        if self.error:
            raise self.error
        return self.embeddings


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
    decision_hash = hash_content(content)
    chunk = DecisionChunk(text=content, index=0, count=1)

    payload = build_document_payload(
        command=slash_command(content),
        chunk=chunk,
        decision_hash=decision_hash,
        source_text_length=len(content),
        embedding=[0.1, 0.2],
        received_at=received_at,
    )

    assert payload["workspace_id"] == "T123"
    assert payload["source"] == "slack_decide"
    assert payload["source_id"] == "trigger-123"
    assert payload["chunk_key"] == build_chunk_key(decision_hash, 0)
    assert payload["content"] == content
    assert payload["content_hash"] == hash_content(f"{decision_hash}:0:{content}")
    assert payload["author_id"] == "U123"
    assert payload["channel_id"] == "C123"
    assert payload["embedding"] == [0.1, 0.2]
    assert payload["created_at"] == "2026-06-20T12:30:00+00:00"
    assert payload["updated_at"] == "2026-06-20T12:30:00+00:00"
    assert payload["metadata"]["decision_hash"] == decision_hash
    assert payload["metadata"]["chunk_index"] == 0
    assert payload["metadata"]["chunk_count"] == 1
    assert payload["metadata"]["source_text_length"] == len(content)
    assert payload["metadata"]["chunk_text_length"] == len(content)
    assert payload["metadata"]["has_response_url"] is True
    assert "response_url" not in payload["metadata"]
    assert "id" not in payload


def test_store_decision_inserts_chunk_payloads_with_embeddings():
    repository = FakeDocumentsRepository()
    embedding_client = FakeEmbeddingClient([[1.0], [2.0]])
    service = DecisionService(
        repository,
        embedding_client,
        chunker=SentenceDecisionChunker(max_sentences=1, min_chunk_chars=1),
    )

    record = service.store_decision(
        slash_command("  We approved snacks. We picked Friday.  "),
        received_at=datetime(2026, 6, 20, 12, 30, tzinfo=UTC),
    )

    decision_hash = hash_content("We approved snacks. We picked Friday.")
    assert repository.duplicate_checks == [
        {
            "chunk_key": build_chunk_key(decision_hash, 0),
            "workspace_id": "T123",
            "source": "slack_decide",
        }
    ]
    assert embedding_client.inputs == [["We approved snacks.", "We picked Friday."]]
    assert repository.inserted_payload_batches == [record.payloads]
    assert [payload["content"] for payload in record.payloads] == [
        "We approved snacks.",
        "We picked Friday.",
    ]
    assert [payload["embedding"] for payload in record.payloads] == [[1.0], [2.0]]
    assert [payload["metadata"]["chunk_index"] for payload in record.payloads] == [0, 1]
    assert [payload["metadata"]["chunk_count"] for payload in record.payloads] == [2, 2]


def test_store_decision_skips_duplicate_decision_by_first_chunk_key():
    repository = FakeDocumentsRepository(existing={"id": "existing"})
    service = DecisionService(repository, FakeEmbeddingClient())

    with pytest.raises(DecisionAlreadyStored):
        service.store_decision(slash_command())

    assert repository.inserted_payload_batches == []
    assert repository.duplicate_checks == [
        {
            "chunk_key": build_chunk_key(
                hash_content("We approved $300 for tabling."), 0
            ),
            "workspace_id": "T123",
            "source": "slack_decide",
        }
    ]


def test_store_decision_fails_before_insert_when_embedding_fails():
    repository = FakeDocumentsRepository()
    service = DecisionService(repository, FakeEmbeddingClient(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        service.store_decision(slash_command())

    assert repository.inserted_payload_batches == []


def test_store_decision_fails_before_insert_when_embedding_count_mismatches():
    repository = FakeDocumentsRepository()
    service = DecisionService(
        repository,
        FakeEmbeddingClient([[1.0]]),
        chunker=SentenceDecisionChunker(max_sentences=1, min_chunk_chars=1),
    )

    with pytest.raises(ValueError, match="embedding count"):
        service.store_decision(slash_command("We approved snacks. We picked Friday."))

    assert repository.inserted_payload_batches == []
