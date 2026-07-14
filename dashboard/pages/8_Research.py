from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Research", icon="newspaper")
render_sidebar()
require_auth()

st.title("Research")
st.caption("Fundamentals and news are Yahoo/Google-News backed — results are cached server-side.")

fundamental_tab, news_tab, context_tab = st.tabs(["Fundamentals", "News", "Market context"])

# --- Fundamentals ----------------------------------------------------------------
with fundamental_tab:
    symbol = st.text_input("Symbol", value="RELIANCE", key="fund_symbol").strip().upper()
    if st.button("Score fundamentals", type="primary") and symbol:
        try:
            score = api.fundamental(symbol)
        except ApiError as exc:
            st.error(str(exc))
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Composite", f"{score['composite']:.2f}")
            c2.metric("Coverage", f"{score['coverage']:.0%}")
            c3.metric("Action", f"{score['action']} ({score['conviction']})")

            st.subheader("Components")
            st.dataframe(
                pd.DataFrame(
                    [{"component": k, "score": v} for k, v in score["components"].items()]
                ),
                use_container_width=True,
                hide_index=True,
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if score["strengths"]:
                    st.markdown("**Strengths**")
                    for s in score["strengths"]:
                        st.markdown(f"- {s}")
            with col_b:
                if score["concerns"]:
                    st.markdown("**Concerns**")
                    for s in score["concerns"]:
                        st.markdown(f"- {s}")

            if score["red_flags"]:
                st.subheader("Red flags")
                for s in score["red_flags"]:
                    st.markdown(f"- 🚩 {s}")

            with st.expander("Data caveats"):
                for c in score["data_caveats"]:
                    st.caption(c)

# --- News --------------------------------------------------------------------------
with news_tab:
    symbol = st.text_input("Symbol", value="RELIANCE", key="news_symbol").strip().upper()
    days = st.slider("Look-back (days)", min_value=1, max_value=30, value=7)
    if st.button("Fetch news", type="primary") and symbol:
        try:
            result = api.news(symbol, days=days)
        except ApiError as exc:
            st.error(str(exc))
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Score", f"{result['score']:.2f}")
            c2.metric("Dominant sentiment", result["dominant"])
            c3.metric("Action", f"{result['action']} ({result['conviction']})")

            if result["concerns"]:
                st.warning(" · ".join(result["concerns"]))

            st.subheader(f"Items ({result['item_count']})")
            if result["items"]:
                st.dataframe(
                    pd.DataFrame(result["items"])[
                        ["headline", "sentiment", "category", "confidence", "published_at", "source"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No news items in this window.")

# --- Market context ------------------------------------------------------------------
with context_tab:
    if st.button("Refresh market context", type="primary"):
        try:
            ctx = api.market_context()
        except ApiError as exc:
            st.error(str(exc))
        else:
            st.session_state["market_context"] = ctx

    ctx = st.session_state.get("market_context")
    if ctx:
        if ctx["risk_off"]:
            st.warning("Risk-off backdrop")
        else:
            st.success("Risk-on backdrop")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nifty", f"{ctx['nifty_change_pct']:+.2f}%" if ctx["nifty_change_pct"] is not None else "—")
        c2.metric("India VIX", ctx["india_vix"] if ctx["india_vix"] is not None else "—")
        c3.metric("USD/INR", ctx["usd_inr"] if ctx["usd_inr"] is not None else "—")
        c4.metric(
            "Crude",
            f"${ctx['crude_usd']:.1f}" if ctx["crude_usd"] is not None else "—",
            f"{ctx['crude_change_pct']:+.2f}%" if ctx["crude_change_pct"] is not None else None,
        )

        if ctx["notes"]:
            st.subheader("Notes")
            for n in ctx["notes"]:
                st.markdown(f"- {n}")
    else:
        st.info("Click **Refresh market context** to pull the latest backdrop.")
