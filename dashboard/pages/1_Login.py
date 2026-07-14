from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402
from dashboard.utils.api_client import ApiError, api  # noqa: E402
from dashboard.utils.state import is_authenticated, page_setup, render_sidebar  # noqa: E402

page_setup("Login", icon="key")
render_sidebar()

st.title("Sign in")

if is_authenticated():
    st.success(f"Already signed in as {st.session_state['user']['email']}")
    st.stop()

sign_in, sign_up = st.tabs(["Sign in", "Create account"])

with sign_in:
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")

    if st.button("Sign in", type="primary", use_container_width=True):
        if not email or not password:
            st.error("Email and password are required.")
        else:
            try:
                user = api.login(email, password)
                st.success(f"Welcome back, {user.get('full_name') or user['email']}")
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))

with sign_up:
    new_name = st.text_input("Full name", key="reg_name")
    new_email = st.text_input("Email", key="reg_email")
    new_password = st.text_input(
        "Password",
        type="password",
        key="reg_password",
        help="At least 8 characters, with a letter and a digit.",
    )
    confirm = st.text_input("Confirm password", type="password", key="reg_confirm")

    if st.button("Create account", use_container_width=True):
        if new_password != confirm:
            st.error("Passwords do not match.")
        elif not new_email or not new_password:
            st.error("Email and password are required.")
        else:
            try:
                api.register(new_email, new_password, new_name or None)
                st.success("Account created. Switch to the Sign in tab.")
            except ApiError as exc:
                st.error(str(exc))
