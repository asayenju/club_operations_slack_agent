from types import SimpleNamespace

from ingestion_api import ingest_sheets


def test_build_chunks_skips_empty_rows():
    rows = [
        {"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": "Alice"},
        {"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": ""},
    ]

    chunks = ingest_sheets.build_chunks(rows)

    assert len(chunks) == 1


def test_build_chunks_identity_survives_row_reordering():
    alice = {"__tab_id__": "1", "__tab_name__": "Members", "Name": "Alice"}
    bob = {"__tab_id__": "1", "__tab_name__": "Members", "Name": "Bob"}

    original = ingest_sheets.build_chunks([alice, bob])
    reordered = ingest_sheets.build_chunks([bob, alice])

    assert {chunk["chunk_key"] for chunk in original} == {
        chunk["chunk_key"] for chunk in reordered
    }
    assert [chunk["row_index"] for chunk in original] == [0, 1]


def test_build_chunks_preserves_identical_duplicate_rows():
    row = {"__tab_id__": "1", "__tab_name__": "Members", "Name": "Alice"}

    chunks = ingest_sheets.build_chunks([row, row])

    assert len(chunks) == 2
    assert chunks[0]["chunk_key"] != chunks[1]["chunk_key"]


def test_ingest_sheet_fully_replaces_existing_rows(monkeypatch):
    rows = [
        {
            "__tab_id__": "1",
            "__tab_name__": "Members",
            "Name": "Alice",
            "Role": "President",
        }
    ]
    replaced = []

    monkeypatch.setattr(
        ingest_sheets,
        "get_ingestion_settings",
        lambda: SimpleNamespace(required_workspace_id="T123"),
    )
    monkeypatch.setattr(ingest_sheets, "fetch_sheet_rows", lambda sheet_id: rows)
    monkeypatch.setattr(
        ingest_sheets,
        "embed_documents",
        lambda texts: [[0.1] * 1024 for _ in texts],
    )

    def fake_replace(workspace_id, source, source_id, payloads):
        replaced.extend(payloads)
        return 3

    monkeypatch.setattr(
        ingest_sheets,
        "replace_source_chunks",
        fake_replace,
    )

    result = ingest_sheets.ingest_sheet("sheet-123")

    assert result == {
        "sheet_id": "sheet-123",
        "inserted_or_changed": 1,
        "unchanged": 0,
        "deleted": 3,
        "total": 1,
    }
    assert replaced[0]["metadata"]["row_index"] == 0
    assert replaced[0]["metadata"]["tab_name"] == "Members"
