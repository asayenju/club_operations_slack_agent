from ingestion_api import documents_repo


class _FakeQuery:
    def __init__(self, recorder, method, *args, **kwargs):
        self._recorder = recorder
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
        return type("Resp", (), {"data": []})()


class _FakeTable:
    def __init__(self, recorder):
        self._recorder = recorder

    def upsert(self, *args, **kwargs):
        return _FakeQuery(self._recorder, "upsert", *args, **kwargs)

    def select(self, *args, **kwargs):
        return _FakeQuery(self._recorder, "select", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return _FakeQuery(self._recorder, "delete", *args, **kwargs)


class _FakeClient:
    def __init__(self, recorder):
        self._recorder = recorder

    def table(self, name):
        assert name == "documents"
        return _FakeTable(self._recorder)


def test_upsert_chunks_passes_composite_on_conflict(monkeypatch):
    calls = []
    monkeypatch.setattr(documents_repo, "_get_client", lambda: _FakeClient(calls))

    documents_repo.upsert_chunks([{"chunk_key": "C01:1"}])

    method, args, kwargs = calls[0]
    assert method == "upsert"
    assert kwargs.get("on_conflict") == "workspace_id,source,source_id,chunk_key"
