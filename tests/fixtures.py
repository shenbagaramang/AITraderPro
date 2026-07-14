"""Synthetic OHLCV builders. Deterministic, so scanner tests assert on real setups."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(
    closes: list[float] | np.ndarray,
    volumes: list[float] | np.ndarray | None = None,
    *,
    intraday: bool = False,
    spread: float = 0.5,
) -> pd.DataFrame:
    """Build an OHLCV frame from a close series, with a constant high/low spread."""
    closes = np.asarray(closes, dtype="float64")
    n = len(closes)

    if volumes is None:
        volumes = np.full(n, 100_000.0)
    volumes = np.asarray(volumes, dtype="float64")

    index = (
        pd.date_range("2026-01-05 09:15", periods=n, freq="5min")
        if intraday
        else pd.date_range("2025-01-01", periods=n, freq="B")
    )

    return pd.DataFrame(
        {
            "open": np.r_[closes[0], closes[:-1]],
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def trending(n: int = 120, start: float = 100.0, drift: float = 0.5) -> np.ndarray:
    return start + drift * np.arange(n, dtype="float64")


def flat(n: int = 120, level: float = 100.0, noise: float = 0.3, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level + rng.normal(0.0, noise, n)
