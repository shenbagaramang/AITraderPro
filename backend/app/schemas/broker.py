"""Request/response contracts for broker and order endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.brokers.base import OrderSide, OrderType, Product


class BrokerStatusResponse(BaseModel):
    connected: bool
    needs_login: bool
    broker: str
    broker_user_id: str | None = None
    expires_at: datetime | None = None


class LoginUrlResponse(BaseModel):
    login_url: str
    note: str = (
        "Open this URL, log in to Kite, and you will be redirected back with a "
        "request_token. POST it to /broker/kite/session."
    )


class CompleteLoginRequest(BaseModel):
    request_token: str = Field(..., min_length=8, max_length=128)


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: OrderSide
    quantity: int = Field(..., gt=0, le=1_000_000)
    exchange: str = Field("NSE", max_length=16)
    product: Product = Product.CNC
    order_type: OrderType = OrderType.MARKET
    price: float | None = Field(None, gt=0)
    trigger_price: float | None = Field(None, gt=0)
    stop_loss: float | None = Field(None, gt=0)
    target: float | None = Field(None, gt=0)
    idempotency_key: str | None = Field(None, max_length=64)
    paper: bool | None = Field(
        None,
        description=(
            "Force paper (true) or live (false). Omit to follow "
            "LIVE_TRADING_ENABLED, which defaults to paper."
        ),
    )

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    idempotency_key: str
    broker: str
    broker_order_id: str | None
    symbol: str
    exchange: str
    side: str
    quantity: int
    filled_quantity: int
    product: str
    order_type: str
    price: float | None
    trigger_price: float | None
    average_price: float | None
    status: str
    status_message: str | None
    is_paper: bool
    stop_loss: float | None
    target: float | None
    placed_at: datetime | None
    created_at: datetime


class PositionResponse(BaseModel):
    symbol: str
    exchange: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    value: float


class HoldingResponse(BaseModel):
    symbol: str
    exchange: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    value: float


class MarginsResponse(BaseModel):
    available_cash: float
    used_margin: float
    net: float


class QuoteResponse(BaseModel):
    symbol: str
    last_price: float
    volume: int
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change_pct: float | None
    timestamp: datetime | None


class PaperResetResponse(BaseModel):
    message: str
    starting_cash: float
