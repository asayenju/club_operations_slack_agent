from types import SimpleNamespace

from common.workspace_admin_settings import WorkspaceAdminSettingsStore


class _FakeTable:
    def __init__(self, rows_by_workspace):
        self._rows = rows_by_workspace
        self._filters: dict = {}
        self._pending_upsert = None
        self._pending_insert = None
        self._pending_delete = False

    def select(self, *_args):
        return self

    def upsert(self, row, on_conflict=None):
        self._pending_upsert = row
        return self

    def insert(self, row):
        self._pending_insert = row
        return self

    def delete(self):
        self._pending_delete = True
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def execute(self):
        if self._pending_upsert is not None:
            existing = self._rows.get(self._pending_upsert["workspace_id"], {})
            merged = {**existing, **self._pending_upsert}
            self._rows[self._pending_upsert["workspace_id"]] = merged
            return SimpleNamespace(data=[merged])
        if self._pending_insert is not None:
            self._rows[self._pending_insert["workspace_id"]] = self._pending_insert
            return SimpleNamespace(data=[self._pending_insert])
        if self._pending_delete:
            workspace_id = self._filters.get("workspace_id")
            removed = self._rows.pop(workspace_id, None)
            return SimpleNamespace(data=[removed] if removed else [])
        workspace_id = self._filters.get("workspace_id")
        row = self._rows.get(workspace_id)
        return SimpleNamespace(data=[row] if row else [])


class _FakeSupabase:
    def __init__(self):
        self.rows: dict = {}

    def table(self, name):
        assert name == "workspace_admin_settings"
        return _FakeTable(self.rows)


def test_get_returns_defaults_for_unconfigured_workspace():
    store = WorkspaceAdminSettingsStore(_FakeSupabase())

    settings = store.get("T_UNKNOWN", app_env="production")

    assert settings.drive_sync_admin_user_ids is None
    assert settings.reconciliation_approval_user_ids is None
    assert settings.reconciliation_approval_reaction == "white_check_mark"
    assert settings.app_env == "production"


def test_ensure_default_admin_seeds_installer_as_admin_for_both_lists():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)

    store.ensure_default_admin("T123", "U_INSTALLER")
    settings = store.get("T123")

    assert settings.drive_sync_admin_user_ids == "U_INSTALLER"
    assert settings.reconciliation_approval_user_ids == "U_INSTALLER"


def test_ensure_default_admin_does_not_clobber_existing_settings():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)
    store.set_drive_sync_admins("T123", ["U_CUSTOM"])

    store.ensure_default_admin("T123", "U_INSTALLER")

    assert store.get("T123").drive_sync_admin_user_ids == "U_CUSTOM"


def test_ensure_default_admin_is_noop_without_user_id():
    store = WorkspaceAdminSettingsStore(_FakeSupabase())

    store.ensure_default_admin("T123", None)

    assert store.get("T123").drive_sync_admin_user_ids is None


def test_set_drive_sync_admins_updates_only_that_field():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)
    store.ensure_default_admin("T123", "U1")

    store.set_drive_sync_admins("T123", ["U2", "U3"])

    settings = store.get("T123")
    assert settings.drive_sync_admin_user_ids == "U2,U3"
    assert settings.reconciliation_approval_user_ids == "U1"


def test_backfill_missing_defaults_seeds_both_fields_when_no_row_exists():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)

    seeded = store.backfill_missing_defaults("T_NEW", "U_INSTALLER")

    assert seeded is True
    settings = store.get("T_NEW")
    assert settings.drive_sync_admin_user_ids == "U_INSTALLER"
    assert settings.reconciliation_approval_user_ids == "U_INSTALLER"


def test_backfill_missing_defaults_fills_only_the_unset_field():
    """Issue #75 review (Aman): ensure_default_admin() no-ops the moment a
    row exists at all, so a workspace with drive_sync_admin_user_ids set by
    hand but reconciliation_approval_user_ids still null was skipped
    entirely instead of getting the missing field backfilled."""
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)
    store.set_drive_sync_admins("T_PARTIAL", ["U_CUSTOM"])

    seeded = store.backfill_missing_defaults("T_PARTIAL", "U_INSTALLER")

    assert seeded is True
    settings = store.get("T_PARTIAL")
    assert settings.drive_sync_admin_user_ids == "U_CUSTOM"
    assert settings.reconciliation_approval_user_ids == "U_INSTALLER"


def test_backfill_missing_defaults_is_noop_when_both_fields_already_set():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)
    store.ensure_default_admin("T_FULL", "U_ORIGINAL")

    seeded = store.backfill_missing_defaults("T_FULL", "U_INSTALLER")

    assert seeded is False
    settings = store.get("T_FULL")
    assert settings.drive_sync_admin_user_ids == "U_ORIGINAL"
    assert settings.reconciliation_approval_user_ids == "U_ORIGINAL"


def test_backfill_missing_defaults_is_noop_without_user_id():
    store = WorkspaceAdminSettingsStore(_FakeSupabase())

    seeded = store.backfill_missing_defaults("T123", None)

    assert seeded is False
    assert store.get("T123").drive_sync_admin_user_ids is None


def test_delete_removes_a_workspaces_admin_settings():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)
    store.ensure_default_admin("T123", "U1")

    store.delete("T123")

    assert store.get("T123").drive_sync_admin_user_ids is None


def test_two_workspaces_have_independent_admin_lists():
    supabase = _FakeSupabase()
    store = WorkspaceAdminSettingsStore(supabase)

    store.ensure_default_admin("T_A", "U_A")
    store.ensure_default_admin("T_B", "U_B")
    store.set_drive_sync_admins("T_A", ["U_A", "U_A2"])

    assert store.get("T_A").drive_sync_admin_user_ids == "U_A,U_A2"
    assert store.get("T_B").drive_sync_admin_user_ids == "U_B"
