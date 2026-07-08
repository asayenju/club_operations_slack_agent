import pytest
from cryptography.fernet import Fernet

from common import crypto


@pytest.fixture(autouse=True)
def _clear_cache():
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()


def test_encrypt_then_decrypt_round_trips(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())

    token = crypto.encrypt("xoxb-super-secret")

    assert token != "xoxb-super-secret"
    assert crypto.decrypt(token) == "xoxb-super-secret"


def test_encrypt_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)

    with pytest.raises(crypto.EncryptionKeyMissing):
        crypto.encrypt("secret")


def test_encrypt_raises_when_key_malformed(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "not-a-valid-fernet-key")

    with pytest.raises(crypto.EncryptionKeyMissing):
        crypto.encrypt("secret")


def test_decrypt_raises_on_tampered_token(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token = crypto.encrypt("secret")

    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(token[:-4] + "abcd")


def test_decrypt_raises_when_key_rotated(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token = crypto.encrypt("secret")

    crypto._fernet.cache_clear()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())

    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(token)
