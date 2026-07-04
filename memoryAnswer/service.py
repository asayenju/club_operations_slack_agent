from dataclasses import dataclass, field
from typing import Protocol


class MemoryRetriever(Protocol):
    def search(self, question: str, workspace_id: str) -> list[dict]:
        ...


@dataclass
class MemoryAnswer:
    answer: str
    sources: list[str] = field(default_factory=list)
    confidence: str = "low"


class MockMemoryRetriever:
    def search(self, question: str, workspace_id: str) -> list[dict]:
        return []


class MemoryAnswerService:
    def __init__(self, retriever: MemoryRetriever | None = None):
        self.retriever = retriever or MockMemoryRetriever()

    def answer(self, question: str, workspace_id: str) -> MemoryAnswer:
        self.retriever.search(question, workspace_id)
        return MemoryAnswer(
            answer="This is a placeholder answer. Memory search is not yet implemented.",
            sources=[],
            confidence="low",
        )
