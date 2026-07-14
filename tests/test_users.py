import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import auth_header

USERS = "/api/v1/users"


@pytest.mark.asyncio
async def test_list_users_requires_superuser(client: AsyncClient, trader_user: User) -> None:
    resp = await client.get(USERS, headers=auth_header(trader_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_users_as_admin(
    client: AsyncClient, admin_user: User, trader_user: User
) -> None:
    resp = await client.get(USERS, headers=auth_header(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {u["email"] for u in body["items"]} == {admin_user.email, trader_user.email}


@pytest.mark.asyncio
async def test_update_me_cannot_escalate_role(client: AsyncClient, trader_user: User) -> None:
    resp = await client.patch(
        f"{USERS}/me",
        headers=auth_header(trader_user),
        json={"full_name": "Renamed", "role": "admin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Renamed"
    assert body["role"] == "trader"


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient, trader_user: User) -> None:
    resp = await client.post(
        f"{USERS}/me/password",
        headers=auth_header(trader_user),
        json={"current_password": "Passw0rd123", "new_password": "BrandNew456"},
    )
    assert resp.status_code == 200

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": trader_user.email, "password": "BrandNew456"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current(client: AsyncClient, trader_user: User) -> None:
    resp = await client.post(
        f"{USERS}/me/password",
        headers=auth_header(trader_user),
        json={"current_password": "Nope12345", "new_password": "BrandNew456"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_deactivates_user(
    client: AsyncClient, admin_user: User, trader_user: User
) -> None:
    resp = await client.delete(f"{USERS}/{trader_user.id}", headers=auth_header(admin_user))
    assert resp.status_code == 200

    denied = await client.get("/api/v1/auth/me", headers=auth_header(trader_user))
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "user_inactive"


@pytest.mark.asyncio
async def test_get_missing_user_404(client: AsyncClient, admin_user: User) -> None:
    resp = await client.get(f"{USERS}/9999", headers=auth_header(admin_user))
    assert resp.status_code == 404
