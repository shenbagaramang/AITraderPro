"""Analysis, Pine and webhook routes over HTTP."""

from __future__ import annotations

import numpy as np
import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import auth_header
from tests.fixtures import flat, make_ohlcv

ANALYSIS = "/api/v1/analysis"
WEBHOOK = "/api/v1/webhooks/tradingview"


def candle_payload(n_extra: int = 40) -> list[dict]:
    rng = np.random.default_rng(5)
    closes = np.r_[
        flat(100, 100.0, noise=0.5), 100.0 + np.cumsum(rng.uniform(0.5, 1.5, n_extra))
    ]
    df = make_ohlcv(
        closes, np.r_[np.full(100, 1e5), np.linspace(2e5, 5e5, n_extra)], intraday=True
    )
    return [
        {
            "timestamp": str(ts),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }
        for ts, r in df.iterrows()
    ]


class TestAnalysisRoutes:
    @pytest.mark.asyncio
    async def test_technical_analysis_over_http(self, client: AsyncClient, trader_user: User):
        resp = await client.post(
            f"{ANALYSIS}/technical",
            headers=auth_header(trader_user),
            json={"symbol": "tcs", "candles": candle_payload()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "TCS"
        assert body["bias"] == "bullish"
        assert len(body["signals"]) == 8
        assert body["rationale"]

    @pytest.mark.asyncio
    async def test_decision_engine_over_http(self, client: AsyncClient, trader_user: User):
        resp = await client.post(
            f"{ANALYSIS}/decide",
            headers=auth_header(trader_user),
            json={"symbol": "TCS", "candles": candle_payload(), "equity": 1_000_000},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "trade"
        assert body["quantity"] > 0
        assert body["stop_loss"] < body["entry"]
        assert set(body["agent_votes"]) >= {"technical", "risk"}

    @pytest.mark.asyncio
    async def test_too_few_candles_is_a_422(self, client: AsyncClient, trader_user: User):
        resp = await client.post(
            f"{ANALYSIS}/technical",
            headers=auth_header(trader_user),
            json={"symbol": "TCS", "candles": candle_payload()[:10]},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_pine_generation_over_http(self, client: AsyncClient, trader_user: User):
        resp = await client.post(
            f"{ANALYSIS}/pine",
            headers=auth_header(trader_user),
            json={"scanner": "ema", "params": {"fast": 5, "slow": 13}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"].startswith("//@version=6")
        assert body["params"]["fast"] == 5
        assert "barstate.isconfirmed" in body["source"]

    @pytest.mark.asyncio
    async def test_analysis_requires_auth(self, client: AsyncClient):
        resp = await client.post(f"{ANALYSIS}/technical", json={"symbol": "X", "candles": []})
        assert resp.status_code == 401


class TestWebhook:
    @pytest.mark.asyncio
    async def test_valid_secret_records_the_alert(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session
    ):
        from app.api.v1 import webhooks as module

        monkeypatch.setattr(module.settings, "TRADINGVIEW_WEBHOOK_SECRET", "s3cret")
        monkeypatch.setattr(module, "AsyncSessionLocal", lambda: _SessionCtx(db_session))

        resp = await client.post(
            WEBHOOK,
            json={
                "secret": "s3cret",
                "ticker": "RELIANCE",
                "alert_name": "EMA Cross Long",
                "direction": "long",
                "price": 2450.5,
            },
        )
        assert resp.status_code == 202

        from sqlalchemy import select

        from app.models.alert import WebhookAlert

        stored = (await db_session.execute(select(WebhookAlert))).scalars().all()
        assert len(stored) == 1
        assert stored[0].symbol == "RELIANCE"
        # The secret must never reach the audit trail.
        assert "s3cret" not in stored[0].raw_body

    @pytest.mark.asyncio
    async def test_bad_secret_is_rejected(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        from app.api.v1 import webhooks as module

        monkeypatch.setattr(module.settings, "TRADINGVIEW_WEBHOOK_SECRET", "s3cret")
        resp = await client.post(WEBHOOK, json={"secret": "wrong", "ticker": "X"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_unconfigured_secret_refuses_everything(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """No secret configured means the endpoint is CLOSED, not open."""
        from app.api.v1 import webhooks as module

        monkeypatch.setattr(module.settings, "TRADINGVIEW_WEBHOOK_SECRET", "")
        resp = await client.post(WEBHOOK, json={"ticker": "X"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "webhook_disabled"

    @pytest.mark.asyncio
    async def test_non_json_body_is_rejected(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        from app.api.v1 import webhooks as module

        monkeypatch.setattr(module.settings, "TRADINGVIEW_WEBHOOK_SECRET", "s3cret")
        resp = await client.post(WEBHOOK, content=b"not json")
        assert resp.status_code == 401


class _SessionCtx:
    """Adapts the test's session fixture to the `async with` the webhook uses."""

    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    async def __aenter__(self):  # noqa: ANN204
        return self._session

    async def __aexit__(self, *exc) -> None:  # noqa: ANN002
        pass
