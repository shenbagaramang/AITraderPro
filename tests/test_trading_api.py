"""Broker and order routes, exercised through HTTP against the paper broker.

These are the tests that prove the whole Phase 2 stack composes: route -> service
-> idempotency -> broker port -> paper fill -> order record.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.user import User
from app.services.broker_service import broker_service
from tests.conftest import auth_header

ORDERS = "/api/v1/orders"
BROKER = "/api/v1/broker"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_paper(trader_user: User):
    """Each test starts with a clean paper account, pre-seeded with a price."""
    broker_service.reset_paper(trader_user.id)
    yield
    broker_service.reset_paper(trader_user.id)


async def seed_price(
    client: AsyncClient, user: User, symbol: str = "RELIANCE", price: float = 100.0
):
    """The paper broker needs a price before it can fill. In production the
    ticker seeds this; in tests we reach in directly."""

    # get_broker is async but only touches the db for live; paper short-circuits.
    broker = await broker_service.get_broker(None, user, paper=True)  # type: ignore[arg-type]
    broker.set_price(symbol, price)


class TestOrderPlacement:
    @pytest.mark.asyncio
    async def test_place_a_paper_market_order(self, client: AsyncClient, trader_user: User):
        await seed_price(client, trader_user)

        resp = await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={"symbol": "reliance", "side": "BUY", "quantity": 10, "paper": True},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["symbol"] == "RELIANCE"  # normalised to upper
        assert body["status"] == "COMPLETE"
        assert body["is_paper"] is True
        assert body["average_price"] is not None
        assert body["average_price"] > 100.0  # slippage against the buyer

    @pytest.mark.asyncio
    async def test_viewer_role_cannot_place_orders(self, client: AsyncClient, db_session):
        from app.crud.user import user_crud
        from app.models.user import UserRole
        from app.schemas.user import UserCreate

        viewer = await user_crud.create(
            db_session,
            UserCreate(email="viewer@example.com", password="Passw0rd123"),
        )
        viewer.role = UserRole.VIEWER
        db_session.add(viewer)
        await db_session.commit()

        resp = await client.post(
            ORDERS,
            headers=auth_header(viewer),
            json={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "paper": True},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_idempotency_key_survives_a_retry_through_http(
        self, client: AsyncClient, trader_user: User
    ):
        """The whole point, proven at the HTTP layer: a client retry after a
        timeout cannot double the position."""
        await seed_price(client, trader_user)
        payload = {
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 10,
            "paper": True,
            "idempotency_key": "retry-me-123",
        }

        first = await client.post(ORDERS, headers=auth_header(trader_user), json=payload)
        second = await client.post(ORDERS, headers=auth_header(trader_user), json=payload)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

        orders = await client.get(ORDERS, headers=auth_header(trader_user))
        assert len(orders.json()) == 1

        positions = await client.get(
            f"{BROKER}/positions", headers=auth_header(trader_user), params={"paper": True}
        )
        assert positions.json()[0]["quantity"] == 10  # not 20

    @pytest.mark.asyncio
    async def test_a_rejected_order_is_persisted_not_swallowed(
        self, client: AsyncClient, trader_user: User
    ):
        """A rejection is data. It must land in the order book with its reason."""
        await seed_price(client, trader_user, price=100_000.0)

        resp = await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={"symbol": "RELIANCE", "side": "BUY", "quantity": 1000, "paper": True},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "REJECTED"
        assert "insufficient funds" in body["status_message"]

        listed = await client.get(ORDERS, headers=auth_header(trader_user))
        assert listed.json()[0]["status"] == "REJECTED"

    @pytest.mark.asyncio
    async def test_limit_order_rests_and_can_be_cancelled(
        self, client: AsyncClient, trader_user: User
    ):
        await seed_price(client, trader_user)

        placed = await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={
                "symbol": "RELIANCE",
                "side": "BUY",
                "quantity": 10,
                "order_type": "LIMIT",
                "price": 90.0,
                "paper": True,
            },
        )
        order_id = placed.json()["id"]
        assert placed.json()["status"] == "OPEN"

        cancelled = await client.delete(
            f"{ORDERS}/{order_id}", headers=auth_header(trader_user)
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_cancelling_a_filled_order_is_a_clean_error(
        self, client: AsyncClient, trader_user: User
    ):
        await seed_price(client, trader_user)
        placed = await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "paper": True},
        )
        resp = await client.delete(
            f"{ORDERS}/{placed.json()['id']}", headers=auth_header(trader_user)
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "order_terminal"

    @pytest.mark.asyncio
    async def test_users_cannot_see_each_others_orders(
        self, client: AsyncClient, trader_user: User, admin_user: User
    ):
        await seed_price(client, trader_user)
        await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "paper": True},
        )

        mine = await client.get(ORDERS, headers=auth_header(trader_user))
        theirs = await client.get(ORDERS, headers=auth_header(admin_user))

        assert len(mine.json()) == 1
        assert len(theirs.json()) == 0


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_trading_halted_blocks_everything(
        self, client: AsyncClient, trader_user: User, monkeypatch: pytest.MonkeyPatch
    ):
        from app.services import order_service as module

        await seed_price(client, trader_user)
        monkeypatch.setattr(module.settings, "TRADING_HALTED", True)

        resp = await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={"symbol": "RELIANCE", "side": "BUY", "quantity": 1, "paper": True},
        )
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "trading_halted"


class TestBrokerRoutes:
    @pytest.mark.asyncio
    async def test_status_reports_no_kite_session(
        self, client: AsyncClient, trader_user: User
    ):
        resp = await client.get(f"{BROKER}/status", headers=auth_header(trader_user))
        assert resp.status_code == 200
        assert resp.json()["needs_login"] is True

    @pytest.mark.asyncio
    async def test_paper_margins_and_reset(self, client: AsyncClient, trader_user: User):
        await seed_price(client, trader_user)
        await client.post(
            ORDERS,
            headers=auth_header(trader_user),
            json={"symbol": "RELIANCE", "side": "BUY", "quantity": 10, "paper": True},
        )

        margins = await client.get(
            f"{BROKER}/margins", headers=auth_header(trader_user), params={"paper": True}
        )
        assert margins.json()["available_cash"] < 1_000_000.0

        reset = await client.post(f"{BROKER}/paper/reset", headers=auth_header(trader_user))
        assert reset.status_code == 200

        after = await client.get(
            f"{BROKER}/margins", headers=auth_header(trader_user), params={"paper": True}
        )
        assert after.json()["available_cash"] == 1_000_000.0

    @pytest.mark.asyncio
    async def test_quotes_round_trip(self, client: AsyncClient, trader_user: User):
        await seed_price(client, trader_user, "TCS", 3500.0)
        resp = await client.get(
            f"{BROKER}/quotes",
            headers=auth_header(trader_user),
            params={"symbols": "TCS", "paper": True},
        )
        assert resp.json()["TCS"]["last_price"] == 3500.0

    @pytest.mark.asyncio
    async def test_broker_routes_require_auth(self, client: AsyncClient):
        for path in (f"{BROKER}/status", f"{BROKER}/positions", ORDERS):
            resp = await client.get(path)
            assert resp.status_code == 401
