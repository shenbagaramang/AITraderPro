from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Scanner", icon="mag")
render_sidebar()
require_auth()

st.title("Scanner")
st.caption(
    "Alerts fire on state CHANGE only — a squeeze that fired yesterday does not "
    "re-alert on every rescan. Scans are triggered by your data pipeline "
    "(n8n / TradingView webhooks) via POST /scanner/watchlists/{id}/scan."
)

alerts_tab, results_tab, lists_tab = st.tabs(["Alerts", "Results", "Watchlists"])

with alerts_tab:
    show_all = st.toggle("Include acknowledged", value=False)
    try:
        rows = api._request(
            "GET",
            "/scanner/alerts",
            params={"unacknowledged_only": str(not show_all).lower(), "limit": 100},
        )
    except ApiError as exc:
        st.error(str(exc))
        rows = []

    if not rows:
        st.info("No alerts. That is a valid market state, not a bug.")
    else:
        frame = pd.DataFrame(rows)[
            ["id", "symbol", "scanner", "direction", "strength", "reason", "created_at"]
        ]
        st.dataframe(frame, use_container_width=True, hide_index=True)

        to_ack = st.multiselect("Acknowledge", options=[r["id"] for r in rows])
        if st.button("Acknowledge selected") and to_ack:
            try:
                api._request("POST", "/scanner/alerts/ack", json=to_ack)
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))

with results_tab:
    symbol = st.text_input("Filter by symbol (optional)").strip().upper()
    actionable = st.toggle("Actionable only", value=True)
    try:
        params = {"actionable_only": str(actionable).lower(), "limit": 200}
        if symbol:
            params["symbol"] = symbol
        rows = api._request("GET", "/scanner/results", params=params)
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No results yet — run a scan through the API.")
    except ApiError as exc:
        st.error(str(exc))

with lists_tab:
    try:
        lists = api._request("GET", "/scanner/watchlists")
    except ApiError as exc:
        st.error(str(exc))
        lists = []

    for wl in lists:
        with st.expander(f"{wl['name']} ({len(wl['symbols'])} symbols)"):
            edited = st.text_area(
                "Symbols (comma or newline separated)",
                value=", ".join(wl["symbols"]),
                key=f"wl_{wl['id']}",
            )
            col_save, col_del = st.columns(2)
            if col_save.button("Save", key=f"save_{wl['id']}"):
                symbols = [s.strip() for s in edited.replace("\n", ",").split(",")]
                try:
                    api._request(
                        "PUT",
                        f"/scanner/watchlists/{wl['id']}",
                        json={"name": wl["name"], "symbols": [s for s in symbols if s]},
                    )
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))
            if col_del.button("Delete", key=f"del_{wl['id']}"):
                try:
                    api._request("DELETE", f"/scanner/watchlists/{wl['id']}")
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))

    st.divider()
    st.subheader("New watchlist")
    name = st.text_input("Name")
    symbols_raw = st.text_area("Symbols", placeholder="RELIANCE, TCS, INFY")
    if st.button("Create", type="primary") and name:
        symbols = [s.strip() for s in symbols_raw.replace("\n", ",").split(",") if s.strip()]
        try:
            api._request(
                "POST", "/scanner/watchlists", json={"name": name, "symbols": symbols}
            )
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))
