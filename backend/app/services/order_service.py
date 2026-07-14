"""Order placement, with the two safeguards that matter.

**Idempotency.** A network timeout during order placement is ambiguous: the order
may or may not have reached the exchange. The instinctive response is to retry,
and that is how you end up holding twice the position you sized. Every order
carries an idempotency key with a UNIQUE constraint behind it, so a retry returns
the original order instead of placing a second one.

**The kill switch.** ``LIVE_TRADING_ENABLED`` defaults to false. Everything runs
against the paper broker until someone deliberately turns it on. A system that
defaults to live is a system where a misconfiguration spends money.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import (
    BrokerError,
    Order,
    OrderRequest,
    OrderSide,
    OrderType,
    Product,
)
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.order import OrderRecord, OrderStatusDB
from app.models.user import User
from app.services.broker_service import broker_service

logger = get_logger(__name__)


class TradingHaltedError(AppError):
    status_code = 423  # Locked
    code = "trading_halted"
    message = "Trading is halted"


class OrderService:
    async def place(
        self,
        db: AsyncSession,
        user: User,
        *,
        symbol: str,
        side: OrderSide,
        quantity: int,
        exchange: str = "NSE",
        product: Product = Product.CNC,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        trigger_price: float | None = None,
        stop_loss: float | None = None,
        target: float | None = None,
        idempotency_key: str | None = None,
        rationale: dict | None = None,
        paper: bool | None = None,
    ) -> OrderRecord:
        if settings.TRADING_HALTED:
            raise TradingHaltedError(
                "TRADING_HALTED is set — the kill switch is on. No orders will be placed."
            )

        key = idempotency_key or str(uuid.uuid4())

        # Idempotency check *before* touching the broker.
        existing = await self._by_key(db, key)
        if existing is not None:
            logger.info("Idempotent replay of %s -> order %s", key, existing.id)
            return existing

        broker = await broker_service.get_broker(db, user, paper=paper)
        is_paper = broker.name == "paper"

        record = OrderRecord(
            user_id=user.id,
            idempotency_key=key,
            broker=broker.name,
            symbol=symbol,
            exchange=exchange,
            side=side.value,
            quantity=quantity,
            product=product.value,
            order_type=order_type.value,
            price=price,
            trigger_price=trigger_price,
            stop_loss=stop_loss,
            target=target,
            status=OrderStatusDB.PENDING,
            is_paper=is_paper,
            rationale=json.dumps(rationale) if rationale else None,
            placed_at=datetime.now(UTC),
        )
        db.add(record)
        await db.flush()  # claim the idempotency key before the network call

        request = OrderRequest(
            symbol=symbol,
            exchange=exchange,
            side=side,
            quantity=quantity,
            product=product,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            idempotency_key=key,
        )

        try:
            placed: Order = broker.place_order(request)
        except BrokerError as exc:
            # The rejection is persisted, not swallowed. A rejected order is data.
            record.status = OrderStatusDB.REJECTED
            record.status_message = str(exc)[:255]
            db.add(record)
            db.add(
                AuditLog(
                    user_id=user.id,
                    action="order.rejected",
                    resource=symbol,
                    detail=str(exc)[:500],
                )
            )
            await db.commit()
            await db.refresh(record)
            return record

        record.broker_order_id = placed.order_id
        record.status = OrderStatusDB(placed.status.value)
        record.filled_quantity = placed.filled_quantity
        record.average_price = placed.average_price
        record.status_message = placed.status_message

        db.add(record)
        db.add(
            AuditLog(
                user_id=user.id,
                action="order.placed" if not is_paper else "order.placed_paper",
                resource=symbol,
                detail=f"{side.value} {quantity} @ {placed.average_price or 'mkt'}",
            )
        )
        await db.commit()
        await db.refresh(record)

        logger.info(
            "%s order %s: %s %s x%d -> %s",
            "PAPER" if is_paper else "LIVE",
            record.id,
            side.value,
            symbol,
            quantity,
            record.status.value,
        )
        return record

    async def cancel(self, db: AsyncSession, user: User, order_id: int) -> OrderRecord:
        record = await self._require(db, user, order_id)
        if OrderStatusDB(record.status).value in ("COMPLETE", "CANCELLED", "REJECTED"):
            raise AppError(
                f"order is already {record.status.value} and cannot be cancelled",
                code="order_terminal",
            )

        broker = await broker_service.get_broker(db, user, paper=record.is_paper)
        if record.broker_order_id:
            cancelled = broker.cancel_order(record.broker_order_id)
            record.status = OrderStatusDB(cancelled.status.value)
        else:
            record.status = OrderStatusDB.CANCELLED

        db.add(record)
        db.add(AuditLog(user_id=user.id, action="order.cancelled", resource=record.symbol))
        await db.commit()
        await db.refresh(record)
        return record

    async def sync(self, db: AsyncSession, user: User, order_id: int) -> OrderRecord:
        """Pull the broker's view and reconcile ours to it. The broker is the
        source of truth about what actually happened."""
        record = await self._require(db, user, order_id)
        if not record.broker_order_id:
            return record

        broker = await broker_service.get_broker(db, user, paper=record.is_paper)
        live = broker.get_order(record.broker_order_id)

        record.status = OrderStatusDB(live.status.value)
        record.filled_quantity = live.filled_quantity
        record.average_price = live.average_price
        record.status_message = live.status_message

        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    async def list_orders(
        self, db: AsyncSession, user: User, *, limit: int = 50
    ) -> list[OrderRecord]:
        stmt = (
            select(OrderRecord)
            .where(OrderRecord.user_id == user.id)
            .order_by(OrderRecord.id.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

    # --- internals ---------------------------------------------------------
    async def _by_key(self, db: AsyncSession, key: str) -> OrderRecord | None:
        stmt = select(OrderRecord).where(OrderRecord.idempotency_key == key)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _require(self, db: AsyncSession, user: User, order_id: int) -> OrderRecord:
        stmt = select(OrderRecord).where(
            OrderRecord.id == order_id, OrderRecord.user_id == user.id
        )
        record = (await db.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise NotFoundError(f"order {order_id} not found")
        return record


order_service = OrderService()
