from unittest.mock import patch

from memoryAnswer.service import MemoryAnswer, MemoryAnswerService
from tools.confidence import ConfidenceResult
from tools.models import Citation, Evidence


def make_evidence(source: str, text: str = "some evidence text") -> Evidence:
    return Evidence(
        source=source,
        text=text,
        citation=Citation(source=source, label=f"label-{source}"),
        similarity=0.85,
    )


def test_answer_combines_decide_and_knowledge_evidence_in_order():
    decide_evidence = [make_evidence("slack_decide", "Decision text.")]
    knowledge_evidence = [make_evidence("gdoc", "Doc text."), make_evidence("gsheet", "Sheet text.")]

    with patch("memoryAnswer.service.search_decisions", return_value=decide_evidence) as mock_decide, \
         patch("memoryAnswer.service.search_knowledge", return_value=knowledge_evidence) as mock_knowledge, \
         patch("memoryAnswer.service.score_confidence") as mock_score, \
         patch("memoryAnswer.service.compose_answer", return_value=("answer", mock_score.return_value)):
        MemoryAnswerService().answer("What is our budget?", "T123")

    mock_decide.assert_called_once_with("What is our budget?", "T123")
    mock_knowledge.assert_called_once_with("What is our budget?", "T123")
    forwarded_evidence = mock_score.call_args[0][0]
    assert forwarded_evidence == decide_evidence + knowledge_evidence


def test_answer_scores_confidence_from_combined_evidence():
    evidence = [make_evidence("gdoc")]
    confidence = ConfidenceResult(level="Medium", reason="Found in a single Google Doc.")

    with patch("memoryAnswer.service.search_decisions", return_value=[]), \
         patch("memoryAnswer.service.search_knowledge", return_value=evidence), \
         patch("memoryAnswer.service.score_confidence", return_value=confidence) as mock_score, \
         patch("memoryAnswer.service.compose_answer", return_value=("answer", confidence)) as mock_compose:
        MemoryAnswerService().answer("question?", "T123")

    mock_score.assert_called_once_with(evidence)
    assert mock_compose.call_args[0][2] is confidence


def test_answer_returns_compose_answer_text_and_final_confidence():
    initial_confidence = ConfidenceResult(level="Medium", reason="Not verified.", conflict="unclear")
    resolved_confidence = ConfidenceResult(level="High", reason="Corroborated by multiple sources: gdoc, gsheet.")

    with patch("memoryAnswer.service.search_decisions", return_value=[]), \
         patch("memoryAnswer.service.search_knowledge", return_value=[make_evidence("gdoc"), make_evidence("gsheet")]), \
         patch("memoryAnswer.service.score_confidence", return_value=initial_confidence), \
         patch("memoryAnswer.service.compose_answer", return_value=("The budget is $500.", resolved_confidence)):
        result = MemoryAnswerService().answer("What is our budget?", "T123")

    assert result == MemoryAnswer(answer="The budget is $500.", confidence=resolved_confidence)


def test_answer_forwards_question_and_workspace_id_to_compose_answer():
    with patch("memoryAnswer.service.search_decisions", return_value=[]), \
         patch("memoryAnswer.service.search_knowledge", return_value=[]), \
         patch("memoryAnswer.service.score_confidence", return_value=ConfidenceResult(level="Low", reason="No relevant evidence found.")), \
         patch("memoryAnswer.service.compose_answer", return_value=("no evidence", ConfidenceResult(level="Low", reason="No relevant evidence found."))) as mock_compose:
        MemoryAnswerService().answer("What is our budget?", "T123")

    assert mock_compose.call_args[0][0] == "What is our budget?"
    assert mock_compose.call_args[0][1] == []


def test_answer_handles_no_evidence_from_either_source():
    with patch("memoryAnswer.service.search_decisions", return_value=[]), \
         patch("memoryAnswer.service.search_knowledge", return_value=[]), \
         patch("memoryAnswer.service.score_confidence", return_value=ConfidenceResult(level="Low", reason="No relevant evidence found.")) as mock_score, \
         patch(
             "memoryAnswer.service.compose_answer",
             return_value=(
                 "I couldn't find relevant information in the club's records to answer that question.",
                 ConfidenceResult(level="Low", reason="No relevant evidence found."),
             ),
         ):
        result = MemoryAnswerService().answer("nonexistent topic", "T123")

    mock_score.assert_called_once_with([])
    assert "couldn't find" in result.answer.lower()
    assert result.confidence.level == "Low"
