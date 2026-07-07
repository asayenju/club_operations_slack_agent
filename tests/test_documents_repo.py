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


class _FakeQuery:
    def __init__(self, recorder, method, data, *args, **kwargs):
        self._recorder = recorder
        self._data = data
        self._recorder.append((method, args, kwargs))

    def eq(self, *args, **kwargs):
        self._recorder.append(("eq", args, kwargs))
        return self

    def gte(self, *args, **kwargs):
        self._recorder.append(("gte", args, kwargs))
        return self

    def in_(self, *args, **kwargs):
        self._recorder.append(("in_", args, kwargs))
        return self

    def select(self, *args, **kwargs):
        self._recorder.append(("select", args, kwargs))
        return self

    def execute(self):
        return type("Resp", (), {"data": self._data})()


class _FakeTable:
    def __init__(self, recorder, data):
        self._recorder = recorder
        self._data = data

    def upsert(self, *args, **kwargs):
        return _FakeQuery(self._recorder, "upsert", self._data, *args, **kwargs)

    def select(self, *args, **kwargs):
        return _FakeQuery(self._recorder, "select", self._data, *args, **kwargs)

    def delete(self, *args, **kwargs):
        return _FakeQuery(self._recorder, "delete", self._data, *args, **kwargs)


class _FakeClient:
    def __init__(self, recorder, data=None):
        self._recorder = recorder
        self._data = data if data is not None else []

    def table(self, name):
        assert name == "documents"
        return _FakeTable(self._recorder, self._data)


def test_upsert_chunks_passes_composite_on_conflict(monkeypatch):
    calls = []
    monkeypatch.setattr(documents_repo, "get_supabase_client", lambda: _FakeClient(calls))

    documents_repo.upsert_chunks([{"chunk_key": "C01:1"}])

    method, args, kwargs = calls[0]
    assert method == "upsert"
    assert kwargs.get("on_conflict") == "workspace_id,source,source_id,chunk_key"


def test_existing_key_state_combines_hash_and_metadata_in_one_query(monkeypatch):
    calls = []
    rows = [
        {"chunk_key": "C01:1", "content_hash": "h1", "metadata": {"a": 1}},
        {"chunk_key": "C01:2", "content_hash": "h2", "metadata": None},
    ]
    monkeypatch.setattr(documents_repo, "get_supabase_client", lambda: _FakeClient(calls, rows))

    result = documents_repo.existing_key_state("T1", "slack", "C01")

    assert result == {
        "C01:1": {"content_hash": "h1", "metadata": {"a": 1}},
        "C01:2": {"content_hash": "h2", "metadata": {}},
    }
    # exactly one select call for both columns, not two separate queries
    select_calls = [c for c in calls if c[0] == "select"]
    assert len(select_calls) == 1
    assert select_calls[0][1] == ("chunk_key,content_hash,metadata",)


def test_list_by_source_filters_workspace_and_source(monkeypatch):
    calls = []
    rows = [{"source": "slack_decide", "content": "We approved $300."}]
    monkeypatch.setattr(documents_repo, "get_supabase_client", lambda: _FakeClient(calls, rows))

    result = documents_repo.list_by_source("T1", "slack_decide")

    assert result == rows
    assert ("eq", ("workspace_id", "T1"), {}) in calls
    assert ("eq", ("source", "slack_decide"), {}) in calls
    assert not any(c[0] == "gte" for c in calls)


def test_list_by_source_applies_since_filter_only_when_given(monkeypatch):
    calls = []
    monkeypatch.setattr(documents_repo, "get_supabase_client", lambda: _FakeClient(calls, []))

    documents_repo.list_by_source("T1", "slack_decide", since="2026-06-01T00:00:00+00:00")

    assert ("gte", ("created_at", "2026-06-01T00:00:00+00:00"), {}) in calls


def test_list_by_source_returns_empty_list_for_no_rows(monkeypatch):
    monkeypatch.setattr(documents_repo, "get_supabase_client", lambda: _FakeClient([], None))

    assert documents_repo.list_by_source("T1", "slack_decide") == []


def test_delete_chunk_key_targets_exact_row(monkeypatch):
    calls = []
    monkeypatch.setattr(
        documents_repo,
        "get_supabase_client",
        lambda: _FakeClient(calls, [{"chunk_key": "C01:1"}]),
    )

    deleted = documents_repo.delete_chunk_key("T1", "slack", "C01", "C01:1")

    assert deleted == 1
    assert ("delete", (), {}) in calls
    assert ("eq", ("chunk_key", "C01:1"), {}) in calls
    # no full-key-set fetch — only the delete call itself hits the table
    assert not any(c[0] == "select" for c in calls)
