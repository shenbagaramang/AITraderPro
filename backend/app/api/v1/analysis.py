"""Chart analysis and Pine generation endpoints — the surface the MCP server calls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.agents import TechnicalAgent
from app.core.deps import CurrentUser
from app.engine import DecisionEngine, MarketData
from app.pine import PineGenerator
from app.services.candle_service import frame_from_payload

router = APIRouter()

generator = PineGenerator()


class CandleRow(BaseModel):
    timestamp: str | None = None
    open: float
    high: float
    low: float
    close: float
    volume: float


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    candles: list[CandleRow] = Field(..., min_length=30, max_length=5000)


class AnalyzeResponse(BaseModel):
    symbol: str
    bias: str
    score: float
    conviction: str
    agreement: float
    regime: str
    action: str
    confidence: float
    rationale: list[str]
    conflicts: list[str]
    signals: list[dict[str, Any]]


class DecideRequest(AnalyzeRequest):
    equity: float = Field(..., gt=0)
    lot_size: int = Field(1, ge=1)


class DecideResponse(BaseModel):
    symbol: str
    outcome: str
    action: str
    confidence: float
    quantity: int
    entry: float | None
    stop_loss: float | None
    target: float | None
    reasons: list[str]
    vetoes: list[str]
    agent_votes: dict[str, str]


class PineRequest(BaseModel):
    scanner: str
    params: dict[str, Any] = Field(default_factory=dict)


class PineResponse(BaseModel):
    name: str
    scanner: str
    params: dict[str, Any]
    source: str
    alerts: list[str]
    instructions: str = (
        "Open TradingView -> Pine Editor -> paste -> Add to chart. "
        "Create alerts from the listed alertconditions; point them at "
        "/api/v1/webhooks/tradingview with your webhook secret in the JSON body."
    )


@router.post(
    "/technical",
    response_model=AnalyzeResponse,
    summary="Run all scanners + the technical agent on supplied candles",
)
async def analyze(payload: AnalyzeRequest, _: CurrentUser) -> AnalyzeResponse:
    df = frame_from_payload([c.model_dump() for c in payload.candles])
    symbol = payload.symbol.upper()

    view = await run_in_threadpool(TechnicalAgent().analyze, symbol, df)
    rec = view.to_recommendation()

    return AnalyzeResponse(
        symbol=symbol,
        bias=view.bias.value,
        score=view.score,
        conviction=view.conviction.value,
        agreement=view.agreement,
        regime=view.regime,
        action=rec.action.value,
        confidence=rec.confidence,
        rationale=view.rationale,
        conflicts=view.conflicts,
        signals=[
            {
                "scanner": s.scanner,
                "direction": s.direction.value,
                "strength": s.strength,
                "reason": s.reason,
                "metrics": s.metrics,
            }
            for s in view.signals
        ],
    )


@router.post(
    "/decide",
    response_model=DecideResponse,
    summary="Run the full decision engine on supplied candles",
)
async def decide(payload: DecideRequest, _: CurrentUser) -> DecideResponse:
    df = frame_from_payload([c.model_dump() for c in payload.candles])
    symbol = payload.symbol.upper()

    decision = await run_in_threadpool(
        lambda: DecisionEngine().decide(
            MarketData(symbol, df), equity=payload.equity, lot_size=payload.lot_size
        )
    )

    return DecideResponse(
        symbol=symbol,
        outcome=decision.outcome.value,
        action=decision.action.value,
        confidence=decision.confidence,
        quantity=decision.quantity,
        entry=decision.entry,
        stop_loss=decision.stop_loss,
        target=decision.target,
        reasons=decision.reasons,
        vetoes=decision.vetoes,
        agent_votes=decision.agent_votes,
    )


@router.get("/pine/templates", summary="List available Pine templates")
async def pine_templates(_: CurrentUser) -> dict[str, list[str]]:
    return {"templates": PineGenerator.available()}


@router.post("/pine", response_model=PineResponse, summary="Generate a Pine v6 script")
async def pine(payload: PineRequest, _: CurrentUser) -> PineResponse:
    script = generator.generate(payload.scanner, **payload.params)
    return PineResponse(
        name=script.name,
        scanner=script.scanner,
        params=script.params,
        source=script.source,
        alerts=script.alerts,
    )
