"""Watchlist CRUD, the scan trigger, and the alert inbox."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.v1.analysis import CandleRow
from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.models.scan import ScannerAlert, ScanResult
from app.models.watchlist import Watchlist
from app.schemas.common import Message
from app.services.candle_service import frame_from_payload
from app.services.scan_service import scan_service

router = APIRouter()


# --- schemas -----------------------------------------------------------------
class WatchlistIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    symbols: list[str] = Field(default_factory=list, max_length=100)


class WatchlistOut(BaseModel):
    id: int
    name: str
    symbols: list[str]


class RunScanRequest(BaseModel):
    candles: dict[str, list[CandleRow]] = Field(
        ...,
        description=(
            "Per-symbol OHLCV, at least 30 rows each. Symbols on the watchlist "
            "but absent here are skipped and reported, not failed."
        ),
    )
    only: list[str] | None = Field(None, description="Optional scanner subset")


class ScanSummaryOut(BaseModel):
    watchlist: str
    scanned: list[str]
    skipped: dict[str, str]
    actionable: list[dict[str, Any]]
    new_alerts: list[dict[str, Any]]


class AlertOut(BaseModel):
    id: int
    symbol: str
    scanner: str
    direction: str
    strength: float
    reason: str
    acknowledged: bool
    created_at: Any


class ResultOut(BaseModel):
    symbol: str
    scanner: str
    direction: str
    strength: float
    reason: str
    scanned_at: Any


# --- watchlists ----------------------------------------------------------------
@router.get("/watchlists", response_model=list[WatchlistOut], summary="My watchlists")
async def list_watchlists(user: CurrentUser, db: DbSession) -> list[WatchlistOut]:
    stmt = select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [WatchlistOut(id=w.id, name=w.name, symbols=w.symbols) for w in rows]


@router.post(
    "/watchlists",
    response_model=WatchlistOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a watchlist",
)
async def create_watchlist(
    payload: WatchlistIn, user: CurrentUser, db: DbSession
) -> WatchlistOut:
    existing = await _by_name(db, user.id, payload.name)
    if existing:
        raise ConflictError(f"a watchlist named {payload.name!r} already exists")

    watchlist = Watchlist(user_id=user.id, name=payload.name)
    watchlist.symbols = payload.symbols
    db.add(watchlist)
    await db.commit()
    await db.refresh(watchlist)
    return WatchlistOut(id=watchlist.id, name=watchlist.name, symbols=watchlist.symbols)


@router.put("/watchlists/{watchlist_id}", response_model=WatchlistOut, summary="Replace")
async def update_watchlist(
    watchlist_id: int, payload: WatchlistIn, user: CurrentUser, db: DbSession
) -> WatchlistOut:
    watchlist = await _require(db, user.id, watchlist_id)
    watchlist.name = payload.name
    watchlist.symbols = payload.symbols
    db.add(watchlist)
    await db.commit()
    await db.refresh(watchlist)
    return WatchlistOut(id=watchlist.id, name=watchlist.name, symbols=watchlist.symbols)


@router.delete("/watchlists/{watchlist_id}", response_model=Message, summary="Delete")
async def delete_watchlist(watchlist_id: int, user: CurrentUser, db: DbSession) -> Message:
    watchlist = await _require(db, user.id, watchlist_id)
    await db.delete(watchlist)
    await db.commit()
    return Message(message=f"watchlist {watchlist.name!r} deleted")


# --- scanning --------------------------------------------------------------------
@router.post(
    "/watchlists/{watchlist_id}/scan",
    response_model=ScanSummaryOut,
    summary="Run the scanner battery across a watchlist",
)
async def run_scan(
    watchlist_id: int, payload: RunScanRequest, user: CurrentUser, db: DbSession
) -> ScanSummaryOut:
    watchlist = await _require(db, user.id, watchlist_id)

    frames = {}
    for symbol, rows in payload.candles.items():
        try:
            frames[symbol.upper()] = frame_from_payload([r.model_dump() for r in rows])
        except Exception:  # noqa: BLE001 - bad candles for one symbol -> skip it
            continue

    summary = await scan_service.run_watchlist(db, user, watchlist, frames, only=payload.only)
    return ScanSummaryOut(
        watchlist=summary.watchlist,
        scanned=summary.scanned,
        skipped=summary.skipped,
        actionable=summary.actionable,
        new_alerts=summary.new_alerts,
    )


@router.get("/results", response_model=list[ResultOut], summary="Recent scan results")
async def results(
    user: CurrentUser,
    db: DbSession,
    symbol: str | None = None,
    actionable_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
) -> list[ResultOut]:
    stmt = select(ScanResult).where(ScanResult.user_id == user.id)
    if symbol:
        stmt = stmt.where(ScanResult.symbol == symbol.upper())
    if actionable_only:
        stmt = stmt.where(ScanResult.direction != "neutral")
    stmt = stmt.order_by(ScanResult.id.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        ResultOut(
            symbol=r.symbol,
            scanner=r.scanner,
            direction=r.direction,
            strength=r.strength,
            reason=r.reason,
            scanned_at=r.scanned_at,
        )
        for r in rows
    ]


# --- alerts ------------------------------------------------------------------------
@router.get("/alerts", response_model=list[AlertOut], summary="Alert inbox")
async def alerts(
    user: CurrentUser,
    db: DbSession,
    unacknowledged_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
) -> list[AlertOut]:
    stmt = select(ScannerAlert).where(ScannerAlert.user_id == user.id)
    if unacknowledged_only:
        stmt = stmt.where(ScannerAlert.acknowledged.is_(False))
    stmt = stmt.order_by(ScannerAlert.id.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        AlertOut(
            id=a.id,
            symbol=a.symbol,
            scanner=a.scanner,
            direction=a.direction,
            strength=a.strength,
            reason=a.reason,
            acknowledged=a.acknowledged,
            created_at=a.created_at,
        )
        for a in rows
    ]


@router.post("/alerts/ack", response_model=Message, summary="Acknowledge alerts")
async def acknowledge(ids: list[int], user: CurrentUser, db: DbSession) -> Message:
    stmt = (
        update(ScannerAlert)
        .where(ScannerAlert.user_id == user.id, ScannerAlert.id.in_(ids))
        .values(acknowledged=True)
    )
    result = await db.execute(stmt)
    await db.commit()
    return Message(message=f"{result.rowcount} alert(s) acknowledged")


# --- internals --------------------------------------------------------------------
async def _by_name(db: DbSession, user_id: int, name: str) -> Watchlist | None:  # type: ignore[valid-type]
    stmt = select(Watchlist).where(Watchlist.user_id == user_id, Watchlist.name == name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _require(db: DbSession, user_id: int, watchlist_id: int) -> Watchlist:  # type: ignore[valid-type]
    stmt = select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
    watchlist = (await db.execute(stmt)).scalar_one_or_none()
    if watchlist is None:
        raise NotFoundError(f"watchlist {watchlist_id} not found")
    return watchlist
