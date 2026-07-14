"""Indicator tests.

These assert against hand-computed values and known mathematical identities, not
against a snapshot of the code's own output — otherwise the test only proves the
code still does whatever it did last week.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    obv,
    relative_volume,
    rma,
    roc,
    rsi,
    sma,
    supertrend,
    true_range,
    vwap,
)
from app.indicators.base import IndicatorError
from tests.fixtures import make_ohlcv, trending


class TestEma:
    def test_matches_manual_recursion_seeded_with_sma(self) -> None:
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype="float64")
        result = ema(s, 5)

        alpha = 2 / 6
        expected = [s[:5].mean()]
        for value in [6, 7, 8, 9, 10]:
            expected.append(alpha * value + (1 - alpha) * expected[-1])

        assert np.allclose(result.dropna().to_numpy(), expected)

    def test_first_valid_value_is_the_sma(self) -> None:
        s = pd.Series(np.arange(1, 21, dtype="float64"))
        assert ema(s, 5).iloc[4] == pytest.approx(sma(s, 5).iloc[4])

    def test_nan_head_is_length_minus_one(self) -> None:
        assert ema(pd.Series(np.arange(20, dtype="float64")), 5).isna().sum() == 4

    def test_constant_series_returns_the_constant(self) -> None:
        s = pd.Series([7.0] * 30)
        assert np.allclose(ema(s, 10).dropna(), 7.0)

    def test_rejects_short_series(self) -> None:
        with pytest.raises(IndicatorError, match="need at least"):
            ema(pd.Series([1.0, 2.0]), 20)

    def test_rejects_bad_length(self) -> None:
        with pytest.raises(IndicatorError, match="positive integer"):
            ema(pd.Series(np.arange(30, dtype="float64")), 0)


class TestRma:
    def test_alpha_is_one_over_length_not_two_over_length_plus_one(self) -> None:
        """The bug that makes a Python RSI disagree with TradingView."""
        s = pd.Series([10.0] * 14 + [20.0])
        result = rma(s, 14)
        expected = (1 / 14) * 20.0 + (13 / 14) * 10.0
        assert result.iloc[-1] == pytest.approx(expected)
        assert result.iloc[-1] != pytest.approx(ema(s, 14).iloc[-1])


class TestRsi:
    def test_unbroken_advance_is_100(self) -> None:
        s = pd.Series(np.arange(1, 40, dtype="float64"))
        assert rsi(s, 14).iloc[-1] == pytest.approx(100.0)

    def test_unbroken_decline_is_0(self) -> None:
        s = pd.Series(np.arange(40, 1, -1, dtype="float64"))
        assert rsi(s, 14).iloc[-1] == pytest.approx(0.0)

    def test_stays_within_bounds(self) -> None:
        rng = np.random.default_rng(7)
        s = pd.Series(100 + rng.normal(0, 1, 300).cumsum())
        values = rsi(s, 14).dropna()
        assert values.between(0, 100).all()

    def test_first_valid_index_is_length(self) -> None:
        s = pd.Series(100 + np.random.default_rng(1).normal(0, 1, 60).cumsum())
        assert rsi(s, 14).first_valid_index() == 14


class TestMacd:
    def test_histogram_is_macd_minus_signal(self) -> None:
        s = pd.Series(100 + np.random.default_rng(3).normal(0, 1, 200).cumsum())
        frame = macd(s)
        assert np.allclose(
            (frame["macd"] - frame["signal"]).dropna(), frame["histogram"].dropna()
        )

    def test_uptrend_gives_positive_macd(self) -> None:
        assert macd(pd.Series(trending(200)))["macd"].iloc[-1] > 0

    def test_rejects_fast_slower_than_slow(self) -> None:
        s = pd.Series(np.arange(100, dtype="float64"))
        with pytest.raises(ValueError, match="must be shorter"):
            macd(s, fast=26, slow=12)


class TestBollingerBands:
    def test_uses_population_stdev_like_pine(self) -> None:
        s = pd.Series(100 + np.random.default_rng(5).normal(0, 2, 100).cumsum())
        bands = bollinger_bands(s, 20, 2.0)

        window = s.iloc[-20:]
        assert bands["upper"].iloc[-1] == pytest.approx(window.mean() + 2 * window.std(ddof=0))
        # And is measurably different from the sample stdev pandas defaults to.
        assert bands["upper"].iloc[-1] != pytest.approx(window.mean() + 2 * window.std(ddof=1))

    def test_percent_b_locates_price_in_the_channel(self) -> None:
        s = pd.Series(100 + np.random.default_rng(9).normal(0, 2, 100).cumsum())
        bands = bollinger_bands(s, 20)
        row = bands.iloc[-1]
        expected = (s.iloc[-1] - row["lower"]) / (row["upper"] - row["lower"])
        assert row["percent_b"] == pytest.approx(expected)

    def test_flat_series_collapses_the_bands(self) -> None:
        bands = bollinger_bands(pd.Series([50.0] * 40), 20)
        assert bands["bandwidth"].iloc[-1] == pytest.approx(0.0)


class TestVolatility:
    def test_true_range_uses_the_previous_close(self) -> None:
        df = pd.DataFrame(
            {
                "open": [10, 20],
                "high": [11, 21],
                "low": [9, 19],
                "close": [10, 20],
                "volume": [1, 1],
            }
        )
        # Bar 2 gaps up: TR is high(21) - prev_close(10) = 11, not high - low = 2.
        assert true_range(df).iloc[-1] == pytest.approx(11.0)

    def test_atr_of_constant_range_equals_that_range(self) -> None:
        closes = np.full(60, 100.0)
        df = make_ohlcv(closes, spread=1.0)  # every bar spans exactly 2.0
        assert atr(df, 14).iloc[-1] == pytest.approx(2.0)


class TestVwap:
    def test_resets_at_the_session_boundary(self) -> None:
        index = pd.to_datetime(
            [
                "2026-01-01 09:15",
                "2026-01-01 10:15",
                "2026-01-01 11:15",
                "2026-01-02 09:15",
                "2026-01-02 10:15",
                "2026-01-02 11:15",
            ]
        )
        prices = [10.0, 10.0, 10.0, 20.0, 20.0, 20.0]
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [100.0] * 6,
            },
            index=index,
        )

        session = vwap(df, anchor="session")
        cumulative = vwap(df, anchor="cumulative")

        # The first bar of day two knows nothing about day one.
        assert session.iloc[3] == pytest.approx(20.0)
        # Whereas the cumulative anchor drags day one's volume along:
        # (3 bars at 10 + 1 bar at 20) / 4 = 12.5
        assert cumulative.iloc[3] == pytest.approx(12.5)

    def test_session_anchor_requires_a_datetime_index(self) -> None:
        df = make_ohlcv([10.0] * 5).reset_index(drop=True)
        with pytest.raises(IndicatorError, match="DatetimeIndex"):
            vwap(df, anchor="session")

    def test_rejects_unknown_anchor(self) -> None:
        with pytest.raises(IndicatorError, match="anchor must be"):
            vwap(make_ohlcv([10.0] * 5), anchor="weekly")


class TestVolume:
    def test_relative_volume_is_a_multiple_of_the_average(self) -> None:
        volumes = np.r_[np.full(20, 1000.0), [3000.0]]
        df = make_ohlcv(np.full(21, 100.0), volumes)

        # The 20-bar window includes the spike bar itself (as TradingView's does),
        # so the average is (19*1000 + 3000)/20 = 1100, not 1000.
        assert relative_volume(df, 20).iloc[-1] == pytest.approx(3000 / 1100)

    def test_relative_volume_of_a_flat_tape_is_one(self) -> None:
        df = make_ohlcv(np.full(30, 100.0), np.full(30, 1000.0))
        assert relative_volume(df, 20).iloc[-1] == pytest.approx(1.0)

    def test_obv_adds_on_up_bars_and_subtracts_on_down_bars(self) -> None:
        df = make_ohlcv([10.0, 11.0, 10.0], [100.0, 200.0, 300.0])
        # 0 (first bar, no direction) + 200 (up) - 300 (down)
        assert obv(df).iloc[-1] == pytest.approx(-100.0)


class TestSupertrend:
    def test_direction_is_up_in_an_uptrend(self) -> None:
        df = make_ohlcv(trending(120, drift=1.0))
        assert supertrend(df, 10, 3.0)["direction"].iloc[-1] == 1.0

    def test_direction_is_down_in_a_downtrend(self) -> None:
        df = make_ohlcv(trending(120, start=200.0, drift=-1.0))
        assert supertrend(df, 10, 3.0)["direction"].iloc[-1] == -1.0


class TestRoc:
    def test_percent_change_over_the_window(self) -> None:
        s = pd.Series([100.0] * 9 + [110.0])
        assert roc(s, 9).iloc[-1] == pytest.approx(10.0)


class TestValidation:
    def test_missing_ohlcv_column_is_named_in_the_error(self) -> None:
        df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})
        with pytest.raises(IndicatorError, match="volume"):
            true_range(df)
