from ingestion_api.drive_repository import SupabaseDriveRegistry


class FakeDriveSyncStateTable:
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
        self.table_instance = table
        self.requested_tables = []

    def table(self, name):
        self.requested_tables.append(name)
        return self.table_instance


def test_get_page_token_returns_none_when_cursor_row_missing():
    table = FakeDriveSyncStateTable(rows=[])
    registry = SupabaseDriveRegistry(FakeSupabaseClient(table))

    page_token = registry.get_page_token("T123")

    assert page_token is None
    assert table.selected == "page_token"
    assert table.filters == [("workspace_id", "T123")]
    assert table.limit_value == 1


def test_get_page_token_returns_none_when_cursor_value_missing():
    table = FakeDriveSyncStateTable(rows=[{"page_token": None}])
    registry = SupabaseDriveRegistry(FakeSupabaseClient(table))

    assert registry.get_page_token("T123") is None


def test_get_page_token_returns_stored_cursor():
    table = FakeDriveSyncStateTable(rows=[{"page_token": "token-1"}])
    registry = SupabaseDriveRegistry(FakeSupabaseClient(table))

    assert registry.get_page_token("T123") == "token-1"
