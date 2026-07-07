from unittest.mock import MagicMock, patch

from memoryAnswer.composer import compose_answer, evaluate_conflict
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


def make_refusal_client() -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value.content = []
    return client


# ── evaluate_conflict ──────────────────────────────────────────────────────────

def test_evaluate_conflict_single_source_returns_unknown_without_calling_claude():
    client = MagicMock()
    result = evaluate_conflict([make_evidence("gdoc"), make_evidence("gdoc")], client=client)
    assert result == "unknown"
    client.messages.create.assert_not_called()


def test_evaluate_conflict_returns_agreeing():
    client = make_mock_client("agreeing")
    result = evaluate_conflict([make_evidence("gdoc"), make_evidence("gsheet")], client=client)
    assert result == "agreeing"


def test_evaluate_conflict_returns_conflicting():
    client = make_mock_client("conflicting")
    result = evaluate_conflict([make_evidence("gdoc"), make_evidence("gsheet")], client=client)
    assert result == "conflicting"


def test_evaluate_conflict_returns_unknown_on_unexpected_response():
    client = make_mock_client("I cannot determine this.")
    result = evaluate_conflict([make_evidence("gdoc"), make_evidence("gsheet")], client=client)
    assert result == "unknown"


def test_evaluate_conflict_does_not_mistake_disagreeing_for_agreeing():
    client = make_mock_client("These sources are disagreeing.")
    result = evaluate_conflict([make_evidence("gdoc"), make_evidence("gsheet")], client=client)
    assert result == "unknown"


def test_evaluate_conflict_returns_unknown_on_refusal():
    client = make_refusal_client()
    result = evaluate_conflict([make_evidence("gdoc"), make_evidence("gsheet")], client=client)
    assert result == "unknown"


def test_evaluate_conflict_prompt_contains_evidence_text():
    client = make_mock_client("agreeing")
    ev = make_evidence("gdoc", "Budget is $500.")
    evaluate_conflict([ev, make_evidence("gsheet", "other text")], client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Budget is $500." in user_content


# ── compose_answer: fallback ───────────────────────────────────────────────────

def test_no_evidence_returns_fallback_without_calling_claude():
    client = MagicMock()
    confidence = ConfidenceResult(level="Low", reason="No relevant evidence found.")
    answer, returned_confidence = compose_answer("What is the budget?", [], confidence, client=client)
    assert "couldn't find" in answer.lower()
    client.messages.create.assert_not_called()
    assert returned_confidence is confidence


# ── compose_answer: prompt contents ───────────────────────────────────────────

def test_compose_prompt_contains_question():
    client = make_mock_client("The budget is $500.")
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")
    compose_answer("What is our budget?", evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "What is our budget?" in user_content


def test_compose_prompt_contains_evidence_text():
    client = make_mock_client("The budget is $500.")
    evidence = [make_evidence("gdoc", "Budget cap is $500 per semester.")]
    confidence = ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")
    compose_answer("What is our budget?", evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Budget cap is $500 per semester." in user_content


def test_compose_prompt_contains_evidence_citation():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")
    compose_answer("question?", evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    # The system prompt asks Claude to cite the bracketed source label itself
    # (e.g. "[#general — 2026-06-21]"), so the evidence block must present it
    # in that exact bracketed form rather than a numeric index.
    assert "[label-gdoc]" in user_content


def test_compose_prompt_contains_confidence_level_and_reason():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="High", reason="Supported by a formal /decide statement.")
    compose_answer("question?", evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "High" in user_content
    assert "Supported by a formal /decide statement." in user_content


def test_compose_returns_fallback_on_refusal():
    client = make_refusal_client()
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")
    answer, returned_confidence = compose_answer("question?", evidence, confidence, client=client)
    assert "couldn't find" in answer.lower()
    assert returned_confidence is confidence


def test_compose_returns_claude_response_text():
    expected = "The club budget is $500 per semester. [label-gdoc]"
    client = make_mock_client(expected)
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")
    answer, _ = compose_answer("What is our budget?", evidence, confidence, client=client)
    assert answer == expected


# ── compose_answer: conflict resolution ───────────────────────────────────────

def test_compose_skips_evaluate_when_conflict_is_false():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="High", reason="Corroborated.", conflict=False)
    with patch("memoryAnswer.composer.evaluate_conflict") as mock_eval:
        compose_answer("question?", evidence, confidence, client=client)
        mock_eval.assert_not_called()


def test_compose_skips_evaluate_when_conflict_is_true():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Conflicting.", conflict=True)
    with patch("memoryAnswer.composer.evaluate_conflict") as mock_eval:
        compose_answer("question?", evidence, confidence, client=client)
        mock_eval.assert_not_called()


def test_compose_calls_evaluate_when_unclear():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("memoryAnswer.composer.evaluate_conflict", return_value="agreeing") as mock_eval:
        compose_answer("question?", evidence, confidence, client=client)
        mock_eval.assert_called_once()


def test_compose_updates_conflict_and_reason_when_agreeing():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("memoryAnswer.composer.evaluate_conflict", return_value="agreeing"):
        _, updated = compose_answer("question?", evidence, confidence, client=client)
    assert updated.conflict is False
    assert "Corroborated" in updated.reason


def test_compose_upgrades_level_to_match_score_confidence_when_agreeing():
    # Regression test: resolving an "unclear" conflict to "agreeing" must produce
    # the same level/reason score_confidence(evidence, agreement="agreeing") would
    # give directly, not the stale "Medium" from the original unclear scoring.
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("memoryAnswer.composer.evaluate_conflict", return_value="agreeing"):
        _, updated = compose_answer("question?", evidence, confidence, client=client)
    assert updated == score_confidence(evidence, agreement="agreeing")
    assert updated.level == "High"


def test_compose_updates_conflict_and_reason_when_conflicting():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("memoryAnswer.composer.evaluate_conflict", return_value="conflicting"):
        _, updated = compose_answer("question?", evidence, confidence, client=client)
    assert updated.conflict is True
    assert "conflicting" in updated.reason.lower()


def test_compose_keeps_confidence_unchanged_when_evaluate_returns_unknown():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("memoryAnswer.composer.evaluate_conflict", return_value="unknown"):
        _, updated = compose_answer("question?", evidence, confidence, client=client)
    assert updated.conflict == "unclear"
    assert updated.reason == "Not verified."


def test_compose_passes_updated_confidence_to_prompt_when_resolved():
    client = make_mock_client("The answer.")
    evidence = [make_evidence("gdoc"), make_evidence("gsheet")]
    confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    with patch("memoryAnswer.composer.evaluate_conflict", return_value="agreeing"):
        compose_answer("question?", evidence, confidence, client=client)
    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Corroborated" in user_content
