"""AITraderPro dashboard entrypoint.

Phase 1 ships the shell: auth, session handling, health and a placeholder
overview. Phases 2-4 fill in the portfolio, chart and scanner pages.
"""

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
st.caption("Algorithmic trading platform — Phase 1 foundation")

if not is_authenticated():
    st.info("Sign in from the **Login** page in the sidebar to access the dashboard.")
else:
    user = st.session_state["user"]
    st.success(f"Signed in as {user['email']}")

st.divider()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Phase 1 · Foundation", "Ready")
col2.metric("Phase 2 · Kite", "Planned")
col3.metric("Phase 3 · TradingView MCP", "Planned")
col4.metric("Phase 4 · Scanner", "Planned")

st.divider()

st.subheader("What is live today")
st.markdown(
    """
- **FastAPI backend** with versioned routes under `/api/v1`
- **JWT auth**: register, login, refresh-with-rotation, logout with a Redis blocklist
- **User management**: profile updates, password change, admin-only listing
- **Postgres + Alembic** migrations, **Redis** cache
- **Structured logging** with a request id on every line
- **Pytest** suite and **GitHub Actions** CI
"""
)

st.subheader("Coming next")
st.markdown(
    """
- **Phase 2** — Zerodha Kite login, portfolio, orders, live ticks over WebSocket
- **Phase 3** — TradingView MCP server, Claude Desktop integration, Pine Script generation
- **Phase 4** — Scanner engine (EMA, RSI, VWAP, Bollinger, MACD, breakouts), watchlists, alerts
"""
)
