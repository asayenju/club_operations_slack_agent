from types import SimpleNamespace

from ingestion_api import ingest_docs


def test_split_text_never_truncates_content():
    text = "A" * 11

    parts = ingest_docs.split_text(text, limit=5)

    assert parts == ["AAAAA", "AAAAA", "A"]
    assert "".join(parts) == text


def test_build_chunks_is_stable_when_sections_are_reordered():
    first = {
        "heading_path": "Budget",
        "heading": "Budget",
        "text": "Approved amount is $500.",
    }
    second = {
        "heading_path": "Venue",
        "heading": "Venue",
        "text": "Use the student hall.",
    }

    original = ingest_docs.build_chunks([first, second])
    reordered = ingest_docs.build_chunks([second, first])

    assert {chunk["chunk_key"] for chunk in original} == {
        chunk["chunk_key"] for chunk in reordered
    }


def test_ingest_doc_embeds_only_new_chunks(monkeypatch):
    document = {
        "title": "Meeting Notes",
        "body": {
            "content": [
                {
                    "paragraph": {
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "elements": [{"textRun": {"content": "Budget\n"}}],
                    }
                },
                {
                    "paragraph": {
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "elements": [
                            {"textRun": {"content": "Approved amount is $500.\n"}}
                        ],
                    }
                },
            ]
        },
    }
    expected_chunk = ingest_docs.build_chunks(
        [
            {
                "heading_path": "Budget",
                "heading": "Budget",
                "text": "Approved amount is $500.",
            }
        ]
    )[0]
    upserted = []

    monkeypatch.setattr(
        ingest_docs,
        "get_ingestion_settings",
        lambda: SimpleNamespace(required_workspace_id="T123"),
    )
    monkeypatch.setattr(ingest_docs, "fetch_doc", lambda doc_id: document)
    monkeypatch.setattr(
        ingest_docs,
        "existing_keys",
        lambda workspace_id, source, source_id: {expected_chunk["chunk_key"]},
    )
    monkeypatch.setattr(
        ingest_docs,
        "embed_documents",
        lambda texts: (_ for _ in ()).throw(AssertionError("must not embed")),
    )
    monkeypatch.setattr(ingest_docs, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(
        ingest_docs,
        "delete_missing",
        lambda workspace_id, source, source_id, current_keys: 0,
    )

    result = ingest_docs.ingest_doc("doc-123")

    assert result["inserted_or_changed"] == 0
    assert result["unchanged"] == 1
    assert upserted == []
