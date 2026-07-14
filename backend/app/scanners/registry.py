"""Scanner registry: name -> class, plus a helper to run the full battery."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.scanners.adx_scanner import AdxScanner
from app.scanners.base import Scanner, Signal
from app.scanners.bb_scanner import BollingerScanner
from app.scanners.breakout_scanner import BreakoutScanner
from app.scanners.ema_scanner import EmaScanner
from app.scanners.ichimoku_scanner import IchimokuScanner
from app.scanners.momentum_scanner import MomentumScanner
from app.scanners.volume_scanner import VolumeScanner
from app.scanners.vwap_scanner import VwapScanner

SCANNERS: dict[str, type[Scanner]] = {
    EmaScanner.name: EmaScanner,
    BreakoutScanner.name: BreakoutScanner,
    VolumeScanner.name: VolumeScanner,
    BollingerScanner.name: BollingerScanner,
    MomentumScanner.name: MomentumScanner,
    VwapScanner.name: VwapScanner,
    AdxScanner.name: AdxScanner,
    IchimokuScanner.name: IchimokuScanner,
}


def get_scanner(name: str, **params: Any) -> Scanner:
    try:
        return SCANNERS[name](**params)
    except KeyError as exc:
        known = ", ".join(sorted(SCANNERS))
        raise KeyError(f"unknown scanner {name!r}; available: {known}") from exc


def run_all(
    symbol: str,
    df: pd.DataFrame,
    *,
    only: list[str] | None = None,
    params: dict[str, dict[str, Any]] | None = None,
) -> list[Signal]:
    """Run every scanner (or a subset) against one symbol's candles.

    One scanner blowing up must not lose the other results, so failures are
    downgraded to a neutral signal carrying the error text.
    """
    names = only or list(SCANNERS)
    params = params or {}
    results: list[Signal] = []

    for name in names:
        scanner = get_scanner(name, **params.get(name, {}))
        try:
            results.append(scanner.scan(symbol, df))
        except Exception as exc:  # noqa: BLE001 - one bad scanner must not sink the scan
            results.append(scanner.neutral(symbol, f"scanner failed: {exc}"))

    return results
