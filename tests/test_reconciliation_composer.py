from unittest.mock import MagicMock, patch

from reconciliation.composer import compose_reconciliation_proposal
from tools.confidence import ConfidenceResult, score_confidence
from tools.models import Citation, Evidence


def make_evidence(source: str, text: str = "some evidence text") -> Evidence:
    return Evidence(
        source=source,
        text=text,
        citation=Citation(source=source, label=f"label-{source}"),
        similarity=0.85,
    )


def make_mock_client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=text)]
    return client


def make_sequenced_client(*texts: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.side_effect = [
        MagicMock(content=[MagicMock(text=text)]) for text in texts
    ]
    return client


# ── not actionable: no conflict detected ──────────────────────────────────────

def test_low_confidence_does_not_call_claude():
    client = MagicMock()
    evidence = [make_evidence("slack")]
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    compose_reconciliation_proposal(evidence, confidence, client=client)
    client.messages.create.assert_not_called()


def test_low_confidence_is_not_actionable_and_shows_reason():
    client = MagicMock()
    evidence = [make_evidence("slack")]
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    assert result.is_actionable is False
    assert result.proposed_action is None
    full_text = str(result.blocks)
    assert "no reconciliation needed" in full_text.lower()
    assert "No relevant evidence found." in full_text


def test_empty_evidence_does_not_call_claude_even_with_high_confidence():
    client = MagicMock()
    confidence = ConfidenceResult(level="High", reason="Supported by a /decide statement.")
    compose_reconciliation_proposal([], confidence, client=client)
    client.messages.create.assert_not_called()


def test_client_is_not_constructed_when_not_actionable(monkeypatch):
    constructed = []
    monkeypatch.setattr("anthropic.Anthropic", lambda *a, **kw: constructed.append(1))
    evidence = [make_evidence("slack")]
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    compose_reconciliation_proposal(evidence, confidence, client=None)
    assert constructed == []


def test_conflict_false_is_not_actionable_and_does_not_call_claude():
    # Regression test: a single authoritative source (or sources that agree)
    # used to still produce a full actionable card asking for confirmation.
    # Only a confirmed conflict (conflict is True) should require a lead's approval.
    client = MagicMock()
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="High", reason="Corroborated.", conflict=False)
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    client.messages.create.assert_not_called()
    assert result.is_actionable is False
    assert "Corroborated." in str(result.blocks)


def test_conflict_false_does_not_call_evaluate_conflict():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Corroborated.", conflict=False)
    with patch("reconciliation.composer.evaluate_conflict") as mock_eval:
        compose_reconciliation_proposal(evidence, confidence, client=client)
        mock_eval.assert_not_called()


# ── actionable: real conflict ──────────────────────────────────────────────────

def test_prompt_contains_evidence_text():
    client = make_mock_client("Summary of conflict.")
    evidence = [
        make_evidence("gdoc", "Budget is $500."),
        make_evidence("gsheet", "Budget is $300."),
    ]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Budget is $500." in user_content
    assert "Budget is $300." in user_content


def test_prompt_contains_evidence_citations():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "label-gdoc" in user_content
    assert "label-gsheet" in user_content


def test_prompt_contains_generated_proposed_action():
    client = make_sequenced_client("Update the budget sheet to $500.", "Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Update the budget sheet to $500." in user_content


def test_blocks_contain_generated_proposed_action():
    client = make_sequenced_client("Update the roster.", "Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    assert result.proposed_action == "Update the roster."
    assert "Update the roster." in str(result.blocks)


def test_proposed_action_prompt_grounded_in_evidence():
    client = make_sequenced_client("Update the budget sheet to $500.", "Summary.")
    evidence = [
        make_evidence("gdoc", "Budget is $500."),
        make_evidence("gsheet", "Budget is $300."),
    ]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(evidence, confidence, client=client)
    first_call_content = client.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
    assert "Budget is $500." in first_call_content
    assert "Budget is $300." in first_call_content


def test_prompt_contains_confidence_level_and_reason():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="High", reason="Supported by a /decide statement.", conflict=True)
    compose_reconciliation_proposal(evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "High" in user_content
    assert "Supported by a /decide statement." in user_content


# ── block kit output ───────────────────────────────────────────────────────────

def test_returns_composed_proposal_with_blocks_list():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    assert result.is_actionable is True
    assert isinstance(result.blocks, list)
    assert all(isinstance(b, dict) for b in result.blocks)


def test_blocks_contain_approval_instructions():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    full_text = str(result.blocks)
    assert "white_check_mark" in full_text
    assert "72" in full_text


def test_blocks_contain_urgency():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="High", reason="Conflicting.", conflict=True)
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    urgency_field = result.blocks[3]["fields"][0]["text"]
    assert urgency_field == "*Urgency:* High"


# ── unclear conflict resolution ────────────────────────────────────────────────

def test_unclear_conflict_calls_evaluate_conflict():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="conflicting") as mock_eval:
        compose_reconciliation_proposal(evidence, confidence, client=client)
        mock_eval.assert_called_once()


def test_unclear_resolved_to_conflicting_updates_prompt():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="conflicting"):
        compose_reconciliation_proposal(evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "conflicting" in user_content.lower()


def test_unclear_resolved_to_agreeing_skips_claude_and_returns_no_conflict_blocks():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="agreeing"):
        result = compose_reconciliation_proposal(evidence, confidence, client=client)
    client.messages.create.assert_not_called()
    assert result.is_actionable is False
    full_text = str(result.blocks)
    assert "no reconciliation needed" in full_text.lower()
    assert "Corroborated" in full_text
    assert "white_check_mark" not in full_text


def test_unclear_resolved_to_conflicting_upgrades_level_via_score_confidence():
    # Regression test: resolving an "unclear" conflict must produce the same
    # level/reason score_confidence(evidence, agreement=...) would give directly,
    # not a hand-rolled result that leaves level stuck at the pre-resolution tier.
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="conflicting"):
        result = compose_reconciliation_proposal(evidence, confidence, client=client)
    expected = score_confidence(evidence, agreement="conflicting")
    assert result.blocks[3]["fields"][1]["text"] == f"*Confidence:* {expected.level} — {expected.reason}"


def test_unclear_unresolved_is_not_actionable():
    # An "unclear" result the LLM also couldn't resolve is treated the same as
    # no conflict: there's nothing concrete for a lead to confirm.
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="unknown"):
        result = compose_reconciliation_proposal(evidence, confidence, client=client)
    client.messages.create.assert_not_called()
    assert result.is_actionable is False
    assert "Not verified." in str(result.blocks)


def test_claude_refusal_falls_back_for_both_action_and_summary():
    client = MagicMock()
    client.messages.create.return_value.content = []
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    result = compose_reconciliation_proposal(evidence, confidence, client=client)
    assert "reconcile manually" in result.proposed_action.lower()
    assert "could not be generated" in str(result.blocks).lower()
