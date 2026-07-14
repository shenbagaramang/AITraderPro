"""Historical candles.

The honest situation: TradingView has no public read API, and Kite's historical
endpoint is a paid add-on. So candles arrive one of three ways, tried in order:

1. Inline with the request (the analysis endpoints accept raw OHLCV) — always works
2. Kite historical API, if a live session exists AND the subscription is active
3. Nowhere — in which case the error says exactly that, instead of a mock
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

REQUIRED = ("open", "high", "low", "close", "volume")

INTERVALS = {"minute", "5minute", "15minute", "30minute", "60minute", "day"}


class NoCandleSourceError(AppError):
    status_code = 422
    code = "no_candle_source"
    message = (
        "No candle source available. Either include candles inline in the request, "
        "or connect a Kite session with the historical-data subscription."
    )


def frame_from_payload(rows: list[dict]) -> pd.DataFrame:
    """Inline candles -> validated OHLCV frame with a DatetimeIndex."""
    if not rows:
        raise AppError("candles list is empty", code="empty_candles")
    if len(rows) > 5000:
        raise AppError("too many candles (max 5000)", code="too_many_candles")

    df = pd.DataFrame(rows)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise AppError(
            f"candles are missing column(s): {', '.join(missing)}",
            code="bad_candles",
        )

    if "timestamp" in df.columns:
        df.index = pd.to_datetime(df["timestamp"])
        df = df.drop(columns=["timestamp"]).sort_index()
    for col in REQUIRED:
        df[col] = df[col].astype("float64")
    return df


def frame_from_kite(
    kite: object, instrument_token: int, interval: str = "day", days: int = 365
) -> pd.DataFrame:
    """Kite historical -> OHLCV frame. Raises honestly if the subscription is missing."""
    if interval not in INTERVALS:
        raise AppError(f"interval must be one of {sorted(INTERVALS)}", code="bad_interval")

    to_date = datetime.now(UTC)
    from_date = to_date - timedelta(days=days)

    try:
        rows = kite.historical_data(  # type: ignore[attr-defined]
            instrument_token, from_date, to_date, interval
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "subscri" in message.lower() or "permission" in message.lower():
            raise NoCandleSourceError(
                "Kite historical data requires the paid historical add-on on your "
                "API key — this key does not have it"
            ) from exc
        raise AppError(f"Kite historical fetch failed: {message}") from exc

    if not rows:
        raise NoCandleSourceError("Kite returned no candles for that range")

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["date"])
    return df[["open", "high", "low", "close", "volume"]].astype("float64")
