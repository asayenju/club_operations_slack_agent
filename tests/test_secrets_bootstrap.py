"""Fly Machines get a fresh filesystem from the image on every deploy/secret
update, so the shared Google credential file has to be reconstructed at
process startup from a Fly secret rather than persisted on disk. These pin
that materialization step."""

import base64

import pytest

from common.secrets_bootstrap import materialize_google_token


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    token_path = tmp_path / "secrets" / "club_token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(token_path))
    from common.config import get_ingestion_settings
    get_ingestion_settings.cache_clear()
    yield token_path
    get_ingestion_settings.cache_clear()


def test_writes_file_from_base64_env_var_when_missing(settings_env, monkeypatch):
    token_path = settings_env
    monkeypatch.setenv("GOOGLE_TOKEN_JSON_B64", base64.b64encode(b'{"refresh_token": "abc"}').decode())

    materialize_google_token()

    assert token_path.read_bytes() == b'{"refresh_token": "abc"}'


def test_noop_when_file_already_exists(settings_env, monkeypatch):
    token_path = settings_env
    token_path.parent.mkdir(parents=True)
    token_path.write_bytes(b"existing-token")
    monkeypatch.setenv("GOOGLE_TOKEN_JSON_B64", base64.b64encode(b"different-token").decode())

    materialize_google_token()

    assert token_path.read_bytes() == b"existing-token"


def test_noop_when_env_var_not_set(settings_env, monkeypatch):
    token_path = settings_env
    monkeypatch.delenv("GOOGLE_TOKEN_JSON_B64", raising=False)

    materialize_google_token()

    assert not token_path.exists()
