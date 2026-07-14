"""Pine Script generation.

The generator's contract: a script generated for a scanner uses **the same
parameters and the same smoothing conventions** as that scanner, so what fires
here is what you see on the TradingView chart. That reconciliation is the entire
reason to generate Pine rather than hand-write it.

All output is Pine v6, and every signal is gated on ``barstate.isconfirmed`` —
an alert that fires intra-bar and then un-fires when the bar closes differently
is a repaint, and repainting alerts are how backtests lie.
"""

from app.pine.generator import PineGenerator, PineScript

__all__ = ["PineGenerator", "PineScript"]
