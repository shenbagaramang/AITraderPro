"""Fundamental / news / context endpoints, backed by the live adapters.

These hit external services (Yahoo, Google News), so results are cached by the
adapters and failures surface as clean errors rather than hanging requests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.adapters import (
    GoogleNewsRssProvider,
    YahooFundamentalsProvider,
    YahooMarketContextProvider,
)
from app.agents import FundamentalAgent, MarketContextAgent, NewsAgent
from app.core.deps import CurrentUser
from app.core.exceptions import AppError

router = APIRouter()

# Module-level singletons: their caches are the whole point.
_fundamental_agent = FundamentalAgent(provider=YahooFundamentalsProvider())
_news_agent = NewsAgent(provider=GoogleNewsRssProvider())
_context_provider = YahooMarketContextProvider()
_context_agent = MarketContextAgent()


class FundamentalResponse(BaseModel):
    symbol: str
    composite: float
    coverage: float
    components: dict[str, float]
    strengths: list[str]
    concerns: list[str]
    red_flags: list[str]
    action: str
    conviction: str
    data_caveats: list[str]


class NewsResponse(BaseModel):
    symbol: str
    score: float
    item_count: int
    dominant: str
    action: str
    conviction: str
    headlines: list[str]
    concerns: list[str]
    items: list[dict[str, Any]]


class ContextResponse(BaseModel):
    as_of: datetime
    nifty_change_pct: float | None
    india_vix: float | None
    usd_inr: float | None
    crude_usd: float | None
    crude_change_pct: float | None
    risk_off: bool
    notes: list[str]


@router.get(
    "/fundamental/{symbol}",
    response_model=FundamentalResponse,
    summary="Score a symbol's fundamentals (Yahoo-backed)",
)
async def fundamental(symbol: str, _: CurrentUser) -> FundamentalResponse:
    try:
        score = await run_in_threadpool(_fundamental_agent.analyze, symbol.upper())
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"fundamentals fetch failed: {exc}", code="provider_error") from exc

    rec = score.to_recommendation()
    return FundamentalResponse(
        symbol=score.symbol,
        composite=score.composite,
        coverage=score.coverage,
        components=score.components,
        strengths=score.strengths,
        concerns=score.concerns,
        red_flags=score.red_flags,
        action=rec.action.value,
        conviction=rec.conviction.value,
        data_caveats=[
            "Yahoo cannot supply promoter holding/pledge or FII/DII, so the "
            "promoter red flags can never fire from this data source.",
            "ROCE is proxied by return-on-assets and understates ROCE for "
            "leveraged companies.",
        ],
    )


@router.get(
    "/news/{symbol}",
    response_model=NewsResponse,
    summary="Aggregate recent news sentiment (Google News RSS)",
)
async def news(symbol: str, _: CurrentUser, days: int = Query(7, ge=1, le=30)) -> NewsResponse:
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    try:
        items = await run_in_threadpool(_news_agent.provider.recent, symbol.upper(), since)
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"news fetch failed: {exc}", code="provider_error") from exc

    assessment = _news_agent.assess(symbol.upper(), items)
    rec = assessment.to_recommendation()
    return NewsResponse(
        symbol=assessment.symbol,
        score=assessment.score,
        item_count=assessment.item_count,
        dominant=assessment.dominant.value,
        action=rec.action.value,
        conviction=rec.conviction.value,
        headlines=assessment.headlines,
        concerns=assessment.concerns,
        items=[
            {
                "headline": i.headline,
                "sentiment": i.sentiment.value,
                "category": i.category.value,
                "confidence": i.confidence,
                "published_at": i.published_at.isoformat(),
                "source": i.source,
                "url": i.url,
            }
            for i in items
        ],
    )


@router.get(
    "/context",
    response_model=ContextResponse,
    summary="Market backdrop: Nifty, VIX, USD/INR, crude (Yahoo-backed)",
)
async def context(_: CurrentUser) -> ContextResponse:
    try:
        ctx = await run_in_threadpool(_context_provider.current)
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"context fetch failed: {exc}", code="provider_error") from exc

    return ContextResponse(
        as_of=ctx.as_of,
        nifty_change_pct=ctx.nifty_change_pct,
        india_vix=ctx.india_vix,
        usd_inr=ctx.usd_inr,
        crude_usd=ctx.crude_usd,
        crude_change_pct=ctx.crude_change_pct,
        risk_off=ctx.risk_off,
        notes=_context_agent.assess(ctx),
    )
