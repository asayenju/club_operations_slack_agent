import os

import pytest

from common import slack_ingestion

# Review feedback (Aman, PR #70): several test helpers never set these
# explicitly, relying on a real, untracked .env file happening to have them --
# so the suite failed before exercising any code on a clean checkout with no
# .env. Set safe, deterministic fake defaults once, before any test module
# (or the settings classes they construct) loads. os.environ takes precedence
# over pydantic-settings' own .env-file fallback, so this doesn't depend on
# .env existing, but a developer's real .env (if present) still isn't
# touched for any key not listed here.
_TEST_ENV_DEFAULTS = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "test.fake.jwt",
    "VOYAGE_API_KEY": "test-voyage-key",
    "SLACK_CLIENT_ID": "test-slack-client-id",
    "SLACK_CLIENT_SECRET": "test-slack-client-secret",
    "SLACK_SIGNING_SECRET": "test-slack-signing-secret",
    "WORKSPACE_ID": "T-TEST-DEFAULT",
}
for _key, _value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)


@pytest.fixture(autouse=True)
def _default_existing_key_state(monkeypatch):
    """Most tests don't care about stored hash/thread-reply state; default to empty."""
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a, **k: {})
