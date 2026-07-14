"""The broker vault. A leaked plaintext access token is someone else trading
your account until it expires that evening."""

from __future__ import annotations

import pytest

from app.core import crypto
from app.core.crypto import VaultError, decrypt, encrypt, generate_key


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", generate_key())
    monkeypatch.setattr(crypto.settings, "SECRET_KEY", "a-totally-different-secret-key-32")


def test_roundtrip() -> None:
    assert decrypt(encrypt("kite-access-token")) == "kite-access-token"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    assert "kite-access-token" not in encrypt("kite-access-token")


def test_encryption_is_non_deterministic() -> None:
    """Same input, different ciphertext — otherwise identical tokens are visible
    as identical rows."""
    assert encrypt("same") != encrypt("same")


def test_a_missing_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", "")
    with pytest.raises(VaultError, match="ENCRYPTION_KEY is not set"):
        encrypt("x")


def test_reusing_SECRET_KEY_as_the_vault_key_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of a second key is that leaking one does not open the other."""
    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", "shared-key-of-sufficient-length!")
    monkeypatch.setattr(crypto.settings, "SECRET_KEY", "shared-key-of-sufficient-length!")

    with pytest.raises(VaultError, match="must not equal SECRET_KEY"):
        encrypt("x")


def test_decrypting_with_a_rotated_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    ciphertext = encrypt("token")
    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", generate_key())

    with pytest.raises(VaultError, match="ENCRYPTION_KEY has"):
        decrypt(ciphertext)


def test_a_long_passphrase_is_derived_into_a_valid_key() -> None:
    from app.core import crypto as c

    original = c.settings.ENCRYPTION_KEY
    try:
        c.settings.ENCRYPTION_KEY = "a-long-human-chosen-passphrase-not-a-fernet-key"
        assert decrypt(encrypt("token")) == "token"
    finally:
        c.settings.ENCRYPTION_KEY = original
