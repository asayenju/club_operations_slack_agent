from ingestion_api import documents_repo


class _FakeQuery:
    def __init__(self, recorder, method, data, *args, **kwargs):
        self._recorder = recorder
        self._data = data
        self._recorder.append((method, args, kwargs))

    def eq(self, *args, **kwargs):
        self._recorder.append(("eq", args, kwargs))
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


def test_delete_chunk_key_targets_exact_row(monkeypatch):
    calls = []
    monkeypatch.setattr(
        documents_repo, "get_supabase_client",
        lambda: _FakeClient(calls, [{"chunk_key": "C01:1"}]),
    )

    deleted = documents_repo.delete_chunk_key("T1", "slack", "C01", "C01:1")

    assert deleted == 1
    assert ("delete", (), {}) in calls
    assert ("eq", ("chunk_key", "C01:1"), {}) in calls
    # no full-key-set fetch — only the delete call itself hits the table
    assert not any(c[0] == "select" for c in calls)
