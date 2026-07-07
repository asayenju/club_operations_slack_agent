import pytest

from tools.vector_search import list_decisions

FAKE_DECIDE_ROW = {
    "source": "slack_decide",
    "content": "We approved $300 for tabling supplies.",
    "channel_id": "C0BB16YR0N9",
    "author_id": "U0BB4JP60KC",
    "chunk_key": "decide:abc123:0000",
    "metadata": {
        "user_name": "alice",
        "channel_name": "general",
        "decision_hash": "abc123",
        "received_at": "2026-06-21T19:45:30.602477+00:00",
    },
}


def test_list_decisions_maps_rows_to_evidence(monkeypatch):
    monkeypatch.setattr(
        "tools.vector_search.list_by_source",
        lambda workspace_id, source, since=None: [FAKE_DECIDE_ROW],
    )

    results = list_decisions(workspace_id="T123")

    assert len(results) == 1
    ev = results[0]
    assert ev.source == "slack_decide"
    assert ev.text == "We approved $300 for tabling supplies."
    assert ev.similarity is None
    assert ev.score is None
    assert ev.citation.label == "#general — 2026-06-21"


def test_list_decisions_returns_empty_list_for_no_rows(monkeypatch):
    monkeypatch.setattr(
        "tools.vector_search.list_by_source",
        lambda workspace_id, source, since=None: [],
    )

    assert list_decisions(workspace_id="T123") == []


def test_list_decisions_rejects_empty_workspace_id():
    with pytest.raises(ValueError):
        list_decisions(workspace_id="   ")


def test_list_decisions_forwards_source_and_since(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "tools.vector_search.list_by_source",
        lambda workspace_id, source, since=None: captured.update(
            {"workspace_id": workspace_id, "source": source, "since": since}
        )
        or [],
    )

    list_decisions(workspace_id="T123", since="2026-06-01T00:00:00+00:00")

    assert captured == {
        "workspace_id": "T123",
        "source": "slack_decide",
        "since": "2026-06-01T00:00:00+00:00",
    }


def test_list_decisions_forwards_workspace_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "tools.vector_search.list_by_source",
        lambda workspace_id, source, since=None: captured.update({"ws": workspace_id}) or [],
    )
    list_decisions(workspace_id="T_WORKSPACE_A")
    assert captured["ws"] == "T_WORKSPACE_A"


def test_list_decisions_different_workspaces_forward_different_ids(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "tools.vector_search.list_by_source",
        lambda workspace_id, source, since=None: seen.append(workspace_id) or [],
    )
    list_decisions(workspace_id="T_A")
    list_decisions(workspace_id="T_B")
    assert seen == ["T_A", "T_B"]
