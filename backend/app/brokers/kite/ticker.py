"""KiteTicker WebSocket -> Redis fan-out.

The design point: the WebSocket connection is a *singleton per process*, and
consumers (the dashboard, the scanner, an alert worker) subscribe to Redis, not
to Kite. Kite permits a limited number of concurrent WebSocket connections, and
having each dashboard tab open its own is a fast route to being throttled.

Ticks are published to ``ticks:{SYMBOL}`` and the latest is cached at
``quote:{SYMBOL}`` so a page load does not have to wait for the next tick.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.brokers.base import BrokerError
from app.core.logging import get_logger

logger = get_logger(__name__)

TICK_CHANNEL = "ticks:{symbol}"
QUOTE_KEY = "quote:{symbol}"
QUOTE_TTL_SECONDS = 300

# Kite caps a single connection at 3,000 instruments.
MAX_INSTRUMENTS = 3000


class KiteTickerBridge:
    """Owns the WebSocket. Publishes to Redis. Nothing else talks to KiteTicker."""

    def __init__(
        self,
        api_key: str,
        access_token: str,
        publish: Callable[[str, str], Any],
        ticker: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self.publish = publish
        self._token_to_symbol: dict[int, str] = {}
        self._ticker = ticker

    def _build(self) -> Any:
        if self._ticker is not None:
            return self._ticker
        try:
            from kiteconnect import KiteTicker
        except ImportError as exc:  # pragma: no cover
            raise BrokerError(
                "the `kiteconnect` package is not installed; "
                "run `pip install kiteconnect` for live ticks"
            ) from exc
        return KiteTicker(self.api_key, self.access_token)

    def subscribe(self, instruments: dict[int, str]) -> None:
        """``instruments`` maps Kite instrument tokens to trading symbols."""
        if len(instruments) > MAX_INSTRUMENTS:
            raise BrokerError(
                f"{len(instruments)} instruments requested, but a single Kite "
                f"WebSocket caps out at {MAX_INSTRUMENTS}"
            )
        self._token_to_symbol = dict(instruments)

    def start(self, threaded: bool = True) -> None:
        ticker = self._build()
        tokens = list(self._token_to_symbol)

        def on_connect(ws: Any, _response: Any) -> None:
            logger.info("KiteTicker connected, subscribing to %d instruments", len(tokens))
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)

        def on_ticks(_ws: Any, ticks: list[dict[str, Any]]) -> None:
            for tick in ticks:
                self._handle(tick)

        def on_close(_ws: Any, code: Any, reason: Any) -> None:
            logger.warning("KiteTicker closed: %s %s", code, reason)

        def on_error(_ws: Any, code: Any, reason: Any) -> None:
            logger.error("KiteTicker error: %s %s", code, reason)

        ticker.on_connect = on_connect
        ticker.on_ticks = on_ticks
        ticker.on_close = on_close
        ticker.on_error = on_error

        ticker.connect(threaded=threaded)
        self._ticker = ticker

    def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.close()
            logger.info("KiteTicker stopped")

    def _handle(self, tick: dict[str, Any]) -> None:
        token = tick.get("instrument_token")
        symbol = self._token_to_symbol.get(int(token)) if token else None
        if symbol is None:
            return

        payload = {
            "symbol": symbol,
            "last_price": tick.get("last_price"),
            "volume": tick.get("volume_traded", tick.get("volume", 0)),
            "timestamp": str(tick.get("exchange_timestamp") or ""),
        }
        self.publish(symbol, str(payload))
