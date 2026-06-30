import pytest

from tools.vector_search import (
    DECIDE_SEARCH_TOOL,
    KNOWLEDGE_SEARCH_TOOL,
    DocumentSearchError,
    search_decisions,
    search_knowledge,
)


FAKE_VECTOR = [0.1] * 1024

FAKE_DECIDE_ROW = {
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

FAKE_GDOC_ROW = {
    "source": "gdoc",
    "content": "Budget for venue: $1,200 approved.",
    "chunk_key": "gdoc:doc1:budget:abc",
    "similarity": 0.88,
    "metadata": {
        "title": "End-of-Term Handover",
        "heading": "Budget",
        "heading_path": "Finances > Budget",
    },
}

FAKE_GSHEET_ROW = {
    "source": "gsheet",
    "content": "Name: Alice | Role: President",
    "chunk_key": "gsheet:sheet1:0001",
    "similarity": 0.85,
    "metadata": {
        "title": "Member Roster",
    },
}


# ── DECIDE_SEARCH_TOOL schema ─────────────────────────────────────────────────

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


# ── KNOWLEDGE_SEARCH_TOOL schema ──────────────────────────────────────────────

def test_knowledge_search_tool_schema_is_claude_compatible():
    assert KNOWLEDGE_SEARCH_TOOL["name"] == "search_knowledge"
    assert "description" in KNOWLEDGE_SEARCH_TOOL

    schema = KNOWLEDGE_SEARCH_TOOL["input_schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["query"]
    assert schema["additionalProperties"] is False
    assert "query" in schema["properties"]
    assert "limit" in schema["properties"]
    assert "source" not in schema["properties"]


# ── search_decisions ──────────────────────────────────────────────────────────

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
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: captured.update({"limit": limit}) or [])

    search_decisions(query="budget", workspace_id="T123", limit=99)
    assert captured["limit"] == 20


def test_search_decisions_clamps_limit_below_min(monkeypatch):
    captured = {}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: captured.update({"limit": limit}) or [])

    search_decisions(query="budget", workspace_id="T123", limit=0)
    assert captured["limit"] == 1


def test_search_decisions_always_passes_slack_decide_source(monkeypatch):
    captured = {}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: captured.update({"sources": sources}) or [])

    search_decisions(query="budget", workspace_id="T123")
    assert captured["sources"] == ["slack_decide"]


def test_search_decisions_maps_row_to_evidence(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [FAKE_DECIDE_ROW])

    results = search_decisions(query="tabling supplies", workspace_id="T123")

    assert len(results) == 1
    ev = results[0]
    assert ev.source == "slack_decide"
    assert ev.text == "We approved $300 for tabling supplies."
    assert ev.author == "alice"
    assert ev.similarity == 0.92
    assert ev.score is None
    assert ev.timestamp == "2026-06-21T19:45:30.602477+00:00"
    assert ev.citation.source == "slack_decide"
    assert ev.citation.label == "#general — 2026-06-21"
    assert ev.metadata["chunk_key"] == "decide:abc123:0000"
    assert ev.metadata["decision_hash"] == "abc123"


def test_search_decisions_citation_falls_back_to_channel_id_when_no_channel_name(monkeypatch):
    row = {**FAKE_DECIDE_ROW, "metadata": {"received_at": "2026-01-01T00:00:00+00:00"}}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [row])

    results = search_decisions(query="budget", workspace_id="T123")
    assert results[0].citation.label == "#C0BB16YR0N9 — 2026-01-01"


def test_search_decisions_citation_unknown_date_when_received_at_missing(monkeypatch):
    row = {**FAKE_DECIDE_ROW, "metadata": {"channel_name": "general"}}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [row])

    results = search_decisions(query="budget", workspace_id="T123")
    assert results[0].citation.label == "#general — unknown date"


def test_search_decisions_returns_empty_list_when_no_results(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [])

    assert search_decisions(query="something obscure", workspace_id="T123") == []


def test_search_decisions_uses_query_input_type(monkeypatch):
    captured = {}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": captured.update({"input_type": input_type}) or [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [])

    search_decisions(query="fundraiser", workspace_id="T123")
    assert captured["input_type"] == "query"


# ── search_knowledge ──────────────────────────────────────────────────────────

def test_search_knowledge_passes_gdoc_and_gsheet_sources(monkeypatch):
    captured = {}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: captured.update({"sources": sources}) or [])

    search_knowledge(query="budget", workspace_id="T123")
    assert captured["sources"] == ["gdoc", "gsheet"]


def test_search_knowledge_returns_empty_list_on_no_results(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [])

    assert search_knowledge(query="anything", workspace_id="T123") == []


def test_search_knowledge_raises_on_empty_query(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not embed")))

    with pytest.raises(ValueError, match="must not be empty"):
        search_knowledge(query="", workspace_id="T123")


def test_search_knowledge_gdoc_citation_label(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [FAKE_GDOC_ROW])

    results = search_knowledge(query="budget", workspace_id="T123")
    ev = results[0]
    assert ev.source == "gdoc"
    assert ev.similarity == 0.88
    assert ev.score is None
    assert ev.citation.source == "gdoc"
    assert ev.citation.label == "End-of-Term Handover › Finances > Budget"


def test_search_knowledge_gdoc_citation_falls_back_to_title_only(monkeypatch):
    row = {**FAKE_GDOC_ROW, "metadata": {"title": "Handover Doc"}}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [row])

    results = search_knowledge(query="doc", workspace_id="T123")
    assert results[0].citation.label == "Handover Doc"


def test_search_knowledge_gdoc_citation_falls_back_to_google_doc(monkeypatch):
    row = {**FAKE_GDOC_ROW, "metadata": {}}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [row])

    results = search_knowledge(query="doc", workspace_id="T123")
    assert results[0].citation.label == "Google Doc"


def test_search_knowledge_gsheet_citation_label(monkeypatch):
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [FAKE_GSHEET_ROW])

    results = search_knowledge(query="members", workspace_id="T123")
    ev = results[0]
    assert ev.source == "gsheet"
    assert ev.citation.source == "gsheet"
    assert ev.citation.label == "Member Roster"
    assert ev.author is None
    assert ev.timestamp is None


def test_search_knowledge_gsheet_citation_falls_back(monkeypatch):
    row = {**FAKE_GSHEET_ROW, "metadata": {}}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr("tools.vector_search.match_documents", lambda ws, vec, limit, sources: [row])

    results = search_knowledge(query="members", workspace_id="T123")
    assert results[0].citation.label == "Google Sheet"


# ── Workspace scoping ─────────────────────────────────────────────────────────

def test_search_decisions_forwards_workspace_id(monkeypatch):
    captured = {}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: captured.update({"ws": ws}) or [],
    )
    search_decisions(query="budget", workspace_id="T_WORKSPACE_A")
    assert captured["ws"] == "T_WORKSPACE_A"


def test_search_decisions_different_workspaces_forward_different_ids(monkeypatch):
    seen = []
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: seen.append(ws) or [],
    )
    search_decisions(query="budget", workspace_id="T_A")
    search_decisions(query="budget", workspace_id="T_B")
    assert seen == ["T_A", "T_B"]


def test_search_knowledge_forwards_workspace_id(monkeypatch):
    captured = {}
    monkeypatch.setattr("tools.vector_search.embed_documents", lambda texts, input_type="document": [FAKE_VECTOR])
    monkeypatch.setattr(
        "tools.vector_search.match_documents",
        lambda ws, vec, limit, sources: captured.update({"ws": ws}) or [],
    )
    search_knowledge(query="venue", workspace_id="T_WORKSPACE_B")
    assert captured["ws"] == "T_WORKSPACE_B"
