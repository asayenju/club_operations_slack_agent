import pytest

from decisions.chunking import SentenceDecisionChunker


def test_sentence_chunker_packs_short_sentences():
    chunker = SentenceDecisionChunker(max_sentences=2)

    chunks = chunker.chunk("We approved snacks. We picked Friday!")

    assert [chunk.text for chunk in chunks] == [
        "We approved snacks. We picked Friday!",
    ]
    assert chunks[0].index == 0
    assert chunks[0].count == 1


def test_sentence_chunker_starts_new_chunk_at_sentence_limit():
    chunker = SentenceDecisionChunker(max_sentences=1)

    chunks = chunker.chunk("We approved snacks. We picked Friday.")

    assert [chunk.text for chunk in chunks] == [
        "We approved snacks.",
        "We picked Friday.",
    ]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert [chunk.count for chunk in chunks] == [2, 2]


def test_sentence_chunker_splits_long_sentence_by_phrases():
    chunker = SentenceDecisionChunker(max_phrases=2)

    chunks = chunker.chunk(
        "We approved snacks, assigned Mira to ordering, set a Friday deadline, and capped spending at $300."
    )

    assert [chunk.text for chunk in chunks] == [
        "We approved snacks, assigned Mira to ordering,",
        "set a Friday deadline, and capped spending at $300.",
    ]


def test_sentence_chunker_normalizes_whitespace():
    chunker = SentenceDecisionChunker(max_sentences=2)

    chunks = chunker.chunk("  We   approved\nsnacks.   ")

    assert [chunk.text for chunk in chunks] == ["We approved snacks."]


def test_sentence_chunker_keeps_blank_line_sections_separate():
    text = """
The club has agreed to allocate a portion of its budget toward new equipment to enhance member experience and support upcoming activities. Final purchases will be determined after reviewing member suggestions.

We will collaborate with other student organizations this semester to host joint events and expand our reach within the campus community. Coordination teams will be assigned to manage these partnerships.

To improve efficiency, the club will implement a structured leadership system with clearly defined roles and responsibilities for each executive member.
"""
    chunker = SentenceDecisionChunker()

    chunks = chunker.chunk(text)

    assert [chunk.text for chunk in chunks] == [
        "The club has agreed to allocate a portion of its budget toward new equipment to enhance member experience and support upcoming activities. Final purchases will be determined after reviewing member suggestions.",
        "We will collaborate with other student organizations this semester to host joint events and expand our reach within the campus community. Coordination teams will be assigned to manage these partnerships.",
        "To improve efficiency, the club will implement a structured leadership system with clearly defined roles and responsibilities for each executive member.",
    ]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]
    assert [chunk.count for chunk in chunks] == [3, 3, 3]


def test_sentence_chunker_splits_large_sections_into_sentence_groups():
    text = (
        "Sentence one has five words. "
        "Sentence two has five words. "
        "Sentence three has five words. "
        "Sentence four has five words."
    )
    chunker = SentenceDecisionChunker(max_sentences=2)

    chunks = chunker.chunk(text)

    assert [chunk.text for chunk in chunks] == [
        "Sentence one has five words. Sentence two has five words.",
        "Sentence three has five words. Sentence four has five words.",
    ]


def test_sentence_chunker_rejects_invalid_sentence_limit():
    with pytest.raises(ValueError, match="max_sentences"):
        SentenceDecisionChunker(max_sentences=0)


def test_sentence_chunker_rejects_invalid_phrase_limit():
    with pytest.raises(ValueError, match="max_phrases"):
        SentenceDecisionChunker(max_phrases=0)
