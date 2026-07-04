import pytest

from tools.confidence import ConfidenceResult, score_confidence
from tools.models import Citation, Evidence


def make_evidence(
    source: str,
    similarity: float | None = 0.90,
    timestamp: str | None = None,
) -> Evidence:
    return Evidence(
        source=source,
        text="some text",
        citation=Citation(source=source, label="label"),
        similarity=similarity,
        timestamp=timestamp,
    )


# ── No evidence ───────────────────────────────────────────────────────────────

def test_no_evidence_returns_low():
    result = score_confidence([])
    assert result.level == "Low"
    assert result.conflict is False
    assert "No relevant evidence" in result.reason


# ── /decide only ──────────────────────────────────────────────────────────────

def test_decide_only_returns_high():
    result = score_confidence([make_evidence("slack_decide")])
    assert result.level == "High"
    assert result.conflict is False
    assert "/decide" in result.reason


def test_multiple_decide_chunks_returns_high():
    result = score_confidence([make_evidence("slack_decide"), make_evidence("slack_decide")])
    assert result.level == "High"
    assert result.conflict is False


# ── /decide + other source ────────────────────────────────────────────────────

def test_decide_plus_gdoc_returns_high_with_conflict():
    result = score_confidence([make_evidence("slack_decide"), make_evidence("gdoc")])
    assert result.level == "High"
    assert result.conflict is True
    assert "/decide" in result.reason
    assert "gdoc" in result.reason


def test_decide_plus_slack_returns_high_with_conflict():
    result = score_confidence([make_evidence("slack_decide"), make_evidence("slack")])
    assert result.level == "High"
    assert result.conflict is True


# ── Multi-source, agreement="unknown" (default) ───────────────────────────────

def test_gdoc_and_gsheet_unknown_returns_medium_unclear():
    result = score_confidence([make_evidence("gdoc"), make_evidence("gsheet")])
    assert result.level == "Medium"
    assert result.conflict == "unclear"
    assert "gdoc" in result.reason
    assert "gsheet" in result.reason
    assert "not verified deterministically" in result.reason


def test_gdoc_and_gsheet_unknown_with_timestamps_notes_most_recent():
    result = score_confidence([
        make_evidence("gdoc", timestamp="2026-01-01T00:00:00Z"),
        make_evidence("gsheet", timestamp="2026-06-01T00:00:00Z"),
    ])
    assert result.level == "Medium"
    assert result.conflict == "unclear"
    assert "gsheet" in result.reason
    assert "2026-06-01" in result.reason


def test_gdoc_and_slack_unknown_returns_medium_with_priority_note():
    result = score_confidence([make_evidence("gdoc"), make_evidence("slack")])
    assert result.level == "Medium"
    assert result.conflict == "unclear"
    assert "takes priority over Slack" in result.reason
    assert "not verified deterministically" in result.reason


def test_gdoc_and_slack_unknown_with_timestamp_includes_date():
    result = score_confidence([
        make_evidence("gdoc", timestamp="2026-05-15T10:00:00Z"),
        make_evidence("slack"),
    ])
    assert result.level == "Medium"
    assert result.conflict == "unclear"
    assert "2026-05-15" in result.reason
    assert "takes priority over Slack" in result.reason


# ── Multi-source, agreement="agreeing" ───────────────────────────────────────

def test_gdoc_and_gsheet_agreeing_returns_high():
    result = score_confidence(
        [make_evidence("gdoc"), make_evidence("gsheet")],
        agreement="agreeing",
    )
    assert result.level == "High"
    assert result.conflict is False
    assert "Corroborated" in result.reason


def test_gdoc_and_gsheet_agreeing_with_timestamps_notes_most_recent():
    result = score_confidence(
        [
            make_evidence("gdoc", timestamp="2026-01-01T00:00:00Z"),
            make_evidence("gsheet", timestamp="2026-06-01T00:00:00Z"),
        ],
        agreement="agreeing",
    )
    assert result.level == "High"
    assert result.conflict is False
    assert "gsheet" in result.reason
    assert "2026-06-01" in result.reason


def test_gdoc_and_slack_agreeing_returns_high():
    result = score_confidence(
        [make_evidence("gdoc"), make_evidence("slack")],
        agreement="agreeing",
    )
    assert result.level == "High"
    assert result.conflict is False
    assert "takes priority over Slack" in result.reason


# ── Multi-source, agreement="conflicting" ────────────────────────────────────

def test_gdoc_and_gsheet_conflicting_returns_medium():
    result = score_confidence(
        [make_evidence("gdoc"), make_evidence("gsheet")],
        agreement="conflicting",
    )
    assert result.level == "Medium"
    assert result.conflict is True
    assert "conflicting" in result.reason


def test_gdoc_and_slack_conflicting_includes_priority_note():
    result = score_confidence(
        [make_evidence("gdoc"), make_evidence("slack")],
        agreement="conflicting",
    )
    assert result.level == "Medium"
    assert result.conflict is True
    assert "takes priority over Slack" in result.reason


# ── Single source (regression) ────────────────────────────────────────────────

def test_single_gdoc_returns_medium():
    result = score_confidence([make_evidence("gdoc")])
    assert result.level == "Medium"
    assert result.conflict is False
    assert "Google Doc" in result.reason


def test_multiple_gdoc_chunks_returns_medium():
    result = score_confidence([make_evidence("gdoc"), make_evidence("gdoc")])
    assert result.level == "Medium"
    assert result.conflict is False


def test_single_gsheet_returns_medium():
    result = score_confidence([make_evidence("gsheet")])
    assert result.level == "Medium"
    assert result.conflict is False
    assert "Google Sheet" in result.reason


def test_slack_only_returns_low():
    result = score_confidence([make_evidence("slack", similarity=None)])
    assert result.level == "Low"
    assert result.conflict is False
    assert "slack" in result.reason
