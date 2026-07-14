"""Technical agent tests: interpretation, not computation."""

from __future__ import annotations

import pytest

from app.agents import Conviction, TechnicalAgent
from app.scanners.base import Signal, SignalDirection
from tests.fixtures import make_ohlcv, trending


def bull(scanner: str, strength: float = 0.8) -> Signal:
    return Signal(scanner, "X", SignalDirection.BULLISH, strength, f"{scanner} bullish")


def bear(scanner: str, strength: float = 0.8) -> Signal:
    return Signal(scanner, "X", SignalDirection.BEARISH, strength, f"{scanner} bearish")


def flat_signal(scanner: str) -> Signal:
    return Signal(scanner, "X", SignalDirection.NEUTRAL, 0.0, f"{scanner} neutral")


class TestInterpretation:
    def test_unanimous_bullish_gives_high_conviction(self) -> None:
        view = TechnicalAgent().interpret(
            "X", [bull(n, 0.9) for n in ("ema", "breakout", "momentum", "volume")]
        )
        assert view.bias is SignalDirection.BULLISH
        assert view.conviction is Conviction.HIGH
        assert view.agreement == pytest.approx(1.0)
        assert view.conflicts == []
        assert view.is_actionable

    def test_all_neutral_gives_no_edge(self) -> None:
        view = TechnicalAgent().interpret("X", [flat_signal(n) for n in ("ema", "vwap")])
        assert view.bias is SignalDirection.NEUTRAL
        assert view.score == 0.0
        assert not view.is_actionable

    def test_no_signals_at_all(self) -> None:
        view = TechnicalAgent().interpret("X", [])
        assert view.bias is SignalDirection.NEUTRAL
        assert "every scanner returned neutral" in view.rationale

    def test_exact_tie_admits_there_is_no_edge(self) -> None:
        """A dead heat must not be broken arbitrarily."""
        view = TechnicalAgent().interpret("X", [bull("ema", 0.8), bear("ema", 0.8)])
        assert view.bias is SignalDirection.NEUTRAL
        assert view.score == 0.0
        assert len(view.conflicts) == 2

    def test_dissenters_are_named_not_hidden(self) -> None:
        view = TechnicalAgent().interpret(
            "X", [bull("ema"), bull("breakout"), bull("momentum"), bear("volume")]
        )
        assert view.bias is SignalDirection.BULLISH
        assert view.agreement == pytest.approx(0.75)
        assert len(view.conflicts) == 1
        assert "volume" in view.conflicts[0]

    def test_a_split_vote_cannot_reach_high_conviction(self) -> None:
        """Agreement gates conviction, however large the raw score."""
        split = TechnicalAgent().interpret(
            "X",
            [
                bull("breakout", 1.0),
                bull("momentum", 1.0),
                bear("ema", 0.9),
                bear("volume", 0.9),
            ],
        )
        sweep = TechnicalAgent().interpret(
            "X",
            [
                bull("breakout", 1.0),
                bull("momentum", 1.0),
                bull("ema", 0.9),
                bull("volume", 0.9),
            ],
        )
        assert sweep.conviction is Conviction.HIGH
        assert split.conviction is not Conviction.HIGH
        assert split.agreement < sweep.agreement

    def test_weights_shift_the_verdict(self) -> None:
        signals = [bull("vwap", 0.9), bear("breakout", 0.9)]

        default = TechnicalAgent().interpret("X", signals)
        assert default.bias is SignalDirection.BEARISH  # breakout outweighs vwap

        reweighted = TechnicalAgent(weights={"vwap": 5.0}).interpret("X", signals)
        assert reweighted.bias is SignalDirection.BULLISH

    def test_score_is_bounded_by_one(self) -> None:
        view = TechnicalAgent().interpret("X", [bull(n, 1.0) for n in ("ema", "breakout")])
        assert view.score == pytest.approx(1.0)

    def test_neutral_signals_do_not_dilute_the_score(self) -> None:
        """Only actionable signals vote; abstentions are not votes against."""
        with_abstentions = TechnicalAgent().interpret(
            "X", [bull("ema", 1.0), flat_signal("vwap"), flat_signal("volume")]
        )
        without = TechnicalAgent().interpret("X", [bull("ema", 1.0)])
        assert with_abstentions.score == pytest.approx(without.score)

    def test_unknown_scanner_gets_a_default_weight(self) -> None:
        view = TechnicalAgent().interpret("X", [bull("some_future_scanner", 1.0)])
        assert view.bias is SignalDirection.BULLISH


class TestEndToEnd:
    def test_analyze_runs_the_full_stack_on_a_real_trend(self) -> None:
        agent = TechnicalAgent()
        view = agent.analyze("TCS", make_ohlcv(trending(200, drift=1.0), intraday=True))

        assert view.bias is SignalDirection.BULLISH
        assert len(view.signals) == 8
        assert view.rationale
        assert "TCS" in view.summary()

    def test_summary_is_human_readable(self) -> None:
        view = TechnicalAgent().interpret("INFY", [bull("ema"), bull("breakout")])
        summary = view.summary()
        assert "INFY" in summary
        assert "bullish" in summary
        assert "agreement" in summary
