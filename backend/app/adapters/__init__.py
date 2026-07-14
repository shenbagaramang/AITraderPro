"""Provider adapters: the implementations behind the ports in agents/providers.py.

Every adapter here separates *fetching* from *mapping*. The fetch is a thin,
injectable callable; the mapping is a pure function from raw payload to domain
type. That split is what makes the adapters testable offline with recorded
payloads, and it is why a Yahoo schema change breaks a mapping test instead of
breaking silently in production.

What each adapter can and cannot supply — stated, not hidden:

  YahooFundamentalsProvider   PE, PB, ROE, D/E, growth, cash flow.
                              CANNOT supply promoter holding/pledge or FII/DII
                              — those fields stay None and coverage drops, so a
                              score from this adapter can never fire the
                              promoter red flags. ROCE is approximated (see the
                              mapping docstring).
  GoogleNewsRssProvider       Headlines per symbol via Google News RSS. No API
                              key, no scraping of paywalled bodies — headlines
                              only, which is what the classifier scores.
  LexiconSentimentClassifier  Deterministic keyword scoring. Crude but
                              transparent and free. Swap in the Claude
                              classifier for nuance.
  ClaudeSentimentClassifier   LLM classification via the Anthropic API.
                              Requires ANTHROPIC_API_KEY.
  YahooMarketContextProvider  Nifty, India VIX, USD/INR, Brent — the full
                              MarketContext, one fetch per scan.
"""

from app.adapters.rss_news import GoogleNewsRssProvider
from app.adapters.sentiment import (
    Classified,
    ClaudeSentimentClassifier,
    LexiconSentimentClassifier,
)
from app.adapters.yahoo import (
    YahooFundamentalsProvider,
    YahooMarketContextProvider,
    map_info_to_snapshot,
)

__all__ = [
    "Classified",
    "ClaudeSentimentClassifier",
    "GoogleNewsRssProvider",
    "LexiconSentimentClassifier",
    "YahooFundamentalsProvider",
    "YahooMarketContextProvider",
    "map_info_to_snapshot",
]
