from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Analysis", icon="brain")
render_sidebar()
require_auth()

st.title("Analysis")
st.caption(
    "Candles are supplied by you, not fetched server-side — there is no free "
    "historical-data source wired in yet. Upload a CSV or paste OHLCV rows."
)

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def _candles_input(key: str) -> list[dict] | None:
    symbol = st.text_input("Symbol", value="RELIANCE", key=f"{key}_symbol").strip().upper()

    upload = st.file_uploader(
        "CSV with columns: timestamp (optional), open, high, low, close, volume",
        type="csv",
        key=f"{key}_upload",
    )
    if upload is not None:
        try:
            df = pd.read_csv(upload)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not parse CSV: {exc}")
            return None
    else:
        pasted = st.text_area(
            "...or paste CSV rows",
            placeholder="timestamp,open,high,low,close,volume\n2024-01-01,100,102,99,101,150000",
            key=f"{key}_paste",
            height=120,
        )
        if not pasted.strip():
            return None
        try:
            from io import StringIO

            df = pd.read_csv(StringIO(pasted))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not parse pasted rows: {exc}")
            return None

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        st.error(f"Missing column(s): {', '.join(missing)}")
        return None
    if len(df) < 30:
        st.warning(f"Only {len(df)} rows — the analysis endpoints need at least 30.")
        return None

    st.session_state[f"{key}_symbol_value"] = symbol
    return df.to_dict(orient="records")


technical_tab, decision_tab, pine_tab = st.tabs(["Technical view", "Decision engine", "Pine Script"])

# --- Technical agent -----------------------------------------------------------
with technical_tab:
    candles = _candles_input("technical")
    if candles and st.button("Run technical analysis", type="primary"):
        symbol = st.session_state["technical_symbol_value"]
        try:
            result = api.analyze_technical(symbol, candles)
        except ApiError as exc:
            st.error(str(exc))
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Bias", result["bias"])
            c2.metric("Conviction", result["conviction"])
            c3.metric("Score", f"{result['score']:.2f}")
            c4.metric("Agreement", f"{result['agreement']:.0%}")

            st.caption(f"Regime: {result['regime']} · Suggested action: {result['action']}")

            if result["rationale"]:
                st.subheader("Rationale")
                for line in result["rationale"]:
                    st.markdown(f"- {line}")
            if result["conflicts"]:
                st.subheader("Conflicts")
                for line in result["conflicts"]:
                    st.markdown(f"- ⚠️ {line}")

            st.subheader("Scanner signals")
            st.dataframe(
                pd.DataFrame(result["signals"])[["scanner", "direction", "strength", "reason"]],
                use_container_width=True,
                hide_index=True,
            )

# --- Decision engine -------------------------------------------------------------
with decision_tab:
    candles = _candles_input("decision")
    equity = st.number_input("Account equity (₹)", min_value=1.0, value=100000.0, step=1000.0)
    lot_size = st.number_input("Lot size", min_value=1, value=1, step=1)

    if candles and st.button("Run decision engine", type="primary"):
        symbol = st.session_state["decision_symbol_value"]
        try:
            decision = api.analyze_decide(symbol, candles, equity=equity, lot_size=int(lot_size))
        except ApiError as exc:
            st.error(str(exc))
        else:
            if decision["outcome"] == "no_trade":
                st.warning(f"No trade — {decision['action']}")
            else:
                st.success(f"{decision['outcome'].upper()}: {decision['action']}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Confidence", f"{decision['confidence']:.0%}")
            c2.metric("Quantity", decision["quantity"])
            c3.metric("Entry", decision["entry"] or "—")
            c4.metric("Stop / Target", f"{decision['stop_loss'] or '—'} / {decision['target'] or '—'}")

            if decision["reasons"]:
                st.subheader("Reasons")
                for line in decision["reasons"]:
                    st.markdown(f"- {line}")
            if decision["vetoes"]:
                st.subheader("Vetoes")
                for line in decision["vetoes"]:
                    st.markdown(f"- 🛑 {line}")

            st.subheader("Agent votes")
            st.dataframe(
                pd.DataFrame(
                    [{"agent": k, "vote": v} for k, v in decision["agent_votes"].items()]
                ),
                use_container_width=True,
                hide_index=True,
            )

# --- Pine Script generation -------------------------------------------------------
with pine_tab:
    try:
        templates = api.pine_templates()
    except ApiError as exc:
        st.error(str(exc))
        templates = []

    if templates:
        scanner = st.selectbox("Scanner template", options=templates)
        params_raw = st.text_area(
            "Params (JSON, optional)",
            value="{}",
            help='e.g. {"fast_length": 9, "slow_length": 21}',
        )
        if st.button("Generate Pine script", type="primary"):
            import json

            try:
                params = json.loads(params_raw) if params_raw.strip() else {}
            except json.JSONDecodeError as exc:
                st.error(f"Params must be valid JSON: {exc}")
                params = None

            if params is not None:
                try:
                    script = api.generate_pine(scanner, params)
                except ApiError as exc:
                    st.error(str(exc))
                else:
                    st.code(script["source"], language="text")
                    st.download_button(
                        "Download .pine",
                        script["source"],
                        file_name=f"{script['name']}.pine",
                    )
                    if script["alerts"]:
                        st.subheader("Alert conditions")
                        for a in script["alerts"]:
                            st.markdown(f"- `{a}`")
                    st.info(script["instructions"])
