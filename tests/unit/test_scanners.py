"""Scanner tests: construct the setup, assert the scanner sees it."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.scanners import (
    SCANNERS,
    BollingerScanner,
    BreakoutScanner,
    EmaScanner,
    MomentumScanner,
    SignalDirection,
    VolumeScanner,
    VwapScanner,
    get_scanner,
    run_all,
)
from tests.fixtures import flat, make_ohlcv, trending


class TestScannerBase:
    def test_short_history_is_neutral_not_an_exception(self) -> None:
        """A thinly-traded symbol must not take the whole scan down."""
        signal = EmaScanner().scan("TINY", make_ohlcv([100.0] * 10))
        assert signal.direction is SignalDirection.NEUTRAL
        assert "insufficient history" in signal.reason

    def test_strength_is_bounded(self) -> None:
        with pytest.raises(ValueError, match=r"strength must be in \[0, 1\]"):
            from app.scanners.base import Signal

            Signal("x", "Y", SignalDirection.BULLISH, 1.5, "impossible")

    def test_neutral_signals_are_not_actionable(self) -> None:
        assert not EmaScanner().neutral("X", "nothing").is_actionable


class TestEmaScanner:
    def test_detects_a_golden_cross(self) -> None:
        # Long decline, then a sharp reversal. The rally is kept to 9 bars so the
        # cross is still inside cross_lookback=3 — a longer rally would make this
        # an old, established trend, which is a different signal entirely.
        closes = np.r_[
            trending(80, start=200.0, drift=-1.0), trending(9, start=121.0, drift=4.0)
        ]
        signal = EmaScanner().scan("RELIANCE", make_ohlcv(closes))

        assert signal.direction is SignalDirection.BULLISH
        assert "crossed above" in signal.reason
        assert signal.metrics["ema_9"] > signal.metrics["ema_21"]

    def test_steady_uptrend_is_alignment_not_a_cross(self) -> None:
        signal = EmaScanner().scan("TCS", make_ohlcv(trending(150, drift=1.0)))

        assert signal.direction is SignalDirection.BULLISH
        assert "aligned" in signal.reason
        # An old trend must score below a fresh cross.
        assert signal.strength == pytest.approx(0.4)

    def test_downtrend_is_bearish(self) -> None:
        signal = EmaScanner().scan("X", make_ohlcv(trending(150, start=300.0, drift=-1.0)))
        assert signal.direction is SignalDirection.BEARISH


class TestBreakoutScanner:
    def test_breakout_on_high_volume_is_confirmed(self) -> None:
        closes = np.r_[flat(80, 100.0), [104.0]]
        volumes = np.r_[np.full(80, 100_000.0), [400_000.0]]
        signal = BreakoutScanner().scan("INFY", make_ohlcv(closes, volumes))

        assert signal.direction is SignalDirection.BULLISH
        assert "confirmed by" in signal.reason
        assert signal.metrics["rvol"] > 1.5
        assert signal.strength > 0.6

    def test_breakout_on_thin_volume_is_penalised(self) -> None:
        """Same price action, no participation: reported, but heavily discounted."""
        closes = np.r_[flat(80, 100.0), [104.0]]
        volumes = np.r_[np.full(80, 100_000.0), [60_000.0]]
        signal = BreakoutScanner().scan("INFY", make_ohlcv(closes, volumes))

        assert signal.direction is SignalDirection.BULLISH
        assert "UNCONFIRMED" in signal.reason
        assert signal.strength < 0.5

    def test_inside_the_range_is_neutral(self) -> None:
        signal = BreakoutScanner().scan("X", make_ohlcv(flat(100, 100.0)))
        assert signal.direction is SignalDirection.NEUTRAL
        assert "inside" in signal.reason

    def test_breakdown_is_bearish(self) -> None:
        closes = np.r_[flat(80, 100.0), [95.0]]
        volumes = np.r_[np.full(80, 100_000.0), [400_000.0]]
        signal = BreakoutScanner().scan("X", make_ohlcv(closes, volumes))
        assert signal.direction is SignalDirection.BEARISH


class TestVolumeScanner:
    def test_spike_closing_on_the_high_is_accumulation(self) -> None:
        df = make_ohlcv(
            np.r_[flat(60, 100.0), [103.0]], np.r_[np.full(60, 100_000.0), [350_000.0]]
        )
        # Force the last bar to close at its high.
        df.iloc[-1, df.columns.get_loc("high")] = 103.0
        df.iloc[-1, df.columns.get_loc("low")] = 101.0

        signal = VolumeScanner().scan("SBIN", df)
        assert signal.direction is SignalDirection.BULLISH
        assert signal.metrics["close_location"] == pytest.approx(1.0)

    def test_same_spike_closing_on_the_low_is_distribution(self) -> None:
        """Volume has no direction of its own — the close decides."""
        df = make_ohlcv(
            np.r_[flat(60, 100.0), [101.0]], np.r_[np.full(60, 100_000.0), [350_000.0]]
        )
        df.iloc[-1, df.columns.get_loc("high")] = 103.0
        df.iloc[-1, df.columns.get_loc("low")] = 101.0

        signal = VolumeScanner().scan("SBIN", df)
        assert signal.direction is SignalDirection.BEARISH
        assert signal.metrics["close_location"] == pytest.approx(0.0)

    def test_spike_closing_mid_range_is_churn(self) -> None:
        df = make_ohlcv(
            np.r_[flat(60, 100.0), [102.0]], np.r_[np.full(60, 100_000.0), [350_000.0]]
        )
        df.iloc[-1, df.columns.get_loc("high")] = 103.0
        df.iloc[-1, df.columns.get_loc("low")] = 101.0

        signal = VolumeScanner().scan("SBIN", df)
        assert signal.direction is SignalDirection.NEUTRAL
        assert "churn" in signal.reason

    def test_normal_volume_is_neutral(self) -> None:
        signal = VolumeScanner().scan("X", make_ohlcv(flat(60, 100.0)))
        assert signal.direction is SignalDirection.NEUTRAL
        assert "normal" in signal.reason


class TestBollingerScanner:
    def test_squeeze_firing_upward_scores_high(self) -> None:
        rng = np.random.default_rng(11)
        wide = 100 + rng.normal(0, 3.0, 120).cumsum() * 0.1
        tight = np.full(30, float(wide[-1])) + rng.normal(0, 0.05, 30)
        closes = np.r_[wide, tight, [float(tight[-1]) + 4.0]]

        signal = BollingerScanner().scan("HDFCBANK", make_ohlcv(closes))
        assert signal.direction is SignalDirection.BULLISH
        assert "squeeze fired" in signal.reason
        assert signal.strength == pytest.approx(0.9)

    def test_squeeze_still_building_is_neutral_but_reported(self) -> None:
        rng = np.random.default_rng(11)
        wide = 100 + rng.normal(0, 3.0, 120).cumsum() * 0.1
        tight = np.full(30, float(wide[-1])) + rng.normal(0, 0.05, 30)

        signal = BollingerScanner().scan("HDFCBANK", make_ohlcv(np.r_[wide, tight]))
        assert signal.direction is SignalDirection.NEUTRAL
        assert "squeeze building" in signal.reason
        assert "bandwidth" in signal.metrics

    def test_price_inside_the_bands_is_neutral(self) -> None:
        signal = BollingerScanner().scan("X", make_ohlcv(flat(200, 100.0, noise=1.0)))
        assert signal.direction is SignalDirection.NEUTRAL


class TestMomentumScanner:
    def test_overbought_alone_is_not_a_short(self) -> None:
        """RSI > 70 in a trend is strength, not a sell signal."""
        signal = MomentumScanner().scan("X", make_ohlcv(trending(150, drift=1.5)))

        assert signal.metrics["rsi"] > 70
        assert signal.direction is SignalDirection.BULLISH
        assert "not a short signal" in signal.reason

    def test_oversold_alone_is_not_a_long(self) -> None:
        signal = MomentumScanner().scan(
            "X", make_ohlcv(trending(150, start=300.0, drift=-1.5))
        )
        assert signal.metrics["rsi"] < 30
        assert signal.direction is SignalDirection.BEARISH
        assert "not a long signal" in signal.reason

    def test_macd_cross_up_is_bullish(self) -> None:
        closes = np.r_[
            trending(90, start=200.0, drift=-1.0), trending(20, start=111.0, drift=3.0)
        ]
        signal = MomentumScanner().scan("X", make_ohlcv(closes))
        assert signal.direction is SignalDirection.BULLISH


class TestVwapScanner:
    def test_reclaim_is_bullish(self) -> None:
        closes = np.r_[np.full(40, 100.0), np.full(8, 98.0), [103.0, 104.0]]
        signal = VwapScanner().scan("X", make_ohlcv(closes, intraday=True))
        assert signal.direction is SignalDirection.BULLISH
        assert "reclaimed VWAP" in signal.reason

    def test_daily_data_is_rejected_gracefully(self) -> None:
        """VWAP is an intraday concept; on a daily frame it must decline, not lie."""
        df = make_ohlcv(flat(60, 100.0)).reset_index(drop=True)
        signal = VwapScanner().scan("X", df)
        assert signal.direction is SignalDirection.NEUTRAL
        assert "DatetimeIndex" in signal.reason


class TestRegistry:
    def test_all_eight_scanners_are_registered(self) -> None:
        assert set(SCANNERS) == {
            "ema",
            "breakout",
            "volume",
            "bollinger",
            "momentum",
            "vwap",
            "adx",
            "ichimoku",
        }

    def test_run_all_returns_one_signal_per_scanner(self) -> None:
        signals = run_all("X", make_ohlcv(trending(200), intraday=True))
        assert len(signals) == len(SCANNERS)
        assert {s.scanner for s in signals} == set(SCANNERS)

    def test_a_failing_scanner_does_not_sink_the_others(self) -> None:
        class Exploding(EmaScanner):
            name = "ema"

            def evaluate(self, symbol: str, df: pd.DataFrame):  # type: ignore[override]
                raise RuntimeError("boom")

        SCANNERS["ema"] = Exploding
        try:
            signals = run_all("X", make_ohlcv(trending(200), intraday=True))
            failed = next(s for s in signals if s.scanner == "ema")
            assert failed.direction is SignalDirection.NEUTRAL
            assert "boom" in failed.reason
            assert len(signals) == len(SCANNERS)  # the other five survived
        finally:
            SCANNERS["ema"] = EmaScanner

    def test_params_are_passed_through(self) -> None:
        assert get_scanner("ema", fast=5, slow=13).params["fast"] == 5

    def test_unknown_scanner_lists_the_known_ones(self) -> None:
        with pytest.raises(KeyError, match="available"):
            get_scanner("astrology")

    def test_only_filter_runs_a_subset(self) -> None:
        signals = run_all("X", make_ohlcv(trending(200)), only=["ema", "momentum"])
        assert {s.scanner for s in signals} == {"ema", "momentum"}
