import pytest

from common import slack_ingestion


@pytest.fixture(autouse=True)
def _default_existing_metadata(monkeypatch):
    """Most tests don't care about thread-reply-tracking metadata; default to empty."""
    monkeypatch.setattr(slack_ingestion, "existing_metadata", lambda *a, **k: {})
