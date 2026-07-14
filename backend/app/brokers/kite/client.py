"""Kite Connect implementing the Broker port.

Everything Kite-specific is translated at this boundary: its string constants,
its dict shapes, its exception types. Nothing above this file knows what a
``variety`` is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.brokers.base import (
    Broker,
    BrokerAuthError,
    BrokerError,
    Holding,
    InsufficientFundsError,
    Margins,
    Order,
    OrderNotFoundError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Product,
    Quote,
    Validity,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Kite's status strings are not our enum, and mapping them in one place beats
# scattering string comparisons through the codebase.
STATUS_MAP = {
    "COMPLETE": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "OPEN": OrderStatus.OPEN,
    "TRIGGER PENDING": OrderStatus.OPEN,
    "AMO REQ RECEIVED": OrderStatus.PENDING,
    "PUT ORDER REQ RECEIVED": OrderStatus.PENDING,
    "VALIDATION PENDING": OrderStatus.PENDING,
    "OPEN PENDING": OrderStatus.PENDING,
    "MODIFY PENDING": OrderStatus.OPEN,
    "CANCEL PENDING": OrderStatus.OPEN,
}


class KiteBroker(Broker):
    name = "kite"

    def __init__(self, api_key: str, access_token: str, kite: Any | None = None) -> None:
        """``kite`` is injectable so this class is testable against a fake without
        a live session — which is the only reason it can be tested at all."""
        self.api_key = api_key
        self.access_token = access_token

        if kite is not None:
            self._kite = kite
            return

        try:
            from kiteconnect import KiteConnect
        except ImportError as exc:  # pragma: no cover
            raise BrokerError(
                "the `kiteconnect` package is not installed; "
                "run `pip install kiteconnect` to use the live broker"
            ) from exc

        self._kite = KiteConnect(api_key=api_key)
        self._kite.set_access_token(access_token)

    # --- auth --------------------------------------------------------------
    def is_authenticated(self) -> bool:
        try:
            self._kite.profile()
            return True
        except Exception:  # noqa: BLE001
            return False

    # --- orders ------------------------------------------------------------
    def place_order(self, request: OrderRequest) -> Order:
        # Kite has no idempotency key of its own, so the tag carries ours. It is
        # capped at 20 characters, and the service layer also holds a unique
        # constraint on the key — belt and braces, because a duplicated order is
        # not a bug you get to fix afterwards.
        tag = (request.idempotency_key or request.tag or "")[:20] or None

        params: dict[str, Any] = {
            "variety": "regular",
            "exchange": request.exchange,
            "tradingsymbol": request.symbol,
            "transaction_type": request.side.value,
            "quantity": request.quantity,
            "product": request.product.value,
            "order_type": request.order_type.value,
            "validity": request.validity.value,
        }
        if request.price is not None:
            params["price"] = request.price
        if request.trigger_price is not None:
            params["trigger_price"] = request.trigger_price
        if tag:
            params["tag"] = tag

        try:
            order_id = self._kite.place_order(**params)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

        logger.info(
            "Kite order %s placed: %s %s x%s",
            order_id,
            request.side.value,
            request.symbol,
            request.quantity,
        )
        return self.get_order(str(order_id))

    def cancel_order(self, order_id: str) -> Order:
        try:
            self._kite.cancel_order(variety="regular", order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return self.get_order(order_id)

    def modify_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> Order:
        params: dict[str, Any] = {"variety": "regular", "order_id": order_id}
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price

        try:
            self._kite.modify_order(**params)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
        return self.get_order(order_id)

    def get_order(self, order_id: str) -> Order:
        try:
            history = self._kite.order_history(order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

        if not history:
            raise OrderNotFoundError(f"Kite has no order {order_id}")
        return self._to_order(history[-1])  # the last leg is the current state

    def orders(self) -> list[Order]:
        try:
            return [self._to_order(o) for o in self._kite.orders()]
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

    # --- book --------------------------------------------------------------
    def positions(self) -> list[Position]:
        try:
            book = self._kite.positions()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

        return [
            Position(
                symbol=p["tradingsymbol"],
                exchange=p["exchange"],
                quantity=int(p["quantity"]),
                average_price=float(p["average_price"]),
                last_price=float(p["last_price"]),
                product=Product(p["product"]),
                pnl=float(p.get("pnl", 0.0)),
            )
            for p in book.get("net", [])
            if int(p["quantity"]) != 0
        ]

    def holdings(self) -> list[Holding]:
        try:
            rows = self._kite.holdings()
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

        return [
            Holding(
                symbol=h["tradingsymbol"],
                exchange=h["exchange"],
                quantity=int(h["quantity"]),
                average_price=float(h["average_price"]),
                last_price=float(h["last_price"]),
                pnl=float(h.get("pnl", 0.0)),
            )
            for h in rows
        ]

    def margins(self) -> Margins:
        try:
            data = self._kite.margins(segment="equity")
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

        available = data.get("available", {})
        utilised = data.get("utilised", {})
        return Margins(
            available_cash=float(available.get("live_balance", available.get("cash", 0.0))),
            used_margin=float(utilised.get("debits", 0.0)),
            net=float(data.get("net", 0.0)),
        )

    def quote(self, symbols: list[str]) -> dict[str, Quote]:
        """Symbols must be fully qualified, e.g. ``NSE:RELIANCE``."""
        try:
            raw = self._kite.quote(symbols)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc

        out: dict[str, Quote] = {}
        for key, data in raw.items():
            ohlc = data.get("ohlc", {})
            out[key] = Quote(
                symbol=key,
                last_price=float(data["last_price"]),
                timestamp=data.get("timestamp"),
                volume=int(data.get("volume", 0)),
                open=ohlc.get("open"),
                high=ohlc.get("high"),
                low=ohlc.get("low"),
                close=ohlc.get("close"),
            )
        return out

    # --- translation -------------------------------------------------------
    def _to_order(self, raw: dict[str, Any]) -> Order:
        status = STATUS_MAP.get(str(raw.get("status", "")).upper(), OrderStatus.PENDING)
        placed = raw.get("order_timestamp")
        if isinstance(placed, str):
            placed = datetime.fromisoformat(placed)

        return Order(
            order_id=str(raw["order_id"]),
            symbol=raw["tradingsymbol"],
            exchange=raw["exchange"],
            side=OrderSide(raw["transaction_type"]),
            quantity=int(raw["quantity"]),
            filled_quantity=int(raw.get("filled_quantity", 0)),
            status=status,
            product=Product(raw["product"]),
            order_type=OrderType(raw["order_type"]),
            price=float(raw["price"]) if raw.get("price") else None,
            average_price=float(raw["average_price"]) if raw.get("average_price") else None,
            trigger_price=(float(raw["trigger_price"]) if raw.get("trigger_price") else None),
            placed_at=placed,
            status_message=raw.get("status_message"),
            tag=raw.get("tag"),
        )

    def _translate(self, exc: Exception) -> BrokerError:
        """Kite's exception names are strings to us — the package may not even be
        installed — so the class name is matched rather than the type."""
        name = type(exc).__name__
        message = str(exc)

        if name in ("TokenException", "PermissionException"):
            return BrokerAuthError(
                f"Kite session is dead ({message}). "
                "The access token expires every morning; a fresh login is required."
            )
        if name == "InsufficientFundsException" or "insufficient" in message.lower():
            return InsufficientFundsError(message)
        if name == "OrderException" and "not found" in message.lower():
            return OrderNotFoundError(message)
        return BrokerError(f"Kite: {message}")


__all__ = ["KiteBroker", "STATUS_MAP", "Validity"]
