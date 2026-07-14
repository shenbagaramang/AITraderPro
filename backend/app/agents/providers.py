"""Data ports for the agents that need the outside world.

These are Protocols, not implementations. The technical, risk and portfolio
agents need nothing but numbers you already have, so they are complete. The
fundamental and news agents need data this repo does not yet fetch, and pretending
otherwise — by shipping an agent that returns plausible-looking made-up PE ratios
— would be worse than useless, because it would look like it worked.

So the *scoring* is real, tested and complete. The *fetching* is a port with no
adapter, and it raises loudly rather than returning a comfortable default.

Adapters land in Phase 2/3:
  FundamentalsProvider -> screener.in / Tijori / NSE filings scrape
  NewsProvider         -> RSS + NSE announcements + an LLM for commentary
  MarketContextProvider-> RBI calendar, crude, USD/INR, global indices
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.agents.fundamental_agent import FundamentalSnapshot
from app.agents.news_agent import MarketContext, NewsItem


class ProviderNotConfiguredError(RuntimeError):
    """Raised when an agent is asked for data no adapter has been wired up for."""


@runtime_checkable
class FundamentalsProvider(Protocol):
    def snapshot(self, symbol: str) -> FundamentalSnapshot: ...


@runtime_checkable
class NewsProvider(Protocol):
    def recent(self, symbol: str, since: date) -> list[NewsItem]: ...


@runtime_checkable
class MarketContextProvider(Protocol):
    def current(self) -> MarketContext: ...


class UnconfiguredFundamentals:
    """The default. Fails loudly instead of inventing a balance sheet."""

    def snapshot(self, symbol: str) -> FundamentalSnapshot:
        raise ProviderNotConfiguredError(
            f"no fundamentals adapter is wired up, so {symbol} cannot be analysed. "
            "Pass a FundamentalsProvider to FundamentalAgent(provider=...), or call "
            "agent.score(snapshot) directly with data you already hold."
        )


class UnconfiguredNews:
    def recent(self, symbol: str, since: date) -> list[NewsItem]:
        raise ProviderNotConfiguredError(
            f"no news adapter is wired up, so {symbol} has no feed. "
            "Pass a NewsProvider to NewsAgent(provider=...), or call "
            "agent.assess(items) directly with items you already hold."
        )
