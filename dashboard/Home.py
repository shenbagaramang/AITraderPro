"""AITraderPro dashboard entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402
from dashboard.utils.state import (  # noqa: E402
    is_authenticated,
    page_setup,
    render_sidebar,
)

page_setup("Home")
render_sidebar()

st.title("AITraderPro")
st.caption("AI-assisted algorithmic trading platform for NSE/BSE")

if not is_authenticated():
    st.info("Sign in from the **Login** page in the sidebar to access the dashboard.")
else:
    user = st.session_state["user"]
    st.success(f"Signed in as {user['email']}")

st.divider()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Foundation", "Ready")
col2.metric("Zerodha Kite", "Ready")
col3.metric("TradingView MCP", "Ready")
col4.metric("Scanner + agents", "Ready")

st.divider()

st.subheader("What is live today")
st.markdown(
    """
- **FastAPI backend** with versioned routes under `/api/v1`
- **JWT auth**: register, login, refresh-with-rotation, logout with a Redis blocklist
- **User management**: profile updates, password change, admin-only listing
- **Postgres + Alembic** migrations, **Redis** cache
- **Structured logging** with a request id on every line
- **Zerodha Kite** — daily login flow, portfolio/positions/margins, order placement
  (paper or live) with an audit trail, KiteTicker → Redis tick fan-out
- **Scanner engine** — 10 indicators, 8 scanners (EMA, breakout, volume, Bollinger,
  momentum, VWAP, ADX, Ichimoku), watchlists and a state-change alert inbox
- **AI agents** — technical, risk, portfolio, fundamental (Yahoo) and news
  (Google News) agents feeding a decision engine with explicit vetoes
- **MCP server** — exposes the decision engine, Pine Script generation and paper
  trading to Claude Desktop as a thin, fully-audited client of this same API
- **Pytest** suite (200+ tests) and **GitHub Actions** CI
"""
)

st.subheader("Known gaps")
st.markdown(
    """
- Historical candles are supplied by the caller (upload/paste), not fetched
  server-side — there's no free intraday data source wired in yet
- KiteTicker publishes live ticks to Redis, but nothing in this dashboard
  subscribes to them; the **Trade**/**Broker** pages poll REST quotes instead
"""
)
