"""The scanner engine as a product: watchlists, the scan loop, the alert diff."""

from __future__ import annotations

import numpy as np
import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import auth_header
from tests.fixtures import flat, make_ohlcv, trending

BASE = "/api/v1/scanner"


def rows_from(closes, volumes=None) -> list[dict]:
    df = make_ohlcv(closes, volumes, intraday=True)
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


def bullish_rows() -> list[dict]:
    rng = np.random.default_rng(5)
    closes = np.r_[flat(100, 100.0, noise=0.5), 100.0 + np.cumsum(rng.uniform(0.5, 1.5, 40))]
    return rows_from(closes, np.r_[np.full(100, 1e5), np.linspace(2e5, 5e5, 40)])


def bearish_rows() -> list[dict]:
    return rows_from(trending(150, start=300.0, drift=-1.0))


async def make_watchlist(client: AsyncClient, user: User, symbols: list[str]) -> int:
    resp = await client.post(
        f"{BASE}/watchlists",
        headers=auth_header(user),
        json={"name": "intraday", "symbols": symbols},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


class TestWatchlists:
    @pytest.mark.asyncio
    async def test_crud_roundtrip(self, client: AsyncClient, trader_user: User):
        wid = await make_watchlist(client, trader_user, ["reliance", "tcs", "TCS", " infy "])

        listed = await client.get(f"{BASE}/watchlists", headers=auth_header(trader_user))
        wl = listed.json()[0]
        # Normalised: uppercased, deduped, sorted, whitespace stripped.
        assert wl["symbols"] == ["INFY", "RELIANCE", "TCS"]

        updated = await client.put(
            f"{BASE}/watchlists/{wid}",
            headers=auth_header(trader_user),
            json={"name": "intraday", "symbols": ["SBIN"]},
        )
        assert updated.json()["symbols"] == ["SBIN"]

        deleted = await client.delete(
            f"{BASE}/watchlists/{wid}", headers=auth_header(trader_user)
        )
        assert deleted.status_code == 200

    @pytest.mark.asyncio
    async def test_duplicate_name_conflicts(self, client: AsyncClient, trader_user: User):
        await make_watchlist(client, trader_user, ["TCS"])
        resp = await client.post(
            f"{BASE}/watchlists",
            headers=auth_header(trader_user),
            json={"name": "intraday", "symbols": []},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_watchlists_are_per_user(
        self, client: AsyncClient, trader_user: User, admin_user: User
    ):
        await make_watchlist(client, trader_user, ["TCS"])
        theirs = await client.get(f"{BASE}/watchlists", headers=auth_header(admin_user))
        assert theirs.json() == []


class TestScanLoop:
    @pytest.mark.asyncio
    async def test_scan_persists_results_and_reports_actionables(
        self, client: AsyncClient, trader_user: User
    ):
        wid = await make_watchlist(client, trader_user, ["TCS", "NODATA"])

        resp = await client.post(
            f"{BASE}/watchlists/{wid}/scan",
            headers=auth_header(trader_user),
            json={"candles": {"TCS": bullish_rows()}},
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["scanned"] == ["TCS"]
        # The symbol with no feed is reported, not fatal.
        assert "NODATA" in body["skipped"]
        assert body["actionable"]

        results = await client.get(
            f"{BASE}/results",
            headers=auth_header(trader_user),
            params={"actionable_only": "false"},
        )
        assert len(results.json()) == 8  # every scanner persisted, neutrals included

    @pytest.mark.asyncio
    async def test_first_scan_raises_alerts_rescan_raises_none(
        self, client: AsyncClient, trader_user: User
    ):
        """THE feature: same state on a rescan is silence, not a repeat alert."""
        wid = await make_watchlist(client, trader_user, ["TCS"])
        payload = {"candles": {"TCS": bullish_rows()}}

        first = await client.post(
            f"{BASE}/watchlists/{wid}/scan", headers=auth_header(trader_user), json=payload
        )
        assert len(first.json()["new_alerts"]) > 0

        second = await client.post(
            f"{BASE}/watchlists/{wid}/scan", headers=auth_header(trader_user), json=payload
        )
        assert second.json()["new_alerts"] == []
        # But the signals themselves are still reported as actionable.
        assert second.json()["actionable"]

    @pytest.mark.asyncio
    async def test_direction_flip_raises_a_fresh_alert(
        self, client: AsyncClient, trader_user: User
    ):
        wid = await make_watchlist(client, trader_user, ["TCS"])

        await client.post(
            f"{BASE}/watchlists/{wid}/scan",
            headers=auth_header(trader_user),
            json={"candles": {"TCS": bullish_rows()}},
        )
        flipped = await client.post(
            f"{BASE}/watchlists/{wid}/scan",
            headers=auth_header(trader_user),
            json={"candles": {"TCS": bearish_rows()}},
        )

        alerts = flipped.json()["new_alerts"]
        assert alerts

        # The trend-following scanners flipped bullish -> bearish: fresh alerts.
        by_scanner = {a["scanner"]: a["direction"] for a in alerts}
        assert by_scanner.get("ema") == "bearish"
        assert by_scanner.get("momentum") == "bearish"

        # The vwap scanner may legitimately alert BULLISH here — deep below
        # VWAP is its mean-reversion "bounce candidate" signal by design. The
        # diff must not suppress a genuine counter-trend signal just because
        # the majority flipped the other way.

    @pytest.mark.asyncio
    async def test_scanner_subset_via_only(self, client: AsyncClient, trader_user: User):
        wid = await make_watchlist(client, trader_user, ["TCS"])
        resp = await client.post(
            f"{BASE}/watchlists/{wid}/scan",
            headers=auth_header(trader_user),
            json={"candles": {"TCS": bullish_rows()}, "only": ["ema", "momentum"]},
        )
        assert resp.status_code == 200

        results = await client.get(
            f"{BASE}/results",
            headers=auth_header(trader_user),
            params={"actionable_only": "false"},
        )
        assert {r["scanner"] for r in results.json()} == {"ema", "momentum"}


class TestAlertInbox:
    @pytest.mark.asyncio
    async def test_acknowledge_clears_the_inbox(self, client: AsyncClient, trader_user: User):
        wid = await make_watchlist(client, trader_user, ["TCS"])
        await client.post(
            f"{BASE}/watchlists/{wid}/scan",
            headers=auth_header(trader_user),
            json={"candles": {"TCS": bullish_rows()}},
        )

        inbox = await client.get(f"{BASE}/alerts", headers=auth_header(trader_user))
        ids = [a["id"] for a in inbox.json()]
        assert ids

        ack = await client.post(
            f"{BASE}/alerts/ack", headers=auth_header(trader_user), json=ids
        )
        assert ack.status_code == 200

        after = await client.get(f"{BASE}/alerts", headers=auth_header(trader_user))
        assert after.json() == []

        history = await client.get(
            f"{BASE}/alerts",
            headers=auth_header(trader_user),
            params={"unacknowledged_only": "false"},
        )
        assert len(history.json()) == len(ids)  # acked, not deleted
