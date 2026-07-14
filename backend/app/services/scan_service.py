"""The scan loop: watchlist in, persisted results and *new* alerts out.

Design points:

- **Candles are supplied, not fetched.** The service takes a per-symbol candle
  map. Where they come from (your n8n pipeline, a Kite historical subscription,
  a CSV) is the caller's business; the loop stays pure enough to test.
- **A symbol with no candles is reported, not fatal.** One missing feed must not
  kill a 40-symbol scan.
- **Alerts fire on state CHANGE only.** For each (symbol, scanner) pair the new
  signal is diffed against the most recent persisted result; an alert is raised
  when it becomes actionable from neutral, or flips direction. Same signal on a
  rescan raises nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.scan import ScannerAlert, ScanResult
from app.models.user import User
from app.models.watchlist import Watchlist
from app.scanners import run_all
from app.scanners.base import Signal

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    watchlist: str
    scanned: list[str]
    skipped: dict[str, str]  # symbol -> why
    actionable: list[dict]  # non-neutral signals this run
    new_alerts: list[dict]  # state changes only
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ScanService:
    async def run_watchlist(
        self,
        db: AsyncSession,
        user: User,
        watchlist: Watchlist,
        candles_by_symbol: dict[str, pd.DataFrame],
        *,
        only: list[str] | None = None,
    ) -> ScanSummary:
        scanned_at = datetime.now(UTC)
        scanned: list[str] = []
        skipped: dict[str, str] = {}
        actionable: list[dict] = []
        new_alerts: list[dict] = []

        for symbol in watchlist.symbols:
            df = candles_by_symbol.get(symbol)
            if df is None or df.empty:
                skipped[symbol] = "no candles supplied"
                continue

            try:
                signals = run_all(symbol, df, only=only)
            except Exception as exc:  # noqa: BLE001 - one symbol must not sink the scan
                skipped[symbol] = f"scan failed: {exc}"
                continue

            scanned.append(symbol)

            # The diff baseline: last persisted state per scanner, BEFORE this
            # run's rows are written.
            previous = await self._last_states(db, user.id, symbol)

            for signal in signals:
                db.add(
                    ScanResult(
                        user_id=user.id,
                        watchlist_id=watchlist.id,
                        symbol=symbol,
                        scanner=signal.scanner,
                        direction=signal.direction.value,
                        strength=signal.strength,
                        reason=signal.reason,
                        metrics_json=json.dumps(signal.metrics) if signal.metrics else None,
                        scanned_at=scanned_at,
                    )
                )

                if signal.is_actionable:
                    actionable.append(self._as_dict(signal))

                if self._is_new(signal, previous.get(signal.scanner)):
                    alert = ScannerAlert(
                        user_id=user.id,
                        symbol=symbol,
                        scanner=signal.scanner,
                        direction=signal.direction.value,
                        strength=signal.strength,
                        reason=signal.reason,
                    )
                    db.add(alert)
                    new_alerts.append(self._as_dict(signal))

        await db.commit()
        logger.info(
            "scan '%s': %d scanned, %d skipped, %d actionable, %d NEW alerts",
            watchlist.name,
            len(scanned),
            len(skipped),
            len(actionable),
            len(new_alerts),
        )
        return ScanSummary(
            watchlist=watchlist.name,
            scanned=scanned,
            skipped=skipped,
            actionable=actionable,
            new_alerts=new_alerts,
            scanned_at=scanned_at,
        )

    # --- internals -----------------------------------------------------------
    async def _last_states(
        self, db: AsyncSession, user_id: int, symbol: str
    ) -> dict[str, str]:
        """Most recent persisted direction per scanner for this symbol."""
        stmt = (
            select(ScanResult.scanner, ScanResult.direction, ScanResult.id)
            .where(ScanResult.user_id == user_id, ScanResult.symbol == symbol)
            .order_by(ScanResult.id.desc())
            .limit(64)  # 8 scanners; 64 covers several runs comfortably
        )
        rows = (await db.execute(stmt)).all()
        latest: dict[str, str] = {}
        for scanner, direction, _ in rows:
            latest.setdefault(scanner, direction)  # first seen = most recent
        return latest

    @staticmethod
    def _is_new(signal: Signal, previous_direction: str | None) -> bool:
        if not signal.is_actionable:
            return False
        if previous_direction is None:
            return True  # first ever sighting
        return previous_direction != signal.direction.value

    @staticmethod
    def _as_dict(signal: Signal) -> dict:
        return {
            "symbol": signal.symbol,
            "scanner": signal.scanner,
            "direction": signal.direction.value,
            "strength": signal.strength,
            "reason": signal.reason,
        }


scan_service = ScanService()
