import pytest

from ingestion_api import documents_repo


def test_replace_source_chunks_writes_before_deleting_stale_keys(monkeypatch):
    calls = []
    rows = [{"chunk_key": "tab:hash-new"}]

    monkeypatch.setattr(
        documents_repo,
        "upsert_chunks",
        lambda payloads: calls.append(("upsert", payloads)),
    )
    monkeypatch.setattr(
        documents_repo,
        "delete_missing",
        lambda workspace_id, source, source_id, current_keys: calls.append(
            ("delete_missing", workspace_id, source, source_id, current_keys)
        ) or 2,
    )

    deleted = documents_repo.replace_source_chunks(
        "T123",
        "gsheet",
        "sheet-123",
        rows,
    )

    assert deleted == 2
    assert calls == [
        ("upsert", rows),
        ("delete_missing", "T123", "gsheet", "sheet-123", {"tab:hash-new"}),
    ]


def test_replace_source_chunks_preserves_existing_rows_when_upsert_fails(monkeypatch):
    calls = []

    def fail_upsert(_rows):
        calls.append("upsert")
        raise RuntimeError("supabase down")

    monkeypatch.setattr(documents_repo, "upsert_chunks", fail_upsert)
    monkeypatch.setattr(
        documents_repo,
        "delete_missing",
        lambda *args: calls.append("delete_missing"),
    )

    with pytest.raises(RuntimeError, match="supabase down"):
        documents_repo.replace_source_chunks(
            "T123",
            "gsheet",
            "sheet-123",
            [{"chunk_key": "tab:hash-new"}],
        )

    assert calls == ["upsert"]
