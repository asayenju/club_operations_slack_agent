from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from common.google_oauth_state_store import GoogleOAuthStateStore


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._filters: dict = {}
        self._gt_filters: dict = {}
        self._pending_insert = None
        self._pending_update = None

    def insert(self, row):
        self._pending_insert = row
        return self

    def update(self, fields):
        self._pending_update = fields
        return self

    def eq(self, key, value):
        self._filters[key] = ("eq", value)
        return self

    def is_(self, key, value):
        self._filters[key] = ("is", value)
        return self

    def gt(self, key, value):
        self._filters[key] = ("gt", value)
        return self

    def _matches(self, row):
        for key, (op, value) in self._filters.items():
            if op == "eq" and row.get(key) != value:
                return False
            if op == "is" and value == "null" and row.get(key) is not None:
                return False
            if op == "gt" and not (row.get(key) is not None and row.get(key) > value):
                return False
        return True

    def execute(self):
        if self._pending_insert is not None:
            self._rows[self._pending_insert["state"]] = self._pending_insert
            return SimpleNamespace(data=[self._pending_insert])
        if self._pending_update is not None:
            matches = [row for row in self._rows.values() if self._matches(row)]
            for row in matches:
                row.update(self._pending_update)
            return SimpleNamespace(data=matches)
        matches = [row for row in self._rows.values() if self._matches(row)]
        return SimpleNamespace(data=matches)


class _FakeSupabase:
    def __init__(self):
        self.rows: dict = {}

    def table(self, name):
        assert name == "google_oauth_states"
        return _FakeTable(self.rows)


def test_create_then_consume_round_trips_workspace_and_user():
    supabase = _FakeSupabase()
    store = GoogleOAuthStateStore(supabase)

    token = store.create("T123", "U456")
    result = store.consume(token)

    assert result == ("T123", "U456")


def test_consume_rejects_unknown_token():
    store = GoogleOAuthStateStore(_FakeSupabase())

    assert store.consume("forged-token-that-was-never-issued") is None


def test_consume_rejects_empty_state():
    store = GoogleOAuthStateStore(_FakeSupabase())

    assert store.consume("") is None
    assert store.consume(None) is None


def test_consume_is_single_use_rejecting_replay():
    supabase = _FakeSupabase()
    store = GoogleOAuthStateStore(supabase)
    token = store.create("T123", "U456")

    first = store.consume(token)
    replay = store.consume(token)

    assert first == ("T123", "U456")
    assert replay is None


def test_consume_rejects_expired_token():
    supabase = _FakeSupabase()
    store = GoogleOAuthStateStore(supabase)
    token = store.create("T123", "U456", ttl_seconds=-1)  # already expired

    assert store.consume(token) is None


def test_forged_state_for_a_different_workspace_is_rejected():
    """The actual attack this fixes: knowing a real workspace's team_id
    alone must not be enough to claim its Drive connection."""
    supabase = _FakeSupabase()
    store = GoogleOAuthStateStore(supabase)
    store.create("T_VICTIM", "U_REAL_ADMIN")

    forged_state = "T_VICTIM|U_ATTACKER"  # the old, forgeable format
    assert store.consume(forged_state) is None


def test_two_workspaces_states_do_not_collide():
    supabase = _FakeSupabase()
    store = GoogleOAuthStateStore(supabase)
    token_a = store.create("T_A", "U_A")
    token_b = store.create("T_B", "U_B")

    assert store.consume(token_a) == ("T_A", "U_A")
    assert store.consume(token_b) == ("T_B", "U_B")
