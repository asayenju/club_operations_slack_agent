import re
from dataclasses import dataclass
from typing import Protocol

MIN_CHUNK_CHARS = 80
MAX_CHUNK_CHARS = 1200
_ABBREVIATIONS = (
    "Dr.",
    "Mr.",
    "Mrs.",
    "Ms.",
    "Prof.",
    "Sr.",
    "Jr.",
    "St.",
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
)
_DOT_PLACEHOLDER = "<DOT>"
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*]|\u2022|\d+[.)])\s+")


@dataclass(frozen=True)
class DecisionChunk:
    text: str
    index: int
    count: int


class DecisionChunker(Protocol):
    def chunk(self, text: str) -> list[DecisionChunk]:
        ...


class SentenceDecisionChunker:
    def __init__(
        self,
        max_sentences: int = 2,
        max_phrases: int = 4,
        min_chunk_chars: int = MIN_CHUNK_CHARS,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
    ):
        if max_sentences < 1:
            raise ValueError("max_sentences must be positive")
        if max_phrases < 1:
            raise ValueError("max_phrases must be positive")
        if min_chunk_chars < 1:
            raise ValueError("min_chunk_chars must be positive")
        if max_chunk_chars < min_chunk_chars:
            raise ValueError(
                "max_chunk_chars must be greater than or equal to min_chunk_chars"
            )
        self.max_sentences = max_sentences
        self.max_phrases = max_phrases
        self.min_chunk_chars = min_chunk_chars
        self.max_chunk_chars = max_chunk_chars

    def chunk(self, text: str) -> list[DecisionChunk]:
        packed: list[str] = []
        for section in _split_sections(text):
            packed.extend(
                _pack_sentences(
                    _split_sentences(section),
                    max_sentences=self.max_sentences,
                    max_phrases=self.max_phrases,
                    max_chunk_chars=self.max_chunk_chars,
                )
            )
        packed = _merge_undersized_chunks(
            packed,
            min_chunk_chars=self.min_chunk_chars,
            max_chunk_chars=self.max_chunk_chars,
        )

        count = len(packed)
        return [
            DecisionChunk(text=chunk, index=index, count=count)
            for index, chunk in enumerate(packed)
        ]


def _split_sections(text: str) -> list[str]:
    sections: list[str] = []
    for section in re.split(r"(?:\r?\n\s*){2,}", text.strip()):
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        if not lines:
            continue
        if any(_is_list_line(line) for line in lines):
            sections.extend(" ".join(line.split()) for line in lines)
        else:
            sections.append(" ".join(section.split()))
    return sections


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    protected = _protect_abbreviations(normalized)
    return [
        _restore_abbreviations(sentence.strip())
        for sentence in re.split(r"(?<=[.!?])\s+", protected)
        if sentence.strip()
    ]


def _pack_sentences(
    sentences: list[str],
    max_sentences: int,
    max_phrases: int,
    max_chunk_chars: int,
) -> list[str]:
    packed: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        phrases = _split_phrases(sentence)
        sentence_chunks = _pack_phrases(
            phrases,
            max_phrases=max_phrases,
            max_chunk_chars=max_chunk_chars,
        )
        if len(phrases) > max_phrases or len(sentence) > max_chunk_chars:
            if current:
                packed.append(" ".join(current))
                current = []
            packed.extend(sentence_chunks)
            continue

        candidate = " ".join([*current, sentence])
        if len(current) >= max_sentences or len(candidate) > max_chunk_chars:
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


def _pack_phrases(
    phrases: list[str],
    max_phrases: int,
    max_chunk_chars: int,
) -> list[str]:
    packed: list[str] = []
    current: list[str] = []

    for phrase in phrases:
        if len(phrase) > max_chunk_chars:
            if current:
                packed.append(" ".join(current))
                current = []
            packed.extend(_split_oversized_text(phrase, max_chunk_chars))
            continue

        candidate = " ".join([*current, phrase])
        if current and (
            len(current) >= max_phrases or len(candidate) > max_chunk_chars
        ):
            packed.append(" ".join(current))
            current = [phrase]
        else:
            current.append(phrase)

    if current:
        packed.append(" ".join(current))

    return packed


def _split_oversized_text(text: str, max_chunk_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""

    for word in text.split():
        if len(word) > max_chunk_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                word[index : index + max_chunk_chars]
                for index in range(0, len(word), max_chunk_chars)
            )
            continue

        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chunk_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def _merge_undersized_chunks(
    chunks: list[str],
    min_chunk_chars: int,
    max_chunk_chars: int,
) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        if (
            len(chunk) < min_chunk_chars
            and index + 1 < len(chunks)
            and not _is_list_line(chunk)
            and not _is_list_line(chunks[index + 1])
            and len(f"{chunk} {chunks[index + 1]}") <= max_chunk_chars
        ):
            merged.append(f"{chunk} {chunks[index + 1]}")
            index += 2
            continue

        if (
            len(chunk) < min_chunk_chars
            and merged
            and not _is_list_line(chunk)
            and not _is_list_line(merged[-1])
            and len(f"{merged[-1]} {chunk}") <= max_chunk_chars
        ):
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
        index += 1

    return merged


def _protect_abbreviations(text: str) -> str:
    protected = text
    for abbreviation in _ABBREVIATIONS:
        protected = re.sub(
            re.escape(abbreviation),
            lambda match: match.group(0).replace(".", _DOT_PLACEHOLDER),
            protected,
            flags=re.IGNORECASE,
        )
    return protected


def _restore_abbreviations(text: str) -> str:
    return text.replace(_DOT_PLACEHOLDER, ".")


def _is_list_line(line: str) -> bool:
    return bool(_LIST_MARKER_RE.match(line))
