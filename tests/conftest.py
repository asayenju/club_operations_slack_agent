import pytest

from common import slack_ingestion


@pytest.fixture(autouse=True)
def _default_existing_key_state(monkeypatch):
    """Most tests don't care about stored hash/thread-reply state; default to empty."""
    monkeypatch.setattr(slack_ingestion, "existing_key_state", lambda *a, **k: {})
