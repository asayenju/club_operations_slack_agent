import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DecisionChunk:
    text: str
    index: int
    count: int


class DecisionChunker(Protocol):
    def chunk(self, text: str) -> list[DecisionChunk]:
        ...


class SentenceDecisionChunker:
    def __init__(self, max_sentences: int = 2, max_phrases: int = 4):
        if max_sentences < 1:
            raise ValueError("max_sentences must be positive")
        if max_phrases < 1:
            raise ValueError("max_phrases must be positive")
        self.max_sentences = max_sentences
        self.max_phrases = max_phrases

    def chunk(self, text: str) -> list[DecisionChunk]:
        packed: list[str] = []
        for section in _split_sections(text):
            packed.extend(
                _pack_sentences(
                    _split_sentences(section),
                    max_sentences=self.max_sentences,
                    max_phrases=self.max_phrases,
                )
            )

        count = len(packed)
        return [
            DecisionChunk(text=chunk, index=index, count=count)
            for index, chunk in enumerate(packed)
        ]


def _split_sections(text: str) -> list[str]:
    return [
        " ".join(section.split())
        for section in re.split(r"(?:\r?\n\s*){2,}", text.strip())
        if section.strip()
    ]


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]


def _pack_sentences(
    sentences: list[str],
    max_sentences: int,
    max_phrases: int,
) -> list[str]:
    packed: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        phrases = _split_phrases(sentence)
        if len(phrases) > max_phrases:
            if current:
                packed.append(" ".join(current))
                current = []
            packed.extend(_pack_phrases(phrases, max_phrases))
            continue

        if len(current) >= max_sentences:
            packed.append(" ".join(current))
            current = [sentence]
        else:
            current.append(sentence)

    if current:
        packed.append(" ".join(current))

    return packed


def _split_phrases(sentence: str) -> list[str]:
    phrases = [
        phrase.strip()
        for phrase in re.findall(r"[^,;:]+[,;:]?", sentence)
        if phrase.strip()
    ]
    return phrases or [sentence]


def _pack_phrases(phrases: list[str], max_phrases: int) -> list[str]:
    return [
        " ".join(phrases[index : index + max_phrases])
        for index in range(0, len(phrases), max_phrases)
    ]
