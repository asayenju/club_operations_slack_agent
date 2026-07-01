import pytest

from tools.confidence import ConfidenceResult, score_confidence
from tools.models import Citation, Evidence


def make_evidence(source: str, similarity: float | None = 0.90) -> Evidence:
    return Evidence(
        source=source,
        text="some text",
        citation=Citation(source=source, label="label"),
        similarity=similarity,
    )


# ── No evidence ───

def test_no_evidence_returns_low():
    result = score_confidence([])
    assert result.level == "Low"
    assert result.conflict is False
    assert "No relevant evidence" in result.reason


# ── /decide ────

def test_decide_only_returns_high():
    result = score_confidence([make_evidence("slack_decide")])
    assert result.level == "High"
    assert result.conflict is False
    assert "/decide" in result.reason


def test_multiple_decide_evidence_returns_high():
    result = score_confidence([make_evidence("slack_decide"), make_evidence("slack_decide")])
    assert result.level == "High"
    assert result.conflict is False


# ── Conflict: decide + other source ────

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


# ── Two independent source types (no decide) ───

def test_gdoc_and_gsheet_returns_high():
    result = score_confidence([make_evidence("gdoc"), make_evidence("gsheet")])
    assert result.level == "High"
    assert result.conflict is False
    assert "gdoc" in result.reason
    assert "gsheet" in result.reason


def test_gdoc_and_slack_returns_high():
    result = score_confidence([make_evidence("gdoc"), make_evidence("slack")])
    assert result.level == "High"
    assert result.conflict is False


# ── Single doc/sheet source ────

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


# ── Slack RTS only ────

def test_slack_only_returns_low():
    result = score_confidence([make_evidence("slack", similarity=None)])
    assert result.level == "Low"
    assert result.conflict is False
    assert "slack" in result.reason
