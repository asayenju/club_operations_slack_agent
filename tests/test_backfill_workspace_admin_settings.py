from types import SimpleNamespace

from tools import backfill_workspace_admin_settings as backfill


class _FakeInstallationsTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _FakeSupabase:
    def __init__(self, installation_rows):
        self._installation_rows = installation_rows

    def table(self, name):
        assert name == "slack_installations"
        return _FakeInstallationsTable(self._installation_rows)


def _patch_common(monkeypatch, supabase, admin_store):
    monkeypatch.setattr(backfill, "get_ingestion_settings", lambda: SimpleNamespace(
        required_supabase_url="http://fake", required_supabase_service_key="fake.fake.fake",
    ))
    import supabase as supabase_module
    monkeypatch.setattr(supabase_module, "create_client", lambda url, key: supabase)
    monkeypatch.setattr(backfill, "WorkspaceAdminSettingsStore", lambda supabase: admin_store)


class _FakeAdminStore:
    """already_fully_configured: workspaces with both fields already set --
    backfill_missing_defaults() is a no-op for these. partially_configured:
    workspaces with a settings row but only one field set -- Aman's #75
    review: the old implementation skipped these entirely instead of
    backfilling just the missing field."""

    def __init__(self, already_fully_configured=(), partially_configured=()):
        self.already_fully_configured = set(already_fully_configured)
        self.partially_configured = set(partially_configured)
        self.seeded_calls = []

    def backfill_missing_defaults(self, workspace_id, user_id):
        if workspace_id in self.already_fully_configured:
            return False
        self.seeded_calls.append((workspace_id, user_id))
        return True


def test_backfill_seeds_workspaces_missing_admin_settings(monkeypatch, capsys):
    installation_rows = [
        {"team_id": "T_A", "installed_by_user_id": "U_A"},
        {"team_id": "T_B", "installed_by_user_id": "U_B"},
    ]
    supabase = _FakeSupabase(installation_rows)
    admin_store = _FakeAdminStore()
    _patch_common(monkeypatch, supabase, admin_store)

    backfill.main()

    assert admin_store.seeded_calls == [("T_A", "U_A"), ("T_B", "U_B")]
    assert "2 seeded, 0 skipped" in capsys.readouterr().out


def test_backfill_skips_workspaces_that_already_have_settings(monkeypatch, capsys):
    installation_rows = [
        {"team_id": "T_A", "installed_by_user_id": "U_A"},
        {"team_id": "T_B", "installed_by_user_id": "U_B"},
    ]
    supabase = _FakeSupabase(installation_rows)
    admin_store = _FakeAdminStore(already_fully_configured={"T_A"})
    _patch_common(monkeypatch, supabase, admin_store)

    backfill.main()

    assert admin_store.seeded_calls == [("T_B", "U_B")]
    assert "1 seeded, 1 skipped" in capsys.readouterr().out


def test_backfill_fills_missing_field_for_partially_configured_workspace(monkeypatch, capsys):
    """Issue #75 review (Aman): a workspace that already has one admin field
    set (e.g. drive_sync_admin_user_ids from a manual set_drive_sync_admins()
    call) but not the other must still get the missing field backfilled,
    not be skipped outright."""
    installation_rows = [{"team_id": "T_PARTIAL", "installed_by_user_id": "U_A"}]
    supabase = _FakeSupabase(installation_rows)
    admin_store = _FakeAdminStore(partially_configured={"T_PARTIAL"})
    _patch_common(monkeypatch, supabase, admin_store)

    backfill.main()

    assert admin_store.seeded_calls == [("T_PARTIAL", "U_A")]
    assert "1 seeded, 0 skipped" in capsys.readouterr().out


def test_backfill_skips_and_warns_when_no_installer_on_record(monkeypatch, capsys):
    installation_rows = [{"team_id": "T_LEGACY", "installed_by_user_id": None}]
    supabase = _FakeSupabase(installation_rows)
    admin_store = _FakeAdminStore()
    _patch_common(monkeypatch, supabase, admin_store)

    backfill.main()

    assert admin_store.seeded_calls == []
    output = capsys.readouterr().out
    assert "T_LEGACY" in output
    assert "0 seeded, 1 skipped" in output
