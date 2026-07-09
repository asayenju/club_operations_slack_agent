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
    def __init__(self, already_configured_workspaces=()):
        self.already_configured = set(already_configured_workspaces)
        self.seeded_calls = []

    def get(self, workspace_id):
        configured = workspace_id in self.already_configured
        return SimpleNamespace(drive_sync_admin_user_ids=("U_EXISTING" if configured else None))

    def ensure_default_admin(self, workspace_id, user_id):
        self.seeded_calls.append((workspace_id, user_id))


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
    admin_store = _FakeAdminStore(already_configured_workspaces={"T_A"})
    _patch_common(monkeypatch, supabase, admin_store)

    backfill.main()

    assert admin_store.seeded_calls == [("T_B", "U_B")]
    assert "1 seeded, 1 skipped" in capsys.readouterr().out


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
