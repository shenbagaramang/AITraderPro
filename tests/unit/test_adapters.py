"""Adapter tests: recorded payloads in, domain types out. No network anywhere."""

from __future__ import annotations

from datetime import date

import pytest

from app.adapters import (
    GoogleNewsRssProvider,
    LexiconSentimentClassifier,
    YahooFundamentalsProvider,
    YahooMarketContextProvider,
    map_info_to_snapshot,
)
from app.adapters.cache import TTLCache
from app.adapters.rss_news import parse_rss
from app.adapters.sentiment import ClaudeSentimentClassifier, classify_category
from app.adapters.yahoo import map_quotes_to_context
from app.agents import FundamentalAgent, NewsAgent, NewsCategory, Sentiment

# A trimmed real-shape yfinance .info payload (RELIANCE.NS-like).
YAHOO_INFO = {
    "trailingPE": 24.5,
    "priceToBook": 2.1,
    "returnOnAssets": 0.062,  # fraction -> 6.2%
    "returnOnEquity": 0.089,  # fraction -> 8.9%
    "debtToEquity": 41.2,  # PERCENT, the trap -> 0.412
    "operatingCashflow": 1_580_000_000_000.0,
    "netIncomeToCommon": 690_000_000_000.0,
    "revenueGrowth": 0.118,
    "earningsGrowth": 0.021,
    "marketCap": 17_000_000_000_000.0,
}

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>q</title>
<item>
  <title>TCS beats estimates as Q1 profit surges 12%</title>
  <link>https://example.com/a</link>
  <pubDate>Sun, 12 Jul 2026 09:30:00 GMT</pubDate>
  <source url="https://et.example">Economic Times</source>
</item>
<item>
  <title>TCS announces dividend of Rs 28 per share</title>
  <link>https://example.com/b</link>
  <pubDate>Sat, 11 Jul 2026 14:00:00 GMT</pubDate>
</item>
<item>
  <title>SEBI probe widens into unrelated smallcap; TCS not named</title>
  <link>https://example.com/c</link>
  <pubDate>Fri, 10 Jul 2026 08:00:00 GMT</pubDate>
</item>
<item>
  <title>Mystery of the leaked exam papers deepens</title>
  <link>https://example.com/d</link>
  <pubDate>Fri, 10 Jul 2026 08:00:00 GMT</pubDate>
</item>
<item><title></title></item>
</channel></rss>"""


class TestYahooFundamentalsMapping:
    def test_fractions_become_percentages(self) -> None:
        snap = map_info_to_snapshot("RELIANCE", YAHOO_INFO)
        assert snap.roe == pytest.approx(8.9)
        assert snap.revenue_growth_yoy == pytest.approx(11.8)

    def test_debt_to_equity_percent_trap_is_handled(self) -> None:
        """Yahoo sends 41.2 meaning 0.412. Unhandled, every company on the
        index looks catastrophically leveraged and the D/E red flag fires."""
        snap = map_info_to_snapshot("RELIANCE", YAHOO_INFO)
        assert snap.debt_to_equity == pytest.approx(0.412)

        score = FundamentalAgent().score(snap)
        assert not any("debt/equity" in f for f in score.red_flags)

    def test_promoter_fields_stay_none_and_coverage_reflects_it(self) -> None:
        """Yahoo cannot know promoter data. The honest outcome: None fields,
        lower coverage — never a guess."""
        snap = map_info_to_snapshot("RELIANCE", YAHOO_INFO)
        assert snap.promoter_holding is None
        assert snap.promoter_pledge is None
        assert snap.fii_holding is None

        score = FundamentalAgent().score(snap)
        assert score.coverage < 0.8  # the missing fields cost coverage
        assert score.composite > 0.0  # but what exists still scores

    def test_missing_values_map_to_none_not_zero(self) -> None:
        snap = map_info_to_snapshot("X", {"trailingPE": None, "returnOnEquity": None})
        assert snap.pe is None
        assert snap.roe is None

    def test_garbage_values_map_to_none(self) -> None:
        snap = map_info_to_snapshot("X", {"trailingPE": "Infinity%", "debtToEquity": []})
        assert snap.pe is None
        assert snap.debt_to_equity is None

    def test_provider_uses_the_injected_fetcher_and_caches_it(self) -> None:
        calls: list[str] = []

        def fetcher(ticker: str) -> dict:
            calls.append(ticker)
            return YAHOO_INFO

        from app.adapters import yahoo

        yahoo._fundamentals_cache.clear()
        provider = YahooFundamentalsProvider(fetcher=fetcher)

        provider.snapshot("reliance")
        provider.snapshot("RELIANCE")

        assert calls == ["RELIANCE.NS"]  # second call served from cache


class TestLexiconClassifier:
    CLS = LexiconSentimentClassifier()

    def test_positive_headline(self) -> None:
        result = self.CLS.classify("TCS beats estimates as profit surges 12%")
        assert result.sentiment is Sentiment.POSITIVE
        assert result.category is NewsCategory.EARNINGS

    def test_negative_headline(self) -> None:
        result = self.CLS.classify("SEBI probe: company fined, CFO resigns")
        assert result.sentiment is Sentiment.NEGATIVE

    def test_bland_headline_is_neutral_with_low_confidence(self) -> None:
        result = self.CLS.classify("Company holds annual general meeting")
        assert result.sentiment is Sentiment.NEUTRAL
        assert result.confidence <= 0.3

    def test_confidence_is_capped_because_keywords_are_not_comprehension(self) -> None:
        loaded = "record profit surges beats wins strong robust growth rally"
        assert self.CLS.classify(loaded).confidence <= 0.7

    def test_category_rules(self) -> None:
        assert classify_category("Board approves buyback") is NewsCategory.CORPORATE_ACTION
        assert classify_category("CEO steps down") is NewsCategory.MANAGEMENT
        assert classify_category("RBI penalty imposed") is NewsCategory.REGULATORY
        assert classify_category("Wins order for new plant") is NewsCategory.ANNOUNCEMENT
        assert classify_category("Something else entirely") is NewsCategory.OTHER


class TestClaudeClassifierFallback:
    def test_no_api_key_falls_back_to_the_lexicon(self) -> None:
        classifier = ClaudeSentimentClassifier(api_key="")
        result = classifier.classify("TCS beats estimates as profit surges")
        assert result.sentiment is Sentiment.POSITIVE  # lexicon answered

    def test_api_failure_falls_back_per_batch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        classifier = ClaudeSentimentClassifier(api_key="not-a-real-key")

        def boom(headlines: list[str]) -> list:
            raise RuntimeError("api down")

        monkeypatch.setattr(classifier, "_via_api", boom)
        results = classifier.classify_many(["profit surges", "CFO resigns"])
        assert results[0].sentiment is Sentiment.POSITIVE
        assert results[1].sentiment is Sentiment.NEGATIVE


class TestRssProvider:
    def test_parse_rss_skips_malformed_items(self) -> None:
        rows = parse_rss(RSS_XML)
        assert len(rows) == 4  # the empty-title item is dropped
        assert rows[0]["source"] == "Economic Times"

    def test_garbage_xml_raises_cleanly(self) -> None:
        with pytest.raises(ValueError, match="not parseable"):
            parse_rss("this is not xml")

    def test_symbol_precision_filter(self) -> None:
        """Google returns keyword matches; 'leaked exam papers' is not TCS news."""
        provider = GoogleNewsRssProvider(fetcher=lambda url: RSS_XML)
        items = provider.recent("TCS", since=date(2026, 7, 1))

        headlines = [i.headline for i in items]
        assert len(items) == 3
        assert not any("exam papers" in h for h in headlines)

    def test_since_filter_drops_old_items(self) -> None:
        provider = GoogleNewsRssProvider(fetcher=lambda url: RSS_XML)
        items = provider.recent("TCS", since=date(2026, 7, 12))
        assert len(items) == 1
        assert "beats estimates" in items[0].headline

    def test_end_to_end_into_the_news_agent(self) -> None:
        """The full path: RSS -> classify -> NewsAgent aggregate."""
        agent = NewsAgent(provider=GoogleNewsRssProvider(fetcher=lambda url: RSS_XML))
        assessment = agent.analyze("TCS", lookback_days=3650)

        assert assessment.item_count == 3
        assert assessment.score > 0  # beat + dividend outweigh the probe
        assert assessment.dominant is Sentiment.POSITIVE

    def test_no_matching_items_returns_empty_not_error(self) -> None:
        provider = GoogleNewsRssProvider(fetcher=lambda url: RSS_XML)
        assert provider.recent("INFY", since=date(2026, 7, 1)) == []


class TestContextMapping:
    def test_quotes_map_onto_the_context(self) -> None:
        ctx = map_quotes_to_context(
            {
                "nifty": {"price": 26_400.0, "change_pct": -1.4},
                "vix": {"price": 22.5, "change_pct": 8.0},
                "usd_inr": {"price": 89.2, "change_pct": 0.6},
                "crude": {"price": 84.0, "change_pct": 6.1},
            }
        )
        assert ctx.india_vix == 22.5
        assert ctx.global_cues is Sentiment.NEGATIVE
        assert ctx.risk_off  # vix>20, nifty<-1, crude>5: three signals

    def test_missing_tickers_degrade_to_none_not_zero(self) -> None:
        ctx = map_quotes_to_context({"nifty": {"price": 26_400.0, "change_pct": 0.2}})
        assert ctx.india_vix is None
        assert ctx.crude_usd is None
        assert not ctx.risk_off

    def test_provider_caches_the_fetch(self) -> None:
        calls = []

        def fetcher() -> dict:
            calls.append(1)
            return {"nifty": {"price": 26_000.0, "change_pct": 0.1}}

        from app.adapters import yahoo

        yahoo._context_cache.clear()
        provider = YahooMarketContextProvider(fetcher=fetcher)
        provider.current()
        provider.current()
        assert len(calls) == 1


class TestTTLCache:
    def test_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.adapters.cache as cache_module

        clock = [1000.0]
        monkeypatch.setattr(cache_module.time, "monotonic", lambda: clock[0])

        cache = TTLCache(ttl_seconds=10)
        calls = []

        def fetch() -> str:
            calls.append(1)
            return "value"

        cache.get_or_fetch("k", fetch)
        clock[0] += 5
        cache.get_or_fetch("k", fetch)  # still fresh
        clock[0] += 6
        cache.get_or_fetch("k", fetch)  # expired -> refetch
        assert len(calls) == 2

    def test_eviction_keeps_the_cache_bounded(self) -> None:
        cache = TTLCache(ttl_seconds=100, max_entries=3)
        for i in range(5):
            cache.get_or_fetch(f"k{i}", lambda i=i: i)
        assert len(cache._store) <= 3
