from types import SimpleNamespace

from ingestion_api import ingest_sheets


def test_build_chunks_skips_empty_rows():
    rows = [
        {"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": "Alice", "Role": "President"},
        {"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": "", "Role": ""},
        {"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": "Bob", "Role": "Treasurer"},
    ]

    chunks = ingest_sheets.build_chunks(rows)

    assert len(chunks) == 2


def test_build_chunks_separates_rows_from_different_tabs():
    rows = [
        {"__tab_id__": "111", "__tab_name__": "Members", "Name": "Alice"},
        {"__tab_id__": "222", "__tab_name__": "Budget", "Name": "Alice"},
    ]

    chunks = ingest_sheets.build_chunks(rows)

    keys = {chunk["chunk_key"] for chunk in chunks}
    assert any(k.startswith("111:") for k in keys)
    assert any(k.startswith("222:") for k in keys)


def test_ingest_sheet_skips_embedding_for_unchanged_rows(monkeypatch):
    rows = [{"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": "Alice", "Role": "President"}]
    existing_chunk = ingest_sheets.build_chunks(rows)[0]
    upserted = []

    monkeypatch.setattr(
        ingest_sheets,
        "get_ingestion_settings",
        lambda: SimpleNamespace(required_workspace_id="T123"),
    )
    monkeypatch.setattr(ingest_sheets, "fetch_sheet_rows", lambda sheet_id: rows)
    monkeypatch.setattr(
        ingest_sheets,
        "existing_keys",
        lambda workspace_id, source, source_id: {existing_chunk["chunk_key"]},
    )
    monkeypatch.setattr(
        ingest_sheets,
        "embed_documents",
        lambda texts: (_ for _ in ()).throw(AssertionError("must not embed")),
    )
    monkeypatch.setattr(ingest_sheets, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(
        ingest_sheets,
        "delete_missing",
        lambda workspace_id, source, source_id, current_keys: 0,
    )

    result = ingest_sheets.ingest_sheet("sheet-123")

    assert result["inserted_or_changed"] == 0
    assert result["unchanged"] == 1
    assert upserted == []


def test_ingest_sheet_embeds_new_rows(monkeypatch):
    rows = [{"__tab_id__": "1", "__tab_name__": "Sheet1", "Name": "Alice", "Role": "President"}]
    upserted = []

    monkeypatch.setattr(
        ingest_sheets,
        "get_ingestion_settings",
        lambda: SimpleNamespace(required_workspace_id="T123"),
    )
    monkeypatch.setattr(ingest_sheets, "fetch_sheet_rows", lambda sheet_id: rows)
    monkeypatch.setattr(
        ingest_sheets,
        "existing_keys",
        lambda workspace_id, source, source_id: set(),
    )
    monkeypatch.setattr(
        ingest_sheets,
        "embed_documents",
        lambda texts: [[0.1] * 1024 for _ in texts],
    )
    monkeypatch.setattr(ingest_sheets, "upsert_chunks", upserted.extend)
    monkeypatch.setattr(
        ingest_sheets,
        "delete_missing",
        lambda workspace_id, source, source_id, current_keys: 0,
    )

    result = ingest_sheets.ingest_sheet("sheet-123")

    assert result["inserted_or_changed"] == 1
    assert result["unchanged"] == 0
    assert len(upserted) == 1
