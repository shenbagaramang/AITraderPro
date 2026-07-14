import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import auth_header

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


@pytest.mark.asyncio
async def test_register_returns_public_user(client: AsyncClient) -> None:
    resp = await client.post(
        REGISTER,
        json={"email": "New@Example.com", "password": "Passw0rd123", "full_name": "New User"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "trader"
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(
    client: AsyncClient, trader_user: User
) -> None:
    resp = await client.post(
        REGISTER, json={"email": trader_user.email, "password": "Passw0rd123"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    resp = await client.post(REGISTER, json={"email": "weak@example.com", "password": "short"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, trader_user: User) -> None:
    resp = await client.post(
        LOGIN, json={"email": trader_user.email, "password": "Passw0rd123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, trader_user: User) -> None:
    resp = await client.post(
        LOGIN, json={"email": trader_user.email, "password": "WrongPass1"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_token(client: AsyncClient) -> None:
    assert (await client.get(ME)).status_code == 401


@pytest.mark.asyncio
async def test_me_with_token(client: AsyncClient, trader_user: User) -> None:
    resp = await client.get(ME, headers=auth_header(trader_user))
    assert resp.status_code == 200
    assert resp.json()["email"] == trader_user.email


@pytest.mark.asyncio
async def test_refresh_rotates_token(client: AsyncClient, trader_user: User) -> None:
    login = await client.post(
        LOGIN, json={"email": trader_user.email, "password": "Passw0rd123"}
    )
    old_refresh = login.json()["refresh_token"]

    first = await client.post(REFRESH, json={"refresh_token": old_refresh})
    assert first.status_code == 200
    assert first.json()["refresh_token"] != old_refresh

    # The rotated-away token must no longer be accepted.
    replay = await client.post(REFRESH, json={"refresh_token": old_refresh})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "token_revoked"


@pytest.mark.asyncio
async def test_access_token_rejected_on_refresh_endpoint(
    client: AsyncClient, trader_user: User
) -> None:
    login = await client.post(
        LOGIN, json={"email": trader_user.email, "password": "Passw0rd123"}
    )
    access = login.json()["access_token"]
    resp = await client.post(REFRESH, json={"refresh_token": access})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_wrong_type"


@pytest.mark.asyncio
async def test_logout_blocklists_access_token(client: AsyncClient, trader_user: User) -> None:
    login = await client.post(
        LOGIN, json={"email": trader_user.email, "password": "Passw0rd123"}
    )
    access = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    assert (await client.post(LOGOUT, headers=headers)).status_code == 200
    after = await client.get(ME, headers=headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "token_revoked"
