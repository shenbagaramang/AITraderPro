"""Shared Streamlit page helpers: auth gate, sidebar, page config."""

from __future__ import annotations

from typing import Any

import streamlit as st
from dashboard.utils.api_client import ApiError, api


def page_setup(title: str, icon: str = "chart_with_upwards_trend") -> None:
    st.set_page_config(
        page_title=f"{title} | AITraderPro",
        page_icon=":" + icon + ":",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def is_authenticated() -> bool:
    return "tokens" in st.session_state and "user" in st.session_state


def current_user() -> dict[str, Any] | None:
    return st.session_state.get("user")


def require_auth() -> dict[str, Any]:
    """Stop rendering the page unless the visitor is logged in."""
    if not is_authenticated():
        st.warning("Please sign in on the Login page to continue.")
        st.stop()
    return current_user()  # type: ignore[return-value]


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### AITraderPro")

        user = current_user()
        if user:
            st.caption(f"{user.get('full_name') or user['email']}")
            st.caption(f"Role: {user['role']}")
            if st.button("Sign out", use_container_width=True):
                api.logout()
                st.rerun()
        else:
            st.caption("Not signed in")

        st.divider()
        try:
            health = api.health()
            status = health["status"]
            icon = "🟢" if status == "ok" else "🟡"
            st.caption(f"{icon} API {status} · v{health['version']}")
            st.caption(
                f"DB {'up' if health['database'] else 'down'} · "
                f"Redis {'up' if health['redis'] else 'down'}"
            )
        except ApiError as exc:
            st.caption(f"🔴 API unreachable — {exc}")

        st.divider()
        st.caption("Foundation · Kite · MCP · Scanner — all live")
