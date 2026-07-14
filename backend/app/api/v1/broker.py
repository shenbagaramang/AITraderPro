"""Broker session and portfolio endpoints.

Broker SDK calls are synchronous by design (see brokers/base.py), so every call
into a Broker goes through ``run_in_threadpool`` rather than blocking the event
loop and stalling every other request in the process.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.brokers.base import Quote
from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.schemas.broker import (
    BrokerStatusResponse,
    CompleteLoginRequest,
    HoldingResponse,
    LoginUrlResponse,
    MarginsResponse,
    PaperResetResponse,
    PositionResponse,
    QuoteResponse,
)
from app.schemas.common import Message
from app.services.broker_service import broker_service

router = APIRouter()


@router.get("/status", response_model=BrokerStatusResponse, summary="Kite session status")
async def status(user: CurrentUser, db: DbSession) -> BrokerStatusResponse:
    return BrokerStatusResponse(**(await broker_service.status(db, user)))  # type: ignore[arg-type]


@router.get(
    "/kite/login-url",
    response_model=LoginUrlResponse,
    summary="Step 1 of the daily Kite login",
)
async def login_url(_: CurrentUser) -> LoginUrlResponse:
    url = await run_in_threadpool(broker_service.login_url)
    return LoginUrlResponse(login_url=url)


@router.post(
    "/kite/session",
    response_model=BrokerStatusResponse,
    summary="Step 2: exchange the request_token",
)
async def complete_login(
    payload: CompleteLoginRequest, user: CurrentUser, db: DbSession
) -> BrokerStatusResponse:
    await broker_service.complete_login(db, user, payload.request_token)
    return BrokerStatusResponse(**(await broker_service.status(db, user)))  # type: ignore[arg-type]


@router.delete("/kite/session", response_model=Message, summary="Disconnect Kite")
async def disconnect(user: CurrentUser, db: DbSession) -> Message:
    await broker_service.disconnect(db, user)
    return Message(message="Kite session disconnected")


@router.get("/positions", response_model=list[PositionResponse], summary="Open positions")
async def positions(
    user: CurrentUser, db: DbSession, paper: bool | None = None
) -> list[PositionResponse]:
    broker = await broker_service.get_broker(db, user, paper=paper)
    rows = await run_in_threadpool(broker.positions)
    return [
        PositionResponse(
            symbol=p.symbol,
            exchange=p.exchange,
            quantity=p.quantity,
            average_price=p.average_price,
            last_price=p.last_price,
            pnl=p.pnl,
            value=p.value,
        )
        for p in rows
    ]


@router.get("/holdings", response_model=list[HoldingResponse], summary="Delivery holdings")
async def holdings(
    user: CurrentUser, db: DbSession, paper: bool | None = None
) -> list[HoldingResponse]:
    broker = await broker_service.get_broker(db, user, paper=paper)
    rows = await run_in_threadpool(broker.holdings)
    return [
        HoldingResponse(
            symbol=h.symbol,
            exchange=h.exchange,
            quantity=h.quantity,
            average_price=h.average_price,
            last_price=h.last_price,
            pnl=h.pnl,
            value=h.value,
        )
        for h in rows
    ]


@router.get("/margins", response_model=MarginsResponse, summary="Available margin")
async def margins(
    user: CurrentUser, db: DbSession, paper: bool | None = None
) -> MarginsResponse:
    broker = await broker_service.get_broker(db, user, paper=paper)
    m = await run_in_threadpool(broker.margins)
    return MarginsResponse(
        available_cash=m.available_cash, used_margin=m.used_margin, net=m.net
    )


@router.get("/quotes", response_model=dict[str, QuoteResponse], summary="Quotes")
async def quotes(
    symbols: str, user: CurrentUser, db: DbSession, paper: bool | None = None
) -> dict[str, QuoteResponse]:
    """``symbols`` is comma-separated, e.g. ``NSE:RELIANCE,NSE:TCS`` for Kite or
    plain symbols for the paper broker."""
    wanted = [s.strip() for s in symbols.split(",") if s.strip()][:50]
    broker = await broker_service.get_broker(db, user, paper=paper)
    raw: dict[str, Quote] = await run_in_threadpool(broker.quote, wanted)
    return {
        key: QuoteResponse(
            symbol=q.symbol,
            last_price=q.last_price,
            volume=q.volume,
            open=q.open,
            high=q.high,
            low=q.low,
            close=q.close,
            change_pct=q.change_pct,
            timestamp=q.timestamp,
        )
        for key, q in raw.items()
    }


@router.post(
    "/paper/reset",
    response_model=PaperResetResponse,
    summary="Reset the paper account to its starting cash",
)
async def reset_paper(user: CurrentUser) -> PaperResetResponse:
    broker_service.reset_paper(user.id)
    return PaperResetResponse(
        message="Paper account reset", starting_cash=settings.PAPER_STARTING_CASH
    )
