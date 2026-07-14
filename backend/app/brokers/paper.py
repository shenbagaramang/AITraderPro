"""In-memory paper broker.

Not a mock. A deterministic simulation with a real fill model, real margin
accounting and a real order book, so the decision chain can be exercised
end-to-end — and dry-run against live prices — without an account.

The fill model is deliberately pessimistic:

- market orders fill at the quote **plus slippage against you**, never at the
  midpoint you hoped for
- limit orders only fill when the price actually trades through them
- stop orders trigger, then become market orders, and pay slippage again

A paper broker that fills every order instantly at the last price is a machine
for producing backtests that cannot be reproduced with real money.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

from app.brokers.base import (
    Broker,
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
)


class PaperBroker(Broker):
    name = "paper"

    def __init__(
        self,
        starting_cash: float = 1_000_000.0,
        slippage_bps: float = 5.0,
        brokerage_pct: float = 0.03,
    ) -> None:
        self.cash = starting_cash
        self.starting_cash = starting_cash
        self.slippage_bps = slippage_bps
        self.brokerage_pct = brokerage_pct

        self._prices: dict[str, Quote] = {}
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._idempotency: dict[str, str] = {}  # key -> order_id
        self._ids = itertools.count(1)

    # --- test/dry-run surface ----------------------------------------------
    def set_price(self, symbol: str, price: float, **kwargs: float) -> None:
        self._prices[symbol] = Quote(
            symbol=symbol,
            last_price=price,
            timestamp=datetime.now(UTC),
            **kwargs,  # type: ignore[arg-type]
        )
        self._mark_to_market(symbol)
        self._try_fill_resting(symbol)

    # --- Broker ------------------------------------------------------------
    def is_authenticated(self) -> bool:
        return True

    def place_order(self, request: OrderRequest) -> Order:
        # Idempotency first, before anything is mutated.
        if request.idempotency_key:
            existing = self._idempotency.get(request.idempotency_key)
            if existing:
                return self._orders[existing]

        if request.symbol not in self._prices:
            raise OrderNotFoundError(f"no price for {request.symbol}; call set_price first")

        order_id = f"PAPER{next(self._ids):06d}"
        order = Order(
            order_id=order_id,
            symbol=request.symbol,
            exchange=request.exchange,
            side=request.side,
            quantity=request.quantity,
            filled_quantity=0,
            status=OrderStatus.OPEN,
            product=request.product,
            order_type=request.order_type,
            price=request.price,
            trigger_price=request.trigger_price,
            placed_at=datetime.now(UTC),
            tag=request.tag,
        )
        self._orders[order_id] = order

        if request.idempotency_key:
            self._idempotency[request.idempotency_key] = order_id

        if request.order_type is OrderType.MARKET:
            self._fill(order_id, self._fill_price(request.symbol, request.side))
        else:
            self._try_fill_resting(request.symbol)

        return self._orders[order_id]

    def cancel_order(self, order_id: str) -> Order:
        order = self._require(order_id)
        if order.status.is_terminal:
            raise OrderNotFoundError(f"{order_id} is already {order.status.value}")
        self._orders[order_id] = _replace(order, status=OrderStatus.CANCELLED)
        return self._orders[order_id]

    def modify_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> Order:
        order = self._require(order_id)
        if order.status.is_terminal:
            raise OrderNotFoundError(f"cannot modify a {order.status.value} order")

        self._orders[order_id] = _replace(
            order,
            quantity=quantity if quantity is not None else order.quantity,
            price=price if price is not None else order.price,
            trigger_price=(
                trigger_price if trigger_price is not None else order.trigger_price
            ),
        )
        self._try_fill_resting(order.symbol)
        return self._orders[order_id]

    def get_order(self, order_id: str) -> Order:
        return self._require(order_id)

    def orders(self) -> list[Order]:
        return list(self._orders.values())

    def positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity != 0]

    def holdings(self) -> list[Holding]:
        return [
            Holding(
                symbol=p.symbol,
                exchange=p.exchange,
                quantity=p.quantity,
                average_price=p.average_price,
                last_price=p.last_price,
                pnl=p.pnl,
            )
            for p in self._positions.values()
            if p.quantity > 0 and p.product is Product.CNC
        ]

    def margins(self) -> Margins:
        used = sum(p.value for p in self.positions())
        return Margins(available_cash=self.cash, used_margin=used, net=self.cash + used)

    def quote(self, symbols: list[str]) -> dict[str, Quote]:
        return {s: self._prices[s] for s in symbols if s in self._prices}

    # --- fill engine -------------------------------------------------------
    def _fill_price(self, symbol: str, side: OrderSide) -> float:
        """Slippage always works against the order. That is what slippage is."""
        last = self._prices[symbol].last_price
        drift = last * self.slippage_bps / 10_000.0
        return last + drift if side is OrderSide.BUY else last - drift

    def _try_fill_resting(self, symbol: str) -> None:
        last = self._prices[symbol].last_price

        for order_id, order in list(self._orders.items()):
            if order.symbol != symbol or order.status.is_terminal:
                continue

            if order.order_type is OrderType.LIMIT:
                assert order.price is not None
                crossed = (order.side is OrderSide.BUY and last <= order.price) or (
                    order.side is OrderSide.SELL and last >= order.price
                )
                if crossed:
                    # A limit order fills at its own price, not better.
                    self._fill(order_id, order.price)

            elif order.order_type in (OrderType.SL, OrderType.SL_M):
                assert order.trigger_price is not None
                triggered = (order.side is OrderSide.BUY and last >= order.trigger_price) or (
                    order.side is OrderSide.SELL and last <= order.trigger_price
                )
                if triggered:
                    # A triggered stop becomes a market order — and pays slippage.
                    # This is why real stop losses fill worse than the trigger.
                    self._fill(order_id, self._fill_price(symbol, order.side))

    def _fill(self, order_id: str, price: float) -> None:
        order = self._orders[order_id]
        cost = order.quantity * price
        fees = abs(cost) * self.brokerage_pct / 100.0

        if order.side is OrderSide.BUY and cost + fees > self.cash:
            self._orders[order_id] = _replace(
                order,
                status=OrderStatus.REJECTED,
                status_message=(
                    f"insufficient funds: need ₹{cost + fees:,.2f}, have ₹{self.cash:,.2f}"
                ),
            )
            raise InsufficientFundsError(self._orders[order_id].status_message or "")

        self.cash += -cost - fees if order.side is OrderSide.BUY else cost - fees
        self._apply_to_position(order, price)

        self._orders[order_id] = _replace(
            order,
            status=OrderStatus.COMPLETE,
            filled_quantity=order.quantity,
            average_price=round(price, 2),
        )

    def _apply_to_position(self, order: Order, price: float) -> None:
        key = order.symbol
        signed = order.quantity if order.side is OrderSide.BUY else -order.quantity
        existing = self._positions.get(key)

        if existing is None:
            self._positions[key] = Position(
                symbol=order.symbol,
                exchange=order.exchange,
                quantity=signed,
                average_price=price,
                last_price=price,
                product=order.product,
            )
            return

        new_qty = existing.quantity + signed

        if existing.quantity * signed > 0:
            # Adding to the position: weighted-average the entry price.
            total = existing.average_price * existing.quantity + price * signed
            avg = total / new_qty
        elif new_qty == 0:
            avg = existing.average_price
        elif existing.quantity * new_qty < 0:
            # Flipped through zero: the new position starts fresh at this price.
            avg = price
        else:
            # Partial close: the remaining lot keeps its original cost basis.
            avg = existing.average_price

        realised = 0.0
        if existing.quantity * signed < 0:
            closed = min(abs(signed), abs(existing.quantity))
            direction = 1 if existing.quantity > 0 else -1
            realised = closed * (price - existing.average_price) * direction

        self._positions[key] = Position(
            symbol=order.symbol,
            exchange=order.exchange,
            quantity=new_qty,
            average_price=avg,
            last_price=price,
            product=order.product,
            pnl=existing.pnl + realised,
        )

    def _mark_to_market(self, symbol: str) -> None:
        position = self._positions.get(symbol)
        if position is None or position.quantity == 0:
            return
        last = self._prices[symbol].last_price
        unrealised = position.quantity * (last - position.average_price)
        self._positions[symbol] = _replace_position(
            position, last_price=last, pnl=round(unrealised, 2)
        )

    def _require(self, order_id: str) -> Order:
        if order_id not in self._orders:
            raise OrderNotFoundError(f"unknown order {order_id}")
        return self._orders[order_id]


def _replace(order: Order, **changes: object) -> Order:
    from dataclasses import replace

    return replace(order, **changes)  # type: ignore[arg-type]


def _replace_position(position: Position, **changes: object) -> Position:
    from dataclasses import replace

    return replace(position, **changes)  # type: ignore[arg-type]
