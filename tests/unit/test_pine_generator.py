"""Pine generation. The tests assert the *contracts*: version pragma, no-repaint
gating, parameter reconciliation with the scanners, and alert wiring."""

from __future__ import annotations

import pytest

from app.pine import PineGenerator

GEN = PineGenerator()


class TestContracts:
    @pytest.mark.parametrize("scanner", PineGenerator.available())
    def test_every_template_is_pine_v6(self, scanner: str) -> None:
        script = GEN.generate(scanner)
        assert script.source.startswith("//@version=6")

    @pytest.mark.parametrize("scanner", PineGenerator.available())
    def test_every_signal_is_gated_on_confirmed_bars(self, scanner: str) -> None:
        """No repaint: an alert must not fire intra-bar and then un-fire."""
        assert "barstate.isconfirmed" in GEN.generate(scanner).source

    @pytest.mark.parametrize("scanner", PineGenerator.available())
    def test_every_template_declares_alertconditions(self, scanner: str) -> None:
        script = GEN.generate(scanner)
        assert script.alerts
        for alert in script.alerts:
            assert f'"{alert}"' in script.source

    def test_unknown_template_lists_the_known_ones(self) -> None:
        with pytest.raises(KeyError, match="available"):
            GEN.generate("astrology")


class TestParameterReconciliation:
    def test_ema_defaults_come_from_the_scanner_not_a_copy(self) -> None:
        """The generator imports the scanner's defaults; they cannot drift."""
        from app.scanners.ema_scanner import EmaScanner

        script = GEN.generate("ema")
        defaults = EmaScanner.defaults()
        assert script.params["fast"] == defaults["fast"]
        assert f'input.int({defaults["fast"]}, "Fast EMA"' in script.source.replace("  ", " ")

    def test_overrides_reach_both_params_and_source(self) -> None:
        script = GEN.generate("ema", fast=5, slow=13)
        assert script.params["fast"] == 5
        assert (
            'input.int(5,  "Fast EMA"' in script.source
            or 'input.int(5, "Fast EMA"' in script.source
        )
        assert "EMA Cross (5/13/" in script.name

    def test_breakout_range_excludes_the_current_bar(self) -> None:
        """Same rule as the scanner: the breaking bar cannot define its own level."""
        source = GEN.generate("breakout").source
        assert "ta.highest(high[1]" in source
        assert "ta.lowest(low[1]" in source

    def test_momentum_does_not_alert_on_overbought_alone(self) -> None:
        """Matches the scanner's philosophy: RSI > 70 is not a short."""
        script = GEN.generate("momentum")
        assert "MACD Cross Up" in script.alerts
        assert not any("overbought" in a.lower() for a in script.alerts)

    def test_placeholders_survive_the_fstring(self) -> None:
        """{{ticker}} must reach TradingView intact, not be eaten by Python."""
        source = GEN.generate("ema").source
        assert "{{ticker}}" in source
