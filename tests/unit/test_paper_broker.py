"""Paper broker: a simulation, not a mock. The fill model has to be honest."""

from __future__ import annotations

import pytest

from app.brokers import (
    InsufficientFundsError,
    OrderNotFoundError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
)


@pytest.fixture
def broker() -> PaperBroker:
    b = PaperBroker(starting_cash=1_000_000.0, slippage_bps=10.0, brokerage_pct=0.0)
    b.set_price("RELIANCE", 100.0)
    return b


def buy(qty: int = 100, **kw) -> OrderRequest:
    return OrderRequest(
        symbol="RELIANCE", exchange="NSE", side=OrderSide.BUY, quantity=qty, **kw
    )


def sell(qty: int = 100, **kw) -> OrderRequest:
    return OrderRequest(
        symbol="RELIANCE", exchange="NSE", side=OrderSide.SELL, quantity=qty, **kw
    )


class TestFills:
    def test_market_buy_pays_slippage_against_you(self, broker: PaperBroker) -> None:
        """A paper broker that fills at the last price is a lie generator."""
        order = broker.place_order(buy())
        assert order.status is OrderStatus.COMPLETE
        # 10bps of 100 = 0.10, paid against the buyer.
        assert order.average_price == pytest.approx(100.10)

    def test_market_sell_also_pays_slippage_against_you(self, broker: PaperBroker) -> None:
        broker.place_order(buy(200))
        order = broker.place_order(sell(100))
        assert order.average_price == pytest.approx(99.90)

    def test_limit_order_rests_until_price_comes_to_it(self, broker: PaperBroker) -> None:
        order = broker.place_order(buy(order_type=OrderType.LIMIT, price=95.0))
        assert order.status is OrderStatus.OPEN  # not filled at 100

        broker.set_price("RELIANCE", 94.0)
        assert broker.get_order(order.order_id).status is OrderStatus.COMPLETE
        # It fills at its own limit, not at the better price.
        assert broker.get_order(order.order_id).average_price == pytest.approx(95.0)

    def test_stop_loss_triggers_then_pays_slippage(self, broker: PaperBroker) -> None:
        """Why real stops fill worse than the trigger: a triggered stop is a
        market order."""
        broker.place_order(buy(100))
        stop = broker.place_order(sell(100, order_type=OrderType.SL_M, trigger_price=95.0))
        assert stop.status is OrderStatus.OPEN

        broker.set_price("RELIANCE", 94.0)
        filled = broker.get_order(stop.order_id)
        assert filled.status is OrderStatus.COMPLETE
        # 94 - 10bps = 93.906, rounded to paise. Prices in INR are quoted to 2dp.
        assert filled.average_price == pytest.approx(93.91)
        assert filled.average_price < 95.0  # worse than the trigger

    def test_cash_falls_on_buy_and_rises_on_sell(self, broker: PaperBroker) -> None:
        broker.place_order(buy(100))
        after_buy = broker.cash
        assert after_buy == pytest.approx(1_000_000.0 - 100 * 100.10)

        broker.place_order(sell(100))
        assert broker.cash > after_buy


class TestIdempotency:
    def test_the_same_key_never_places_a_second_order(self, broker: PaperBroker) -> None:
        """The whole reason the key exists: a retry after a timeout must not double up."""
        first = broker.place_order(buy(100, idempotency_key="abc-123"))
        second = broker.place_order(buy(100, idempotency_key="abc-123"))

        assert first.order_id == second.order_id
        assert len(broker.orders()) == 1
        assert broker.positions()[0].quantity == 100  # not 200

    def test_different_keys_place_different_orders(self, broker: PaperBroker) -> None:
        broker.place_order(buy(100, idempotency_key="a"))
        broker.place_order(buy(100, idempotency_key="b"))
        assert len(broker.orders()) == 2
        assert broker.positions()[0].quantity == 200


class TestPositions:
    def test_averaging_up_weights_the_entry_price(self, broker: PaperBroker) -> None:
        broker.place_order(buy(100))  # @ 100.10
        broker.set_price("RELIANCE", 200.0)
        broker.place_order(buy(100))  # @ 200.20

        position = broker.positions()[0]
        assert position.quantity == 200
        assert position.average_price == pytest.approx(150.15)

    def test_partial_close_keeps_the_original_cost_basis(self, broker: PaperBroker) -> None:
        broker.place_order(buy(200))
        entry = broker.positions()[0].average_price

        broker.set_price("RELIANCE", 120.0)
        broker.place_order(sell(100))

        position = broker.positions()[0]
        assert position.quantity == 100
        assert position.average_price == pytest.approx(entry)

    def test_flat_position_disappears_from_the_book(self, broker: PaperBroker) -> None:
        broker.place_order(buy(100))
        broker.place_order(sell(100))
        assert broker.positions() == []

    def test_unrealised_pnl_marks_to_market(self, broker: PaperBroker) -> None:
        broker.place_order(buy(100))
        broker.set_price("RELIANCE", 110.0)
        assert broker.positions()[0].pnl == pytest.approx(100 * (110.0 - 100.10), abs=0.01)


class TestGuards:
    def test_insufficient_funds_rejects_the_order(self) -> None:
        broker = PaperBroker(starting_cash=1000.0)
        broker.set_price("RELIANCE", 100.0)

        with pytest.raises(InsufficientFundsError):
            broker.place_order(buy(1000))  # needs 100k, has 1k

    def test_a_limit_order_with_no_price_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="LIMIT order needs a price"):
            OrderRequest(
                symbol="X",
                exchange="NSE",
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.LIMIT,
            )

    def test_a_stop_order_with_no_trigger_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="needs a trigger_price"):
            OrderRequest(
                symbol="X",
                exchange="NSE",
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.SL_M,
            )

    def test_zero_quantity_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            OrderRequest(symbol="X", exchange="NSE", side=OrderSide.BUY, quantity=0)

    def test_cancelling_a_filled_order_fails(self, broker: PaperBroker) -> None:
        order = broker.place_order(buy())
        with pytest.raises(OrderNotFoundError, match="already COMPLETE"):
            broker.cancel_order(order.order_id)

    def test_cancelling_a_resting_order_works(self, broker: PaperBroker) -> None:
        order = broker.place_order(buy(order_type=OrderType.LIMIT, price=50.0))
        cancelled = broker.cancel_order(order.order_id)
        assert cancelled.status is OrderStatus.CANCELLED

    def test_margins_reflect_cash_and_exposure(self, broker: PaperBroker) -> None:
        broker.place_order(buy(100))
        margins = broker.margins()
        assert margins.available_cash < 1_000_000.0
        assert margins.used_margin > 0
