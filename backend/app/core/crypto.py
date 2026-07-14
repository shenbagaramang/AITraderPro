"""Encryption at rest for broker credentials.

A Zerodha access token is not a password — it is a bearer credential that can
place orders. A leaked database dump containing plaintext access tokens is
someone else trading your account until the token expires that evening.

So it is Fernet-encrypted, with a key that is deliberately **separate from
SECRET_KEY**. If the JWT signing key is ever rotated or leaked, the broker vault
must not open with it.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class VaultError(RuntimeError):
    """Raised when a stored credential cannot be decrypted."""


def _fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY
    if not key:
        raise VaultError(
            "ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    if key == settings.SECRET_KEY:
        raise VaultError(
            "ENCRYPTION_KEY must not equal SECRET_KEY — the point of a separate "
            "key is that leaking one does not open the other"
        )

    # Accept either a raw Fernet key or any sufficiently long secret, which is
    # derived into a valid 32-byte key.
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise VaultError(
            "stored credential could not be decrypted — the ENCRYPTION_KEY has "
            "probably changed since it was written"
        ) from exc


def generate_key() -> str:
    return Fernet.generate_key().decode()
