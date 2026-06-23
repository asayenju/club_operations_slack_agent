from decisions.repository import SupabaseDocumentsRepository


class FakeDocumentsTable:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.selected = None
        self.filters = []
        self.limit_value = None

    def select(self, columns):
        self.selected = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        return type("Response", (), {"data": self.rows})()


class FakeSupabaseClient:
    def __init__(self, table):
        self.requested_tables = []
        self.documents_table = table

    def table(self, name):
        self.requested_tables.append(name)
        return self.documents_table


def test_find_by_chunk_key_scopes_lookup_by_workspace_and_source():
    table = FakeDocumentsTable(
        rows=[
            {
                "id": "doc-1",
                "content_hash": "hash",
                "chunk_key": "decide:hash:0000",
                "workspace_id": "T123",
                "source": "slack_decide",
            }
        ]
    )
    repository = SupabaseDocumentsRepository(FakeSupabaseClient(table))

    row = repository.find_by_chunk_key(
        "decide:hash:0000",
        workspace_id="T123",
        source="slack_decide",
    )

    assert row["id"] == "doc-1"
    assert table.selected == "id,content_hash,chunk_key,workspace_id,source"
    assert table.filters == [
        ("chunk_key", "decide:hash:0000"),
        ("workspace_id", "T123"),
        ("source", "slack_decide"),
    ]
    assert table.limit_value == 1
