"""Yahoo Finance adapters: fundamentals and market context.

The fetcher is injectable everywhere. In production it is yfinance; in tests it
is a dict. The mappings are pure functions and carry the actual knowledge.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.adapters.cache import TTLCache
from app.agents.fundamental_agent import FundamentalSnapshot
from app.agents.news_agent import MarketContext, Sentiment
from app.core.logging import get_logger

logger = get_logger(__name__)

FUNDAMENTALS_TTL = 6 * 3600  # quarterly data; six hours is generous
CONTEXT_TTL = 300  # macro backdrop; five minutes

_fundamentals_cache = TTLCache(FUNDAMENTALS_TTL)
_context_cache = TTLCache(CONTEXT_TTL)

# NSE symbols map to Yahoo as SYMBOL.NS (BSE would be .BO).
YAHOO_SUFFIX = ".NS"

CONTEXT_TICKERS = {
    "nifty": "^NSEI",
    "vix": "^INDIAVIX",
    "usd_inr": "USDINR=X",
    "crude": "BZ=F",  # Brent, the benchmark that matters for India
}


def _default_info_fetcher(ticker: str) -> dict[str, Any]:  # pragma: no cover
    """Production fetcher. Imported lazily so yfinance is not a test dependency."""
    try:
        import yfinance
    except ImportError as exc:
        raise RuntimeError(
            "yfinance is not installed; run `pip install yfinance` to use the Yahoo adapters"
        ) from exc
    return yfinance.Ticker(ticker).info or {}


def _pct(value: Any) -> float | None:
    """Yahoo returns ratios as fractions (0.18 for 18%); our snapshot wants %."""
    if value is None:
        return None
    try:
        return float(value) * 100.0
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_info_to_snapshot(symbol: str, info: dict[str, Any]) -> FundamentalSnapshot:
    """Pure mapping: yfinance ``info`` dict -> FundamentalSnapshot.

    Two mappings need their caveats stated:

    - **ROCE is approximated.** Yahoo has no ROCE field; ``returnOnAssets`` is
      the closest available proxy and consistently *understates* ROCE for
      leveraged companies (assets > capital employed). It is mapped anyway
      because a conservative proxy beats a None, but a company scored on this
      field will look slightly worse on quality than screener.in would show.
    - **debtToEquity arrives as a percentage** (e.g. 41.2 meaning 0.412), unlike
      the fraction convention Yahoo uses elsewhere. Divided by 100 here; getting
      this wrong makes every company look catastrophically leveraged and fires
      the D/E red flag on the entire index.

    Promoter holding, pledge and FII/DII are structurally unavailable from
    Yahoo and stay None — coverage drops accordingly, and the promoter red
    flags can never fire from this adapter. ``heldPercentInsiders`` is NOT
    mapped to promoter_holding: insiders and promoters are different concepts,
    and a wrong red flag is worse than a missing field.
    """
    debt_to_equity = _num(info.get("debtToEquity"))
    if debt_to_equity is not None:
        debt_to_equity /= 100.0

    return FundamentalSnapshot(
        symbol=symbol,
        pe=_num(info.get("trailingPE")),
        pb=_num(info.get("priceToBook")),
        industry_pe=None,  # not exposed by Yahoo
        roce=_pct(info.get("returnOnAssets")),  # proxy — see docstring
        roe=_pct(info.get("returnOnEquity")),
        debt_to_equity=debt_to_equity,
        interest_coverage=None,  # not exposed by Yahoo
        operating_cash_flow=_num(info.get("operatingCashflow")),
        net_profit=_num(info.get("netIncomeToCommon")),
        revenue_growth_yoy=_pct(info.get("revenueGrowth")),
        profit_growth_yoy=_pct(info.get("earningsGrowth")),
        promoter_holding=None,  # structurally unavailable
        promoter_pledge=None,
        fii_holding=None,
        dii_holding=None,
        promoter_holding_change=None,
    )


class YahooFundamentalsProvider:
    """Implements the FundamentalsProvider port."""

    def __init__(self, fetcher: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.fetcher = fetcher or _default_info_fetcher

    def snapshot(self, symbol: str) -> FundamentalSnapshot:
        ticker = f"{symbol.upper()}{YAHOO_SUFFIX}"
        info = _fundamentals_cache.get_or_fetch(ticker, lambda: self.fetcher(ticker))
        if not info or (info.get("trailingPE") is None and info.get("marketCap") is None):
            logger.warning("Yahoo returned an empty info payload for %s", ticker)
        return map_info_to_snapshot(symbol.upper(), info)


def map_quotes_to_context(quotes: dict[str, dict[str, Any]]) -> MarketContext:
    """Pure mapping: {name: {price, change_pct}} -> MarketContext."""

    def price(name: str) -> float | None:
        return _num(quotes.get(name, {}).get("price"))

    def change(name: str) -> float | None:
        return _num(quotes.get(name, {}).get("change_pct"))

    nifty_change = change("nifty")
    global_cues = Sentiment.NEUTRAL
    if nifty_change is not None:
        if nifty_change <= -1.0:
            global_cues = Sentiment.NEGATIVE
        elif nifty_change >= 1.0:
            global_cues = Sentiment.POSITIVE

    return MarketContext(
        as_of=datetime.now(UTC),
        nifty_change_pct=nifty_change,
        india_vix=price("vix"),
        usd_inr=price("usd_inr"),
        usd_inr_change_pct=change("usd_inr"),
        crude_usd=price("crude"),
        crude_change_pct=change("crude"),
        repo_rate=None,  # RBI publishes this; not on Yahoo
        rbi_event_today=False,  # needs the RBI calendar — not wired yet
        global_cues=global_cues,
    )


def _default_quote_fetcher() -> dict[str, dict[str, Any]]:  # pragma: no cover
    try:
        import yfinance
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed") from exc

    out: dict[str, dict[str, Any]] = {}
    for name, ticker in CONTEXT_TICKERS.items():
        try:
            fast = yfinance.Ticker(ticker).fast_info
            last = float(fast["last_price"])
            prev = float(fast["previous_close"])
            out[name] = {
                "price": last,
                "change_pct": (last - prev) / prev * 100.0 if prev else None,
            }
        except Exception as exc:  # noqa: BLE001 - one dead ticker must not kill the context
            logger.warning("context fetch failed for %s (%s): %s", name, ticker, exc)
    return out


class YahooMarketContextProvider:
    """Implements the MarketContextProvider port. One fetch serves a whole scan."""

    def __init__(self, fetcher: Callable[[], dict[str, dict[str, Any]]] | None = None) -> None:
        self.fetcher = fetcher or _default_quote_fetcher

    def current(self) -> MarketContext:
        quotes = _context_cache.get_or_fetch("context", self.fetcher)
        return map_quotes_to_context(quotes)
