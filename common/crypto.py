"""Symmetric encryption for secrets stored at rest (Slack bot tokens, Google
OAuth refresh tokens) once those move from local files/env vars into
per-workspace database rows for multi-tenant installs.

One mechanism, reused everywhere a per-workspace secret needs to sit in
Supabase — see issues #61 and #66.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class EncryptionKeyMissing(RuntimeError):
    pass


class DecryptionFailed(RuntimeError):
    pass


@lru_cache
def _fernet() -> Fernet:
    import os

    key = os.environ.get("APP_ENCRYPTION_KEY")
    if not key or not key.strip():
        raise EncryptionKeyMissing(
            "APP_ENCRYPTION_KEY must be configured to store per-workspace "
            "secrets (Slack bot tokens, Google refresh tokens). Generate one "
            "with: python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise EncryptionKeyMissing(
            "APP_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns a urlsafe-base64 token string."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a value previously produced by encrypt()."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionFailed(
            "Could not decrypt stored secret — APP_ENCRYPTION_KEY may have "
            "changed, or the stored value is corrupt."
        ) from exc
