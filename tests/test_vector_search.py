import pytest

from tools.vector_search import (
    DECIDE_SEARCH_TOOL,
    DocumentSearchError,
    search_decisions,
)


FAKE_VECTOR = [0.1] * 1024
FAKE_ROW = {
    "source": "slack_decide",
    "content": "We approved $300 for tabling supplies.",
    "channel_id": "C0BB16YR0N9",
    "author_id": "U0BB4JP60KC",
    "chunk_key": "decide:abc123:0000",
    "similarity": 0.92,
    "metadata": {
        "user_name": "alice",
        "channel_name": "general",
        "decision_hash": "abc123",
        "received_at": "2026-06-21T19:45:30.602477+00:00",
    },
}


def test_decide_search_tool_schema_is_claude_compatible():
    assert DECIDE_SEARCH_TOOL["name"] == "search_decisions"
    assert "description" in DECIDE_SEARCH_TOOL

    schema = DECIDE_SEARCH_TOOL["input_schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["query"]
    assert schema["additionalProperties"] is False
    assert "query" in schema["properties"]
    assert "limit" in schema["properties"]
    assert schema["properties"]["limit"]["default"] == 5
    assert schema["properties"]["limit"]["maximum"] == 20
    assert "source" not in schema["properties"]


def test_search_decisions_raises_on_empty_query(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not embed")))

    with pytest.raises(ValueError, match="must not be empty"):
        search_decisions(query="", workspace_id="T123")


def test_search_decisions_raises_on_whitespace_query(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not embed")))

    with pytest.raises(ValueError, match="must not be empty"):
        search_decisions(query="   ", workspace_id="T123")


def test_search_decisions_clamps_limit_above_max(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tools.vector_search.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR],
    )
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: captured.update({"limit": limit}) or [],
    )

    search_decisions(query="budget", workspace_id="T123", limit=99)

    assert captured["limit"] == 20


def test_search_decisions_clamps_limit_below_min(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tools.vector_search.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR],
    )
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: captured.update({"limit": limit}) or [],
    )

    search_decisions(query="budget", workspace_id="T123", limit=0)

    assert captured["limit"] == 1


def test_search_decisions_always_passes_slack_decide_source(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tools.vector_search.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR],
    )
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: captured.update({"sources": sources}) or [],
    )

    search_decisions(query="budget", workspace_id="T123")

    assert captured["sources"] == ["slack_decide"]


def test_search_decisions_maps_row_to_retrieved_chunk(monkeypatch):
    monkeypatch.setattr(
        "tools.vector_search.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR],
    )
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: [FAKE_ROW],
    )

    chunks = search_decisions(query="tabling supplies", workspace_id="T123")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source == "slack_decide"
    assert chunk.text == "We approved $300 for tabling supplies."
    assert chunk.channel_id == "C0BB16YR0N9"
    assert chunk.author_user_id == "U0BB4JP60KC"
    assert chunk.author_name == "alice"
    assert chunk.channel_name == "general"
    assert chunk.metadata["chunk_key"] == "decide:abc123:0000"
    assert chunk.metadata["similarity"] == 0.92
    assert chunk.metadata["decision_hash"] == "abc123"


def test_search_decisions_returns_empty_list_when_no_results(monkeypatch):
    monkeypatch.setattr(
        "tools.vector_search.embed_documents",
        lambda texts, input_type="document": [FAKE_VECTOR],
    )
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: [],
    )

    chunks = search_decisions(query="something obscure", workspace_id="T123")

    assert chunks == []


def test_search_decisions_uses_query_input_type(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tools.vector_search.embed_documents",
        lambda texts, input_type="document": captured.update({"input_type": input_type}) or [FAKE_VECTOR],
    )
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: [],
    )

    search_decisions(query="fundraiser", workspace_id="T123")

    assert captured["input_type"] == "query"
