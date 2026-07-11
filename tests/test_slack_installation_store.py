from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation

from common import crypto
from common.slack_installation_store import SupabaseInstallationStore


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    crypto._fernet.cache_clear()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    yield
    crypto._fernet.cache_clear()


class _FakeTable:
    def __init__(self, rows_by_team):
        self._rows_by_team = rows_by_team
        self._filters = {}
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
            self._rows_by_team[self._pending_upsert["team_id"]] = self._pending_upsert
            return SimpleNamespace(data=[self._pending_upsert])
        if self._pending_delete:
            team_id = self._filters.get("team_id")
            self._rows_by_team.pop(team_id, None)
            return SimpleNamespace(data=[])
        if not self._filters:
            return SimpleNamespace(data=list(self._rows_by_team.values()))
        team_id = self._filters.get("team_id")
        row = self._rows_by_team.get(team_id)
        return SimpleNamespace(data=[row] if row else [])


class _FakeSupabase:
    def __init__(self):
        self.rows_by_team: dict = {}

    def table(self, name):
        assert name == "slack_installations"
        return _FakeTable(self.rows_by_team)


def _installation(**overrides):
    defaults = dict(
        app_id="A123",
        team_id="T123",
        bot_token="xoxb-secret-token",
        bot_id="B123",
        bot_user_id="U_BOT",
        bot_scopes=["chat:write", "channels:history"],
        user_id="U_INSTALLER",
        is_enterprise_install=False,
        installed_at=1700000000.0,
    )
    defaults.update(overrides)
    return Installation(**defaults)


def test_save_then_find_bot_round_trips_and_decrypts_token():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)

    store.save(_installation())
    bot = store.find_bot(enterprise_id=None, team_id="T123")

    assert bot is not None
    assert bot.bot_token == "xoxb-secret-token"
    assert bot.bot_user_id == "U_BOT"
    assert bot.team_id == "T123"


def test_bot_token_is_encrypted_at_rest():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)

    store.save(_installation())

    stored_row = supabase.rows_by_team["T123"]
    assert "xoxb-secret-token" not in stored_row["bot_token_encrypted"]
    assert crypto.decrypt(stored_row["bot_token_encrypted"]) == "xoxb-secret-token"


def test_find_bot_returns_none_for_unknown_team():
    store = SupabaseInstallationStore(_FakeSupabase())

    assert store.find_bot(enterprise_id=None, team_id="T_UNKNOWN") is None


def test_list_team_ids_returns_every_installed_workspace():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)
    store.save(_installation(team_id="T_A"))
    store.save(_installation(team_id="T_B"))

    assert sorted(store.list_team_ids()) == ["T_A", "T_B"]


def test_list_team_ids_empty_when_nothing_installed():
    store = SupabaseInstallationStore(_FakeSupabase())

    assert store.list_team_ids() == []


def test_two_workspaces_do_not_see_each_other_installations():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)

    store.save(_installation(team_id="T_A", bot_token="token-a"))
    store.save(_installation(team_id="T_B", bot_token="token-b"))

    bot_a = store.find_bot(enterprise_id=None, team_id="T_A")
    bot_b = store.find_bot(enterprise_id=None, team_id="T_B")

    assert bot_a.bot_token == "token-a"
    assert bot_b.bot_token == "token-b"


def test_find_installation_reconstructs_installation_with_decrypted_token():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)
    store.save(_installation())

    installation = store.find_installation(enterprise_id=None, team_id="T123")

    assert installation is not None
    assert installation.bot_token == "xoxb-secret-token"
    assert installation.team_id == "T123"


def test_delete_bot_removes_the_row():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)
    store.save(_installation())

    store.delete_bot(enterprise_id=None, team_id="T123")

    assert store.find_bot(enterprise_id=None, team_id="T123") is None


def test_delete_installation_removes_the_row():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)
    store.save(_installation())

    store.delete_installation(enterprise_id=None, team_id="T123")

    assert store.find_installation(enterprise_id=None, team_id="T123") is None


def test_delete_all_removes_the_row_via_default_implementation():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)
    store.save(_installation())

    store.delete_all(enterprise_id=None, team_id="T123")

    assert store.find_bot(enterprise_id=None, team_id="T123") is None


def test_save_bot_directly_without_full_installation():
    supabase = _FakeSupabase()
    store = SupabaseInstallationStore(supabase)

    store.save_bot(Bot(
        app_id="A1",
        team_id="T_BOT_ONLY",
        bot_token="xoxb-bot-only",
        bot_id="B1",
        bot_user_id="U_BOT",
        bot_scopes="chat:write",
        installed_at=1700000000.0,
    ))

    bot = store.find_bot(enterprise_id=None, team_id="T_BOT_ONLY")
    assert bot.bot_token == "xoxb-bot-only"
