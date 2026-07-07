from datetime import UTC, datetime

import pytest

from reconciliation.candidates import (
    ReconciliationCandidate,
    SourceResult,
    build_reconciliation_candidate,
    build_reconciliation_candidates,
)
from tools.models import Citation, Evidence


def make_evidence(source: str, text: str = "some evidence text") -> Evidence:
    return Evidence(
        source=source,
        text=text,
        citation=Citation(source=source, label=f"label-{source}"),
        similarity=0.85,
    )


# ── SourceResult / ReconciliationCandidate construction ────────────────────────

def test_all_evidence_flattens_across_results_preserving_order():
    candidate = ReconciliationCandidate(
        workspace_id="T123",
        topic="club budget",
        results=[
            SourceResult(source="slack_decide", evidence=[make_evidence("slack_decide", "a")]),
            SourceResult(source="gdoc", evidence=[make_evidence("gdoc", "b"), make_evidence("gdoc", "c")]),
            SourceResult(source="gsheet", evidence=[]),
        ],
    )

    assert [ev.text for ev in candidate.all_evidence()] == ["a", "b", "c"]


def test_has_any_evidence_true_when_at_least_one_source_has_evidence():
    candidate = ReconciliationCandidate(
        workspace_id="T123",
        topic="club budget",
        results=[
            SourceResult(source="slack_decide", evidence=[]),
            SourceResult(source="gdoc", evidence=[make_evidence("gdoc")]),
        ],
    )

    assert candidate.has_any_evidence() is True


def test_has_any_evidence_false_when_all_results_empty():
    candidate = ReconciliationCandidate(
        workspace_id="T123",
        topic="club budget",
        results=[
            SourceResult(source="slack_decide", evidence=[]),
            SourceResult(source="gdoc", evidence=[]),
            SourceResult(source="gsheet", evidence=[]),
        ],
    )

    assert candidate.has_any_evidence() is False


def test_empty_sources_lists_only_searched_and_empty_sources():
    candidate = ReconciliationCandidate(
        workspace_id="T123",
        topic="club budget",
        results=[
            SourceResult(source="slack_decide", evidence=[], searched=True),
            SourceResult(source="gdoc", evidence=[make_evidence("gdoc")], searched=True),
            SourceResult(source="gsheet", evidence=[], searched=False),
        ],
    )

    assert candidate.empty_sources() == ["slack_decide"]


def test_candidate_defaults_to_empty_results_and_sets_generated_at():
    before = datetime.now(UTC)
    candidate = ReconciliationCandidate(workspace_id="T123", topic="club budget")
    after = datetime.now(UTC)

    assert candidate.results == []
    assert candidate.all_evidence() == []
    assert candidate.has_any_evidence() is False
    assert before <= candidate.generated_at <= after


# ── build_reconciliation_candidate: scenarios ──────────────────────────────────

def _by_source(candidate, source):
    return next(r for r in candidate.results if r.source == source)


def test_build_candidate_missing_decision_scenario(monkeypatch):
    """Docs/Sheets discuss a topic but no /decide record covers it — even the
    unfiltered decision listing comes back empty (genuinely missing)."""
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.list_decisions",
        lambda ws: [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [
            make_evidence("gdoc", "Venue booked for $500."),
        ],
    )

    candidate = build_reconciliation_candidate("venue booking", workspace_id="T123")

    assert _by_source(candidate, "slack_decide").evidence == []
    assert len(_by_source(candidate, "gdoc").evidence) == 1
    assert candidate.has_any_evidence() is True
    assert candidate.empty_sources() == ["slack_decide", "gsheet"]


def test_build_candidate_falls_back_to_decision_listing_when_search_empty(monkeypatch):
    """A real decision exists but scored below the similarity threshold —
    the unfiltered listing fallback still surfaces it."""
    listed_decision = make_evidence("slack_decide", "We picked the campus quad for the venue.")
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.list_decisions",
        lambda ws: [listed_decision],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [],
    )

    candidate = build_reconciliation_candidate("venue booking", workspace_id="T123")

    assert _by_source(candidate, "slack_decide").evidence == [listed_decision]


def test_build_candidate_does_not_fall_back_when_search_decisions_finds_something(monkeypatch):
    calls = {"list_decisions": 0}
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [make_evidence("slack_decide", "found it")],
    )

    def fake_list_decisions(ws):
        calls["list_decisions"] += 1
        return []

    monkeypatch.setattr("reconciliation.candidates.list_decisions", fake_list_decisions)
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [],
    )

    build_reconciliation_candidate("venue booking", workspace_id="T123")

    assert calls["list_decisions"] == 0


def test_build_candidate_budget_mismatch_scenario(monkeypatch):
    """Both a /decide record and a Sheet mention a cost, with different figures
    — build_reconciliation_candidate co-presents them without judging."""
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [
            make_evidence("slack_decide", "We approved $300 for tabling supplies.")
        ],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [
            make_evidence("gsheet", "Tabling supplies: $250"),
        ],
    )

    candidate = build_reconciliation_candidate("tabling supplies budget", workspace_id="T123")

    assert "$300" in _by_source(candidate, "slack_decide").evidence[0].text
    assert "$250" in _by_source(candidate, "gsheet").evidence[0].text
    assert candidate.has_any_evidence() is True


def test_build_candidate_conflicting_fact_scenario(monkeypatch):
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [
            make_evidence("slack_decide", "Meeting moved to Friday.")
        ],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [
            make_evidence("gdoc", "Meeting is on Thursday as usual."),
        ],
    )

    candidate = build_reconciliation_candidate("weekly meeting day", workspace_id="T123")

    assert len(candidate.all_evidence()) == 2


def test_build_candidate_returns_candidate_not_none_when_fully_empty(monkeypatch):
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [],
    )
    monkeypatch.setattr("reconciliation.candidates.list_decisions", lambda ws: [])
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [],
    )

    candidate = build_reconciliation_candidate("nonexistent topic", workspace_id="T123")

    assert isinstance(candidate, ReconciliationCandidate)
    assert candidate.has_any_evidence() is False
    assert set(candidate.empty_sources()) == {"slack_decide", "gdoc", "gsheet"}


def test_build_candidate_splits_knowledge_results_by_source(monkeypatch):
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: [],
    )
    monkeypatch.setattr("reconciliation.candidates.list_decisions", lambda ws: [])
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: [
            make_evidence("gdoc", "doc evidence"),
            make_evidence("gsheet", "sheet evidence"),
        ],
    )

    candidate = build_reconciliation_candidate("club budget", workspace_id="T123")

    assert [ev.text for ev in _by_source(candidate, "gdoc").evidence] == ["doc evidence"]
    assert [ev.text for ev in _by_source(candidate, "gsheet").evidence] == ["sheet evidence"]


# ── build_reconciliation_candidate: validation ─────────────────────────────────

def test_build_candidate_rejects_empty_topic():
    with pytest.raises(ValueError):
        build_reconciliation_candidate("   ", workspace_id="T123")


def test_build_candidate_rejects_empty_workspace_id():
    with pytest.raises(ValueError):
        build_reconciliation_candidate("club budget", workspace_id="   ")


# ── build_reconciliation_candidate: workspace scoping ──────────────────────────

def test_build_candidate_forwards_workspace_id_to_all_retrieval_calls(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: captured.setdefault("decide_ws", ws) and [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.list_decisions",
        lambda ws: captured.setdefault("list_ws", ws) and [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: captured.setdefault("knowledge_ws", ws) and [],
    )

    build_reconciliation_candidate("club budget", workspace_id="T_WORKSPACE_A")

    assert captured["decide_ws"] == "T_WORKSPACE_A"
    assert captured["list_ws"] == "T_WORKSPACE_A"
    assert captured["knowledge_ws"] == "T_WORKSPACE_A"


def test_build_candidate_different_workspaces_forward_different_ids(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "reconciliation.candidates.search_decisions",
        lambda topic, ws, limit, min_similarity: seen.append(("decide", ws)) or [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.list_decisions",
        lambda ws: seen.append(("list", ws)) or [],
    )
    monkeypatch.setattr(
        "reconciliation.candidates.search_knowledge",
        lambda topic, ws, limit, min_similarity: seen.append(("knowledge", ws)) or [],
    )

    build_reconciliation_candidate("club budget", workspace_id="T_A")
    build_reconciliation_candidate("club budget", workspace_id="T_B")

    assert ("decide", "T_A") in seen
    assert ("decide", "T_B") in seen
    assert ("list", "T_A") in seen
    assert ("list", "T_B") in seen


# ── build_reconciliation_candidates: batch ─────────────────────────────────────

def test_build_candidates_returns_one_per_topic_in_order(monkeypatch):
    calls = []

    def fake_build(topic, workspace_id, *, limit, min_similarity):
        calls.append((topic, workspace_id))
        return ReconciliationCandidate(workspace_id=workspace_id, topic=topic)

    monkeypatch.setattr("reconciliation.candidates.build_reconciliation_candidate", fake_build)

    result = build_reconciliation_candidates(
        ["club budget", "venue booking"], workspace_id="T123"
    )

    assert [c.topic for c in result] == ["club budget", "venue booking"]
    assert calls == [("club budget", "T123"), ("venue booking", "T123")]


def test_build_candidates_passes_same_workspace_id_to_every_topic(monkeypatch):
    seen_workspaces = []

    def fake_build(topic, workspace_id, *, limit, min_similarity):
        seen_workspaces.append(workspace_id)
        return ReconciliationCandidate(workspace_id=workspace_id, topic=topic)

    monkeypatch.setattr("reconciliation.candidates.build_reconciliation_candidate", fake_build)

    build_reconciliation_candidates(["a", "b", "c"], workspace_id="T_A")

    assert seen_workspaces == ["T_A", "T_A", "T_A"]


def test_build_candidates_empty_topic_list_returns_empty_list(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "reconciliation.candidates.build_reconciliation_candidate",
        lambda *a, **k: calls.append(1),
    )

    result = build_reconciliation_candidates([], workspace_id="T123")

    assert result == []
    assert calls == []


def test_build_candidates_propagates_error_from_bad_topic(monkeypatch):
    def fake_build(topic, workspace_id, *, limit, min_similarity):
        if not topic.strip():
            raise ValueError("topic must not be empty")
        return ReconciliationCandidate(workspace_id=workspace_id, topic=topic)

    monkeypatch.setattr("reconciliation.candidates.build_reconciliation_candidate", fake_build)

    with pytest.raises(ValueError):
        build_reconciliation_candidates(["club budget", "   "], workspace_id="T123")
