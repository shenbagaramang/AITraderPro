"""Kite adapter, driven by a fake KiteConnect.

The point of injecting the client is that this translation layer — the part that
turns Kite's dicts and strings into our types — is the part most likely to be
subtly wrong, and it is fully testable without an account.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.brokers.base import (
    BrokerAuthError,
    OrderNotFoundError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Product,
)
from app.brokers.kite.auth import IST, KiteSession
from app.brokers.kite.client import KiteBroker


class FakeKite:
    def __init__(self) -> None:
        self.placed: list[dict] = []
        self._orders: dict[str, dict] = {}

    def profile(self) -> dict:
        return {"user_id": "AB1234"}

    def place_order(self, **params) -> str:
        self.placed.append(params)
        order_id = f"25071{len(self.placed):05d}"
        self._orders[order_id] = {
            "order_id": order_id,
            "tradingsymbol": params["tradingsymbol"],
            "exchange": params["exchange"],
            "transaction_type": params["transaction_type"],
            "quantity": params["quantity"],
            "filled_quantity": params["quantity"],
            "status": "COMPLETE",
            "product": params["product"],
            "order_type": params["order_type"],
            "price": params.get("price", 0),
            "average_price": 2450.5,
            "trigger_price": params.get("trigger_price", 0),
            "tag": params.get("tag"),
        }
        return order_id

    def order_history(self, order_id: str) -> list[dict]:
        if order_id not in self._orders:
            return []
        return [self._orders[order_id]]

    def orders(self) -> list[dict]:
        return list(self._orders.values())

    def cancel_order(self, variety: str, order_id: str) -> str:
        self._orders[order_id]["status"] = "CANCELLED"
        return order_id

    def positions(self) -> dict:
        return {
            "net": [
                {
                    "tradingsymbol": "RELIANCE",
                    "exchange": "NSE",
                    "quantity": 10,
                    "average_price": 2400.0,
                    "last_price": 2450.0,
                    "product": "CNC",
                    "pnl": 500.0,
                },
                {  # a closed-out row: Kite returns these, and they are not positions
                    "tradingsymbol": "TCS",
                    "exchange": "NSE",
                    "quantity": 0,
                    "average_price": 3000.0,
                    "last_price": 3100.0,
                    "product": "CNC",
                    "pnl": 0.0,
                },
            ]
        }

    def holdings(self) -> list[dict]:
        return [
            {
                "tradingsymbol": "INFY",
                "exchange": "NSE",
                "quantity": 20,
                "average_price": 1400.0,
                "last_price": 1500.0,
                "pnl": 2000.0,
            }
        ]

    def margins(self, segment: str) -> dict:
        return {
            "available": {"live_balance": 250_000.0},
            "utilised": {"debits": 50_000.0},
            "net": 200_000.0,
        }

    def quote(self, symbols: list[str]) -> dict:
        return {
            "NSE:RELIANCE": {
                "last_price": 2450.0,
                "volume": 1_000_000,
                "ohlc": {"open": 2400.0, "high": 2460.0, "low": 2390.0, "close": 2410.0},
            }
        }


@pytest.fixture
def broker() -> KiteBroker:
    return KiteBroker(api_key="k", access_token="t", kite=FakeKite())


class TestTranslation:
    def test_place_order_maps_our_types_onto_kites_params(self, broker: KiteBroker) -> None:
        order = broker.place_order(
            OrderRequest(
                symbol="RELIANCE",
                exchange="NSE",
                side=OrderSide.BUY,
                quantity=10,
                product=Product.CNC,
                order_type=OrderType.LIMIT,
                price=2400.0,
                idempotency_key="key-123",
            )
        )
        sent = broker._kite.placed[0]  # type: ignore[attr-defined]

        assert sent["variety"] == "regular"
        assert sent["tradingsymbol"] == "RELIANCE"
        assert sent["transaction_type"] == "BUY"
        assert sent["order_type"] == "LIMIT"
        assert sent["price"] == 2400.0
        # Kite has no idempotency field, so ours rides in the tag.
        assert sent["tag"] == "key-123"

        assert order.status is OrderStatus.COMPLETE
        assert order.average_price == 2450.5

    def test_the_tag_is_truncated_to_kites_20_char_limit(self, broker: KiteBroker) -> None:
        broker.place_order(
            OrderRequest(
                symbol="X",
                exchange="NSE",
                side=OrderSide.BUY,
                quantity=1,
                idempotency_key="a" * 50,
            )
        )
        assert len(broker._kite.placed[0]["tag"]) == 20  # type: ignore[attr-defined]

    def test_kite_status_strings_map_onto_our_enum(self, broker: KiteBroker) -> None:
        from app.brokers.kite.client import STATUS_MAP

        assert STATUS_MAP["TRIGGER PENDING"] is OrderStatus.OPEN
        assert STATUS_MAP["COMPLETE"] is OrderStatus.COMPLETE
        assert STATUS_MAP["REJECTED"] is OrderStatus.REJECTED

    def test_zero_quantity_positions_are_filtered_out(self, broker: KiteBroker) -> None:
        """Kite returns closed-out rows in the position book. They are not positions."""
        positions = broker.positions()
        assert len(positions) == 1
        assert positions[0].symbol == "RELIANCE"

    def test_holdings_are_translated(self, broker: KiteBroker) -> None:
        holding = broker.holdings()[0]
        assert holding.symbol == "INFY"
        assert holding.value == pytest.approx(30_000.0)

    def test_margins_are_translated(self, broker: KiteBroker) -> None:
        margins = broker.margins()
        assert margins.available_cash == 250_000.0
        assert margins.used_margin == 50_000.0

    def test_quote_computes_change_against_the_previous_close(
        self, broker: KiteBroker
    ) -> None:
        quote = broker.quote(["NSE:RELIANCE"])["NSE:RELIANCE"]
        assert quote.last_price == 2450.0
        assert quote.change_pct == pytest.approx((2450 - 2410) / 2410 * 100)

    def test_an_unknown_order_raises_OrderNotFoundError(self, broker: KiteBroker) -> None:
        with pytest.raises(OrderNotFoundError):
            broker.get_order("nonexistent")


class TestErrorTranslation:
    def test_a_token_exception_becomes_BrokerAuthError(self, broker: KiteBroker) -> None:
        class TokenException(Exception):
            pass

        translated = broker._translate(TokenException("token expired"))
        assert isinstance(translated, BrokerAuthError)
        assert "expires every morning" in str(translated)


class TestSessionExpiry:
    def test_a_session_issued_midday_expires_at_6am_the_next_morning(self) -> None:
        """Kite tokens die daily. Nothing about this is a bug to work around."""
        issued = datetime(2026, 7, 13, 10, 0, tzinfo=IST)
        session = KiteSession("tok", None, "AB1234", issued.astimezone(UTC))

        expiry_ist = session.expires_at.astimezone(IST)
        assert expiry_ist.day == 14
        assert expiry_ist.hour == 6

    def test_a_session_is_expired_once_that_time_passes(self) -> None:
        issued = datetime(2026, 7, 13, 10, 0, tzinfo=IST).astimezone(UTC)
        session = KiteSession("tok", None, "AB1234", issued)

        assert not session.is_expired(issued + timedelta(hours=1))
        assert session.is_expired(issued + timedelta(days=1))
