"""Agent layer.

Agents *interpret*. They do not compute indicators and they do not apply scan
criteria — they consume the output of the layer below and turn it into a view a
human (or the Decision Engine) can act on.

    indicators/   pure math          ema(close, 9) -> Series
    scanners/     criteria on math   "EMA9 crossed EMA21 on 2.3x volume" -> Signal
    agents/       interpretation     "buy, moderate, but volume disagrees" -> Recommendation
    engine/       decision           which trade, how large -> Order      (next)

Each layer imports only from the layer below it.

Status of the five agents:

  technical   COMPLETE — 8 scanners, ADX regime gate, Buy/Sell/Hold + confidence
  risk        COMPLETE — sizing, stops, R:R, correlation, and the veto
  portfolio   COMPLETE — CAGR, drawdown, Sharpe, Sortino, win ratio, concentration
  fundamental SCORING COMPLETE, DATA PORT UNIMPLEMENTED
  news        SCORING COMPLETE, DATA PORT UNIMPLEMENTED

The last two are honest about it: they raise ``ProviderNotConfigured`` rather
than returning invented numbers. See ``providers.py``.
"""

from app.agents.base import Action, Conviction, Recommendation
from app.agents.fundamental_agent import (
    FundamentalAgent,
    FundamentalScore,
    FundamentalSnapshot,
)
from app.agents.news_agent import (
    MarketContext,
    MarketContextAgent,
    NewsAgent,
    NewsAssessment,
    NewsCategory,
    NewsItem,
    Sentiment,
)
from app.agents.portfolio_agent import Holding, PortfolioAgent, PortfolioReport
from app.agents.risk_agent import Position, RiskAgent, RiskAssessment, RiskLimits
from app.agents.technical_agent import TechnicalAgent, TechnicalView

__all__ = [
    "Action",
    "Conviction",
    "FundamentalAgent",
    "FundamentalScore",
    "FundamentalSnapshot",
    "Holding",
    "MarketContext",
    "MarketContextAgent",
    "NewsAgent",
    "NewsAssessment",
    "NewsCategory",
    "NewsItem",
    "PortfolioAgent",
    "PortfolioReport",
    "Position",
    "Recommendation",
    "RiskAgent",
    "RiskAssessment",
    "RiskLimits",
    "Sentiment",
    "TechnicalAgent",
    "TechnicalView",
]
