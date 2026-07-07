from dataclasses import dataclass

from memoryAnswer.composer import compose_answer
from tools.confidence import ConfidenceResult, score_confidence
from tools.vector_search import search_decisions, search_knowledge


@dataclass
class MemoryAnswer:
    answer: str
    confidence: ConfidenceResult


class MemoryAnswerService:
    def answer(self, question: str, workspace_id: str) -> MemoryAnswer:
        evidence = search_decisions(question, workspace_id) + search_knowledge(question, workspace_id)
        confidence = score_confidence(evidence)
        answer_text, final_confidence = compose_answer(question, evidence, confidence)
        return MemoryAnswer(answer=answer_text, confidence=final_confidence)
