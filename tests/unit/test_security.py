import time

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("Passw0rd123")
    assert hashed != "Passw0rd123"
    assert verify_password("Passw0rd123", hashed)
    assert not verify_password("wrong", hashed)


def test_password_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_access_token_carries_claims() -> None:
    token, jti, expires_at = create_access_token(7, {"role": "trader"})
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "7"
    assert payload["type"] == "access"
    assert payload["jti"] == jti
    assert payload["role"] == "trader"
    assert payload["exp"] == int(expires_at.timestamp())


def test_refresh_token_type_is_enforced() -> None:
    token, _, _ = create_refresh_token(7)
    decode_token(token, expected_type="refresh")
    with pytest.raises(AuthenticationError) as exc:
        decode_token(token, expected_type="access")
    assert exc.value.code == "token_wrong_type"


def test_tampered_token_rejected() -> None:
    token, _, _ = create_access_token(7)
    with pytest.raises(AuthenticationError):
        decode_token(token + "x")


def test_expired_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import security

    monkeypatch.setattr(security.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token, _, _ = create_access_token(7)
    time.sleep(0.01)
    with pytest.raises(AuthenticationError) as exc:
        decode_token(token)
    assert exc.value.code == "token_expired"


def test_token_hash_is_stable_and_opaque() -> None:
    token, _, _ = create_refresh_token(1)
    assert hash_token(token) == hash_token(token)
    assert token not in hash_token(token)
    assert len(hash_token(token)) == 64


def test_jti_is_unique_per_token() -> None:
    _, jti_a, _ = create_access_token(1)
    _, jti_b, _ = create_access_token(1)
    assert jti_a != jti_b
