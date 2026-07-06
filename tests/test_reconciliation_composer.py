from unittest.mock import MagicMock, patch

from reconciliation.composer import compose_reconciliation_proposal
from tools.confidence import ConfidenceResult
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


# ── cautious proposal (low confidence) ────────────────────────────────────────

def test_low_confidence_does_not_call_claude():
    client = MagicMock()
    evidence = [make_evidence("slack")]
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    compose_reconciliation_proposal(evidence, "Update the doc.", confidence, client=client)
    client.messages.create.assert_not_called()


def test_low_confidence_blocks_contain_cautious_text():
    client = MagicMock()
    evidence = [make_evidence("slack")]
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    blocks = compose_reconciliation_proposal(evidence, "Update the doc.", confidence, client=client)
    full_text = str(blocks)
    assert "insufficient" in full_text.lower()
    assert "human review" in full_text.lower()


# ── prompt contents ────────────────────────────────────────────────────────────

def test_prompt_contains_evidence_text():
    client = make_mock_client("Summary of conflict.")
    evidence = [
        make_evidence("gdoc", "Budget is $500."),
        make_evidence("gsheet", "Budget is $300."),
    ]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(evidence, "Update sheet.", confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Budget is $500." in user_content
    assert "Budget is $300." in user_content


def test_prompt_contains_evidence_citations():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "label-gdoc" in user_content
    assert "label-gsheet" in user_content


def test_prompt_contains_proposed_action():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    compose_reconciliation_proposal(
        evidence, "Update the budget sheet to $500.", confidence, client=client
    )
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Update the budget sheet to $500." in user_content


def test_prompt_contains_confidence_level_and_reason():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="High", reason="Supported by a /decide statement.", conflict=True)
    compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "High" in user_content
    assert "Supported by a /decide statement." in user_content


# ── block kit output ───────────────────────────────────────────────────────────

def test_returns_list_of_dicts():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    blocks = compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    assert isinstance(blocks, list)
    assert all(isinstance(b, dict) for b in blocks)


def test_blocks_contain_approval_instructions():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    blocks = compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    full_text = str(blocks)
    assert "white_check_mark" in full_text
    assert "72" in full_text


def test_blocks_contain_proposed_action():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    blocks = compose_reconciliation_proposal(evidence, "Update the roster.", confidence, client=client)
    full_text = str(blocks)
    assert "Update the roster." in full_text


def test_blocks_contain_urgency():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="High", reason="Conflicting.", conflict=True)
    blocks = compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    full_text = str(blocks)
    assert "High" in full_text


# ── unclear conflict resolution ────────────────────────────────────────────────

def test_unclear_conflict_calls_evaluate_conflict():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="conflicting") as mock_eval:
        compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
        mock_eval.assert_called_once()


def test_unclear_resolved_to_conflicting_updates_prompt():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="conflicting"):
        compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "conflicting" in user_content.lower()


def test_unclear_resolved_to_agreeing_updates_prompt():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="agreeing"):
        compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Corroborated" in user_content


def test_unclear_unresolved_keeps_original_confidence():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("reconciliation.composer.evaluate_conflict", return_value="unknown"):
        compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Not verified." in user_content


def test_conflict_false_does_not_call_evaluate_conflict():
    client = make_mock_client("Summary.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Corroborated.", conflict=False)
    with patch("reconciliation.composer.evaluate_conflict") as mock_eval:
        compose_reconciliation_proposal(evidence, "Update.", confidence, client=client)
        mock_eval.assert_not_called()
