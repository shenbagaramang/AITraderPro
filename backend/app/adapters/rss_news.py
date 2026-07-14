"""Google News RSS -> NewsItem list.

Why Google News RSS: no API key, no scraping of paywalled article bodies, and it
aggregates ET / Moneycontrol / Business Standard / Livemint in one query. The
cost is that we get *headlines*, not full text — which is fine, because the
classifier scores headlines and the NewsAgent already treats one article as an
anecdote.

The feed is fetched raw and parsed with stdlib ElementTree: RSS 2.0 is simple
enough that pulling in feedparser buys nothing.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import quote

from app.adapters.cache import TTLCache
from app.adapters.sentiment import Classified, LexiconSentimentClassifier
from app.agents.news_agent import NewsItem
from app.core.logging import get_logger

logger = get_logger(__name__)

NEWS_TTL = 600  # ten minutes; headlines do not move faster than that
_cache = TTLCache(NEWS_TTL)

GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?q={query}+stock+NSE&hl=en-IN&gl=IN&ceid=IN:en"
)

MAX_ITEMS = 25


class SentimentClassifier(Protocol):
    def classify_many(self, headlines: list[str]) -> list[Classified]: ...


def _default_fetcher(url: str) -> str:  # pragma: no cover - network
    import httpx

    resp = httpx.get(
        url,
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": "AITraderPro/1.0"},
    )
    resp.raise_for_status()
    return resp.text


def parse_rss(xml_text: str) -> list[dict[str, str]]:
    """Pure parse: RSS 2.0 -> [{title, link, published, source}]. A malformed
    item is skipped, not fatal — one bad entry must not lose the feed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"not parseable as RSS: {exc}") from exc

    out: list[dict[str, str]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "link": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
                "source": (item.findtext("source") or "").strip() or "google-news",
            }
        )
    return out


def _parse_when(pub_date: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(pub_date)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


class GoogleNewsRssProvider:
    """Implements the NewsProvider port."""

    def __init__(
        self,
        classifier: SentimentClassifier | None = None,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.classifier = classifier or LexiconSentimentClassifier()
        self.fetcher = fetcher or _default_fetcher

    def recent(self, symbol: str, since: date) -> list[NewsItem]:
        symbol = symbol.upper()
        url = GOOGLE_NEWS_URL.format(query=quote(symbol))

        xml_text = _cache.get_or_fetch(url, lambda: self.fetcher(url))
        raw = parse_rss(xml_text)[:MAX_ITEMS]

        # Google's relevance ranking is keyword-based; a query for TCS also
        # returns "TCS of the leaked exam papers". Cheap precision filter: the
        # symbol must actually appear in the headline.
        raw = [r for r in raw if symbol.lower() in r["title"].lower()]
        if not raw:
            return []

        classified = self.classifier.classify_many([r["title"] for r in raw])

        items: list[NewsItem] = []
        for row, cls in zip(raw, classified, strict=True):
            published = _parse_when(row["published"])
            if published.date() < since:
                continue
            items.append(
                NewsItem(
                    symbol=symbol,
                    headline=row["title"],
                    published_at=published,
                    sentiment=cls.sentiment,
                    category=cls.category,
                    confidence=cls.confidence,
                    source=row["source"],
                    url=row["link"] or None,
                )
            )

        logger.info("news: %d items for %s after filtering", len(items), symbol)
        return items
