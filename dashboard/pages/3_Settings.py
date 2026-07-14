from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import page_setup, render_sidebar, require_auth  # noqa: E402

page_setup("Settings", icon="gear")
render_sidebar()

user = require_auth()

st.title("Settings")

profile, security, admin = st.tabs(["Profile", "Security", "Admin"])

with profile:
    st.text_input("Email", value=user["email"], disabled=True)
    full_name = st.text_input("Full name", value=user.get("full_name") or "")
    st.text_input("Role", value=user["role"], disabled=True)

    if st.button("Save profile", type="primary"):
        try:
            st.session_state["user"] = api.update_profile(full_name)
            st.success("Profile updated.")
        except ApiError as exc:
            st.error(str(exc))

with security:
    current = st.text_input("Current password", type="password")
    new = st.text_input("New password", type="password")
    confirm = st.text_input("Confirm new password", type="password")

    if st.button("Change password"):
        if new != confirm:
            st.error("New passwords do not match.")
        else:
            try:
                api.change_password(current, new)
                st.success("Password changed. Other sessions stay valid until they expire.")
            except ApiError as exc:
                st.error(str(exc))

with admin:
    if not user.get("is_superuser"):
        st.info("Administrator access required.")
    else:
        try:
            data = api.list_users()
            df = pd.DataFrame(data["items"])
            if not df.empty:
                df = df[["id", "email", "full_name", "role", "is_active", "last_login_at"]]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"{data['total']} user(s)")
        except ApiError as exc:
            st.error(str(exc))
