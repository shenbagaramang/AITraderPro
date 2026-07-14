"""Scanner layer.

A scanner applies *criteria* to indicator output. It computes no math of its own
— every number it reasons about comes from ``app.indicators``. That is what stops
the EMA in the EMA scanner from drifting away from the EMA in the technical agent.

Scanners are also pure: OHLCV in, ``Signal`` list out. No DB, no broker. The
service layer feeds them candles and persists what comes back.
"""

from app.scanners.adx_scanner import AdxScanner
from app.scanners.base import Scanner, ScanRequest, Signal, SignalDirection
from app.scanners.bb_scanner import BollingerScanner
from app.scanners.breakout_scanner import BreakoutScanner
from app.scanners.ema_scanner import EmaScanner
from app.scanners.ichimoku_scanner import IchimokuScanner
from app.scanners.momentum_scanner import MomentumScanner
from app.scanners.registry import SCANNERS, get_scanner, run_all
from app.scanners.volume_scanner import VolumeScanner
from app.scanners.vwap_scanner import VwapScanner

__all__ = [
    "SCANNERS",
    "AdxScanner",
    "BollingerScanner",
    "BreakoutScanner",
    "EmaScanner",
    "IchimokuScanner",
    "MomentumScanner",
    "ScanRequest",
    "Scanner",
    "Signal",
    "SignalDirection",
    "VolumeScanner",
    "VwapScanner",
    "get_scanner",
    "run_all",
]
