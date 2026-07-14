from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Overview")
render_sidebar()
require_auth()

st.title("Portfolio overview")

mode = st.radio("Book", ["Paper", "Live (Kite)"], horizontal=True)
paper = mode == "Paper"

if not paper:
    try:
        status = api.broker_status()
        if not status["connected"]:
            st.warning("No live Kite session — see the **Broker** page. Showing nothing here.")
            st.stop()
    except ApiError as exc:
        st.error(str(exc))
        st.stop()

try:
    margins = api.margins(paper=paper)
    positions = api.positions(paper=paper)
    holdings = api.holdings(paper=paper)
except ApiError as exc:
    st.error(str(exc))
    st.stop()

total_pnl = sum(p["pnl"] for p in positions) + sum(h["pnl"] for h in holdings)
exposure = sum(p["value"] for p in positions) + sum(h["value"] for h in holdings)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cash", f"₹{margins['available_cash']:,.0f}")
c2.metric("Exposure", f"₹{exposure:,.0f}")
c3.metric("Open P&L", f"₹{total_pnl:,.0f}")
c4.metric("Open positions", str(len(positions)))

st.divider()

st.subheader("Positions")
if positions:
    st.dataframe(
        pd.DataFrame(positions)[
            ["symbol", "quantity", "average_price", "last_price", "pnl", "value"]
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No open positions.")

st.subheader("Holdings")
if holdings:
    st.dataframe(
        pd.DataFrame(holdings)[
            ["symbol", "quantity", "average_price", "last_price", "pnl", "value"]
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(
        "No holdings. Place a paper trade on the **Trade** page — it flows "
        "through the exact same code path a live order will."
    )
