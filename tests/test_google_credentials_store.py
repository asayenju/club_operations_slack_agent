from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from common import crypto
from common.google_credentials_store import (
    GoogleDriveNotConnected,
    WorkspaceGoogleCredentialsStore,
    get_google_credentials,
)


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    crypto._fernet.cache_clear()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    yield
    crypto._fernet.cache_clear()


class _FakeTable:
    def __init__(self, rows_by_workspace):
        self._rows = rows_by_workspace
        self._filters: dict = {}
        self._pending_upsert = None
        self._pending_delete = False

    def upsert(self, row, on_conflict=None):
        self._pending_upsert = row
        return self

    def select(self, *_args):
        return self

    def delete(self):
        self._pending_delete = True
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def execute(self):
        if self._pending_upsert is not None:
            self._rows[self._pending_upsert["workspace_id"]] = self._pending_upsert
            return SimpleNamespace(data=[self._pending_upsert])
        if self._pending_delete:
            self._rows.pop(self._filters.get("workspace_id"), None)
            return SimpleNamespace(data=[])
        if not self._filters:
            return SimpleNamespace(data=list(self._rows.values()))
        workspace_id = self._filters.get("workspace_id")
        row = self._rows.get(workspace_id)
        return SimpleNamespace(data=[row] if row else [])


class _FakeSupabase:
    def __init__(self):
        self.rows: dict = {}

    def table(self, name):
        assert name == "workspace_google_credentials"
        return _FakeTable(self.rows)


def test_save_then_get_round_trips_and_decrypts_refresh_token():
    supabase = _FakeSupabase()
    store = WorkspaceGoogleCredentialsStore(supabase)

    store.save("T123", "refresh-secret", ["drive.readonly"], connected_by_user_id="U1")
    result = store.get("T123")

    assert result is not None
    assert result.refresh_token == "refresh-secret"
    assert result.scopes == ["drive.readonly"]
    assert result.connected_by_user_id == "U1"


def test_refresh_token_is_encrypted_at_rest():
    supabase = _FakeSupabase()
    store = WorkspaceGoogleCredentialsStore(supabase)

    store.save("T123", "refresh-secret", ["drive.readonly"])

    stored_row = supabase.rows["T123"]
    assert "refresh-secret" not in stored_row["refresh_token_encrypted"]
    assert crypto.decrypt(stored_row["refresh_token_encrypted"]) == "refresh-secret"


def test_get_returns_none_for_unconnected_workspace():
    store = WorkspaceGoogleCredentialsStore(_FakeSupabase())

    assert store.get("T_UNKNOWN") is None
    assert store.is_connected("T_UNKNOWN") is False


def test_two_workspaces_do_not_see_each_other_credentials():
    supabase = _FakeSupabase()
    store = WorkspaceGoogleCredentialsStore(supabase)

    store.save("T_A", "refresh-a", ["drive.readonly"])
    store.save("T_B", "refresh-b", ["drive.readonly"])

    assert store.get("T_A").refresh_token == "refresh-a"
    assert store.get("T_B").refresh_token == "refresh-b"


def test_list_workspace_ids_returns_every_connected_workspace():
    supabase = _FakeSupabase()
    store = WorkspaceGoogleCredentialsStore(supabase)
    store.save("T_A", "refresh-a", ["drive.readonly"])
    store.save("T_B", "refresh-b", ["drive.readonly"])

    assert sorted(store.list_workspace_ids()) == ["T_A", "T_B"]


def test_list_workspace_ids_empty_when_none_connected():
    store = WorkspaceGoogleCredentialsStore(_FakeSupabase())

    assert store.list_workspace_ids() == []


def test_delete_removes_the_row():
    supabase = _FakeSupabase()
    store = WorkspaceGoogleCredentialsStore(supabase)
    store.save("T123", "refresh-secret", ["drive.readonly"])

    store.delete("T123")

    assert store.get("T123") is None


def test_get_google_credentials_raises_when_not_connected(monkeypatch):
    with pytest.raises(GoogleDriveNotConnected, match="T_UNKNOWN"):
        get_google_credentials("T_UNKNOWN", ["drive.readonly"], supabase_client=_FakeSupabase())


def test_get_google_credentials_builds_refreshable_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    from common.config import get_ingestion_settings
    get_ingestion_settings.cache_clear()

    supabase = _FakeSupabase()
    store = WorkspaceGoogleCredentialsStore(supabase)
    store.save("T123", "refresh-secret", ["drive.readonly"])

    credentials = get_google_credentials("T123", ["drive.readonly"], supabase_client=supabase)

    assert credentials.refresh_token == "refresh-secret"
    assert credentials.client_id == "client-id"
    assert credentials.client_secret == "client-secret"
    assert credentials.token_uri == "https://oauth2.googleapis.com/token"
    get_ingestion_settings.cache_clear()
