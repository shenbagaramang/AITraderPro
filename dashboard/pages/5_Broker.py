from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Broker", icon="link")
render_sidebar()
require_auth()

st.title("Zerodha Kite")

try:
    status = api.broker_status()
except ApiError as exc:
    st.error(str(exc))
    st.stop()

# --- The daily reality of Kite ------------------------------------------------
if status["connected"]:
    st.success(
        f"Connected as **{status.get('broker_user_id', '?')}** — "
        f"session valid until {status.get('expires_at', '?')}"
    )
    st.caption(
        "Kite sessions die at ~6am IST every day, by regulatory design. "
        "You will be back on this page tomorrow morning. This is normal."
    )
    if st.button("Disconnect"):
        try:
            api.kite_disconnect()
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))
else:
    st.warning("No live Kite session. Paper trading works without one.")

    st.markdown(
        """
**The daily login, in two steps:**

1. Click the button below and log in to Kite in the tab that opens.
2. Kite redirects you to your registered redirect URL with `request_token=...`
   in the query string. Copy that token and paste it here.
"""
    )

    if st.button("Get Kite login URL", type="primary"):
        try:
            st.session_state["kite_login_url"] = api.kite_login_url()
        except ApiError as exc:
            st.error(str(exc))

    if url := st.session_state.get("kite_login_url"):
        st.link_button("Open Kite login", url, use_container_width=True)

    request_token = st.text_input(
        "Paste the request_token from the redirect URL",
        placeholder="e.g. AbC123xYz...",
    )
    if st.button("Complete login") and request_token:
        try:
            result = api.kite_complete_login(request_token.strip())
            st.success(f"Connected as {result.get('broker_user_id')}")
            st.session_state.pop("kite_login_url", None)
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))

st.divider()

# --- Live book, when connected --------------------------------------------------
if status["connected"]:
    import pandas as pd

    tabs = st.tabs(["Holdings", "Positions", "Margins"])

    with tabs[0]:
        try:
            rows = api.holdings(paper=False)
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No holdings.")
        except ApiError as exc:
            st.error(str(exc))

    with tabs[1]:
        try:
            rows = api.positions(paper=False)
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No open positions.")
        except ApiError as exc:
            st.error(str(exc))

    with tabs[2]:
        try:
            m = api.margins(paper=False)
            a, b, c = st.columns(3)
            a.metric("Available cash", f"₹{m['available_cash']:,.0f}")
            b.metric("Used margin", f"₹{m['used_margin']:,.0f}")
            c.metric("Net", f"₹{m['net']:,.0f}")
        except ApiError as exc:
            st.error(str(exc))
