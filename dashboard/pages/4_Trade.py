from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Trade", icon="chart_with_upwards_trend")
render_sidebar()
require_auth()

st.title("Trade")
st.caption(
    "Orders go to the **paper broker** unless live trading is enabled server-side "
    "and you untick the paper box. Paper fills include slippage against you — "
    "that is deliberate."
)

ticket, book = st.columns([1, 2], gap="large")

# --- Order ticket -----------------------------------------------------------
with ticket:
    st.subheader("Order ticket")

    symbol = st.text_input("Symbol", value="RELIANCE").strip().upper()
    side = st.radio("Side", ["BUY", "SELL"], horizontal=True)
    quantity = st.number_input("Quantity", min_value=1, value=10, step=1)
    order_type = st.selectbox("Order type", ["MARKET", "LIMIT", "SL-M"])

    price = None
    trigger = None
    if order_type == "LIMIT":
        price = st.number_input("Limit price", min_value=0.05, value=100.0, step=0.05)
    if order_type == "SL-M":
        trigger = st.number_input("Trigger price", min_value=0.05, value=95.0, step=0.05)

    with st.expander("Risk (optional)"):
        stop_loss = st.number_input("Stop loss", min_value=0.0, value=0.0, step=0.05)
        target = st.number_input("Target", min_value=0.0, value=0.0, step=0.05)

    paper = st.checkbox(
        "Paper trade", value=True, help="Untick only if live trading is enabled."
    )

    # The idempotency key lives in session state so a Streamlit rerun (double
    # click, browser refresh mid-request) cannot place the same order twice.
    if "ticket_key" not in st.session_state:
        st.session_state["ticket_key"] = str(uuid.uuid4())

    if st.button(f"{side} {quantity} {symbol}", type="primary", use_container_width=True):
        if paper and symbol not in st.session_state.get("seeded", set()):
            st.info(
                "Paper broker has no price for this symbol yet — quote it once "
                "below to seed it, or place the order after a quote."
            )
        try:
            order = api.place_order(
                symbol=symbol,
                side=side,
                quantity=int(quantity),
                order_type=order_type,
                price=price,
                trigger_price=trigger,
                stop_loss=stop_loss or None,
                target=target or None,
                idempotency_key=st.session_state["ticket_key"],
                paper=paper,
            )
            st.session_state.pop("ticket_key")  # a new ticket gets a new key
            status = order["status"]
            if status == "REJECTED":
                st.error(f"REJECTED: {order.get('status_message')}")
            else:
                filled = order.get("average_price")
                st.success(
                    f"{status}: {order['side']} {order['quantity']} {order['symbol']}"
                    + (f" @ ₹{filled}" if filled else "")
                )
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Quote")
    quote_symbol = st.text_input("Quote symbol", value=symbol, key="quote_sym").strip().upper()
    if st.button("Get quote", use_container_width=True):
        try:
            data = api.quotes([quote_symbol], paper=paper)
            if not data:
                st.warning(
                    "No quote. On paper, a symbol gets a price the first time it "
                    "trades; on Kite, prefix the exchange (NSE:RELIANCE)."
                )
            for key, quote in data.items():
                change = quote.get("change_pct")
                st.metric(
                    key,
                    f"₹{quote['last_price']:,.2f}",
                    f"{change:+.2f}%" if change is not None else None,
                )
        except ApiError as exc:
            st.error(str(exc))

# --- Order book ---------------------------------------------------------------
with book:
    st.subheader("Orders")
    try:
        rows = api.orders(limit=50)
    except ApiError as exc:
        st.error(str(exc))
        rows = []

    if not rows:
        st.info("No orders yet. The first one is the hardest.")
    else:
        frame = pd.DataFrame(rows)[
            [
                "id",
                "symbol",
                "side",
                "quantity",
                "order_type",
                "average_price",
                "status",
                "is_paper",
                "created_at",
            ]
        ]
        frame["mode"] = frame.pop("is_paper").map({True: "paper", False: "LIVE"})
        st.dataframe(frame, use_container_width=True, hide_index=True)

        open_orders = [r for r in rows if r["status"] in ("OPEN", "PENDING")]
        if open_orders:
            st.subheader("Cancel a resting order")
            target_id = st.selectbox(
                "Order",
                options=[r["id"] for r in open_orders],
                format_func=lambda oid: next(
                    f"#{r['id']} {r['side']} {r['quantity']} {r['symbol']} ({r['order_type']})"
                    for r in open_orders
                    if r["id"] == oid
                ),
            )
            if st.button("Cancel order"):
                try:
                    api.cancel_order(int(target_id))
                    st.success(f"Order #{target_id} cancelled")
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))

    st.divider()
    st.subheader("Paper account")
    left, right = st.columns(2)
    with left:
        if st.button("Reset paper account"):
            try:
                result = api.reset_paper()
                st.success(f"{result['message']} — ₹{result['starting_cash']:,.0f}")
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))
    with right:
        try:
            m = api.margins(paper=True)
            st.metric("Paper cash", f"₹{m['available_cash']:,.0f}")
        except ApiError:
            pass
