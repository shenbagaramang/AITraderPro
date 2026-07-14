"""Order endpoints. Placing an order is gated to trader/admin roles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import CurrentUser, DbSession, RequireRoles
from app.models.user import UserRole
from app.schemas.broker import OrderResponse, PlaceOrderRequest
from app.services.order_service import order_service

router = APIRouter()

can_trade = RequireRoles(UserRole.ADMIN, UserRole.TRADER)


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order (defaults to paper)",
    dependencies=[Depends(can_trade)],
)
async def place_order(
    payload: PlaceOrderRequest, user: CurrentUser, db: DbSession
) -> OrderResponse:
    record = await order_service.place(
        db,
        user,
        symbol=payload.symbol,
        side=payload.side,
        quantity=payload.quantity,
        exchange=payload.exchange,
        product=payload.product,
        order_type=payload.order_type,
        price=payload.price,
        trigger_price=payload.trigger_price,
        stop_loss=payload.stop_loss,
        target=payload.target,
        idempotency_key=payload.idempotency_key,
        paper=payload.paper,
    )
    return OrderResponse.model_validate(record)


@router.get("", response_model=list[OrderResponse], summary="Recent orders")
async def list_orders(
    user: CurrentUser, db: DbSession, limit: int = Query(50, ge=1, le=200)
) -> list[OrderResponse]:
    rows = await order_service.list_orders(db, user, limit=limit)
    return [OrderResponse.model_validate(r) for r in rows]


@router.get("/{order_id}", response_model=OrderResponse, summary="One order, synced")
async def get_order(order_id: int, user: CurrentUser, db: DbSession) -> OrderResponse:
    record = await order_service.sync(db, user, order_id)
    return OrderResponse.model_validate(record)


@router.delete(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Cancel a resting order",
    dependencies=[Depends(can_trade)],
)
async def cancel_order(order_id: int, user: CurrentUser, db: DbSession) -> OrderResponse:
    record = await order_service.cancel(db, user, order_id)
    return OrderResponse.model_validate(record)
