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
    chunker = SentenceDecisionChunker(max_sentences=1, min_chunk_chars=1)

    chunks = chunker.chunk("We approved snacks. We picked Friday.")

    assert [chunk.text for chunk in chunks] == [
        "We approved snacks.",
        "We picked Friday.",
    ]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert [chunk.count for chunk in chunks] == [2, 2]


def test_sentence_chunker_splits_long_sentence_by_phrases():
    chunker = SentenceDecisionChunker(max_phrases=2, min_chunk_chars=1)

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
    chunker = SentenceDecisionChunker(max_sentences=2, min_chunk_chars=1)

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


def test_sentence_chunker_rejects_invalid_minimum_size():
    with pytest.raises(ValueError, match="min_chunk_chars"):
        SentenceDecisionChunker(min_chunk_chars=0)


def test_sentence_chunker_rejects_maximum_smaller_than_minimum():
    with pytest.raises(ValueError, match="max_chunk_chars"):
        SentenceDecisionChunker(min_chunk_chars=100, max_chunk_chars=99)


def test_sentence_chunker_protects_common_abbreviations():
    chunker = SentenceDecisionChunker(max_sentences=1, min_chunk_chars=1)

    chunks = chunker.chunk("Dr. Lee approved snacks. We picked Friday.")

    assert [chunk.text for chunk in chunks] == [
        "Dr. Lee approved snacks.",
        "We picked Friday.",
    ]


def test_sentence_chunker_preserves_single_newline_list_boundaries():
    text = (
        "- Allocate $300\n"
        "- Ask Dr. Lee"
    )
    chunker = SentenceDecisionChunker(max_sentences=2)

    chunks = chunker.chunk(text)

    assert [chunk.text for chunk in chunks] == [
        "- Allocate $300",
        "- Ask Dr. Lee",
    ]


def test_sentence_chunker_splits_long_unpunctuated_text_at_hard_limit():
    text = " ".join(f"word{index}" for index in range(300))
    chunker = SentenceDecisionChunker(max_chunk_chars=120, min_chunk_chars=1)

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 120 for chunk in chunks)


def test_sentence_chunker_splits_single_oversized_word_at_hard_limit():
    chunker = SentenceDecisionChunker(max_chunk_chars=120, min_chunk_chars=1)

    chunks = chunker.chunk("x" * 250)

    assert [len(chunk.text) for chunk in chunks] == [120, 120, 10]


def test_sentence_chunker_merges_undersized_trailing_fragments():
    chunker = SentenceDecisionChunker(max_phrases=2, min_chunk_chars=80)

    chunks = chunker.chunk(
        "We approved a complete outreach package, assigned Priya to ordering, "
        "and $300 for marketing."
    )

    assert [chunk.text for chunk in chunks] == [
        "We approved a complete outreach package, assigned Priya to ordering, and $300 for marketing."
    ]


def test_sentence_chunker_merges_short_final_sentence_into_previous_chunk():
    chunker = SentenceDecisionChunker(max_sentences=1, min_chunk_chars=80)

    chunks = chunker.chunk(
        "The executive board agreed to publish the final volunteer calendar by Friday. "
        "Effectively."
    )

    assert [chunk.text for chunk in chunks] == [
        "The executive board agreed to publish the final volunteer calendar by Friday. Effectively."
    ]
