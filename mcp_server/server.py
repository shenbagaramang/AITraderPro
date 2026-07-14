"""AITraderPro MCP server for Claude Desktop.

Architecture: this is a **thin client of the REST API**, not a second way into
the database. Every tool call goes through the same authenticated routes, the
same role checks, the same kill switch and the same audit log as the dashboard.
An MCP server with its own DB connection would be a second, unaudited door.

Setup (Claude Desktop -> claude_desktop_config.json):

    {
      "mcpServers": {
        "aitraderpro": {
          "command": "python",
          "args": ["/path/to/AITraderPro/mcp_server/server.py"],
          "env": {
            "AITRADERPRO_URL": "http://localhost:8000/api/v1",
            "AITRADERPRO_EMAIL": "you@example.com",
            "AITRADERPRO_PASSWORD": "..."
          }
        }
      }
    }

Requires: pip install "mcp[cli]" httpx
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("AITRADERPRO_URL", "http://localhost:8000/api/v1")

mcp = FastMCP(
    "aitraderpro",
    instructions=(
        "Tools for the AITraderPro platform: technical analysis, the full "
        "decision engine, Pine Script generation, paper trading and the order "
        "book. Orders default to PAPER. The decision engine's default answer "
        "is no-trade; treat a veto as information, not an obstacle."
    ),
)

_tokens: dict[str, str] = {}


def _login(client: httpx.Client) -> None:
    email = os.environ.get("AITRADERPRO_EMAIL")
    password = os.environ.get("AITRADERPRO_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Set AITRADERPRO_EMAIL and AITRADERPRO_PASSWORD in the MCP server env"
        )
    resp = client.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    _tokens.update(resp.json())


def _call(method: str, path: str, **kwargs: Any) -> Any:
    """Authenticated request with one automatic re-login on 401."""
    with httpx.Client(timeout=30.0) as client:
        if not _tokens:
            _login(client)

        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {_tokens['access_token']}"}
            resp = client.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
            if resp.status_code == 401 and attempt == 1:
                _login(client)
                continue
            break

        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]
            except Exception:
                detail = {"message": resp.text}
            # Errors are returned as data, not raised: a veto or a halt is an
            # answer Claude should relay, not a stack trace.
            return {"error": detail, "status_code": resp.status_code}
        return resp.json() if resp.content else {"ok": True}


# --- analysis ----------------------------------------------------------------
@mcp.tool()
def analyze_technical(symbol: str, candles: list[dict]) -> dict:
    """Run all 8 scanners and the technical agent on OHLCV candles.

    candles: list of {timestamp?, open, high, low, close, volume}, oldest first,
    at least 30 rows (150+ recommended so every indicator is warmed up).
    Returns bias, conviction, regime, per-scanner signals, and the dissent.
    """
    return _call("POST", "/analysis/technical", json={"symbol": symbol, "candles": candles})


@mcp.tool()
def run_decision_engine(
    symbol: str, candles: list[dict], equity: float, lot_size: int = 1
) -> dict:
    """Run the full decision engine: technical proposes, filters veto, risk sizes.

    Returns TRADE (with quantity/entry/stop/target), NO_TRADE, or VETOED —
    plus every agent's vote and the reasons. A veto is a result, not a failure.
    """
    return _call(
        "POST",
        "/analysis/decide",
        json={"symbol": symbol, "candles": candles, "equity": equity, "lot_size": lot_size},
    )


# --- Pine Script ----------------------------------------------------------------
@mcp.tool()
def list_pine_templates() -> dict:
    """List the available Pine v6 script templates (one per scanner)."""
    return _call("GET", "/analysis/pine/templates")


@mcp.tool()
def generate_pine_script(scanner: str, params: dict | None = None) -> dict:
    """Generate a Pine v6 script whose parameters and smoothing exactly match the
    named scanner, so chart signals reconcile with platform signals.

    scanner: ema | bollinger | momentum | vwap | breakout | supertrend
    params: optional overrides, e.g. {"fast": 5, "slow": 13} for ema.
    """
    return _call("POST", "/analysis/pine", json={"scanner": scanner, "params": params or {}})


# --- trading (paper by default) ---------------------------------------------------
@mcp.tool()
def place_paper_order(
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "MARKET",
    price: float | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Place a PAPER order. side: BUY|SELL. order_type: MARKET|LIMIT.

    This tool cannot place live orders — it hard-codes paper=true. Live trading
    goes through the dashboard, deliberately.
    """
    return _call(
        "POST",
        "/orders",
        json={
            "symbol": symbol,
            "side": side.upper(),
            "quantity": quantity,
            "order_type": order_type.upper(),
            "price": price,
            "idempotency_key": idempotency_key,
            "paper": True,
        },
    )


@mcp.tool()
def get_orders(limit: int = 20) -> dict:
    """Recent orders (paper and live), newest first, with status and fill prices."""
    return {"orders": _call("GET", "/orders", params={"limit": limit})}


@mcp.tool()
def get_portfolio(paper: bool = True) -> dict:
    """Positions, holdings and margins for the paper (default) or live book."""
    params = {"paper": str(paper).lower()}
    return {
        "positions": _call("GET", "/broker/positions", params=params),
        "holdings": _call("GET", "/broker/holdings", params=params),
        "margins": _call("GET", "/broker/margins", params=params),
    }


@mcp.tool()
def get_quotes(symbols: list[str], paper: bool = True) -> dict:
    """Quotes for up to 50 symbols. Prefix with exchange for live (NSE:RELIANCE)."""
    return _call(
        "GET",
        "/broker/quotes",
        params={"symbols": ",".join(symbols), "paper": str(paper).lower()},
    )


@mcp.tool()
def platform_status() -> dict:
    """API health, broker session state, and whether the kill switch is on."""
    return {
        "health": _call("GET", "/health"),
        "broker": _call("GET", "/broker/status"),
    }


if __name__ == "__main__":
    mcp.run()
