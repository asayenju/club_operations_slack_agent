from types import SimpleNamespace

from ingestion_api import ingest_sheets


def test_build_chunks_skips_empty_rows():
    rows = [
        {"Name": "Alice", "Role": "President"},
        {"Name": "", "Role": ""},
        {"Name": "Bob", "Role": "Treasurer"},
    ]

    chunks = ingest_sheets.build_chunks(rows)

    assert len(chunks) == 2


def test_build_chunks_is_stable_when_rows_are_reordered():
    first = {"Name": "Alice", "Role": "President"}
    second = {"Name": "Bob", "Role": "Treasurer"}

    original = ingest_sheets.build_chunks([first, second])
    reordered = ingest_sheets.build_chunks([second, first])

    assert {chunk["chunk_key"] for chunk in original} == {
        chunk["chunk_key"] for chunk in reordered
    }


def test_ingest_sheet_skips_embedding_for_unchanged_rows(monkeypatch):
    rows = [{"Name": "Alice", "Role": "President"}]
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
    rows = [{"Name": "Alice", "Role": "President"}]
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
