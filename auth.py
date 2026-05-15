"""Authentication module for Mirra app."""

import hashlib
import streamlit as st
import base64


def hash_pw(password: str) -> str:
    """Hash a password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def render_login_page(supabase):
    """Render the login/signup page."""
    try:
        with open("logo.png", "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        logo_b64 = None

    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    if logo_b64:
        st.markdown(
            f'<div class="login-logo"><img src="data:image/png;base64,{logo_b64}" width="320"/></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="login-title">mirra</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">Where patterns become awareness</div>', unsafe_allow_html=True)

    mode = st.radio("", ["Sign in", "Create account"], horizontal=True, label_visibility="collapsed", key="auth_mode")

    with st.container(border=True):
        username = st.text_input("Username", key="auth_user", placeholder="your username")
        password = st.text_input("Password", type="password", key="auth_pass", placeholder="••••••••")

        if mode == "Sign in":
            if st.button("Sign in", type="primary", use_container_width=True):
                handle_signin(supabase, username, password)
        else:
            if st.button("Create account", type="primary", use_container_width=True):
                handle_signup(supabase, username, password)


def handle_signin(supabase, username: str, password: str):
    """Handle user sign in."""
    if not username or not password:
        st.error("Please enter both username and password.")
    else:
        res = supabase.table("users").select("id,username,password_hash").eq("username", username.strip().lower()).execute()
        if not res.data:
            st.error("Username not found.")
        elif res.data[0]["password_hash"] != hash_pw(password):
            st.error("Incorrect password.")
        else:
            st.session_state["user_id"]   = res.data[0]["id"]
            st.session_state["username"]  = res.data[0]["username"]
            st.session_state["logged_in"] = True
            st.rerun()


def handle_signup(supabase, username: str, password: str):
    """Handle user account creation."""
    if not username or not password:
        st.error("Please fill in all fields.")
    elif len(password) < 6:
        st.error("Password must be at least 6 characters.")
    else:
        clean = username.strip().lower()
        existing = supabase.table("users").select("id").eq("username", clean).execute()
        if existing.data:
            st.error("Username already taken.")
        else:
            new_user = supabase.table("users").insert({
                "username": clean,
                "password_hash": hash_pw(password),
            }).execute()
            uid = new_user.data[0]["id"]
            st.session_state["user_id"]   = uid
            st.session_state["username"]  = clean
            st.session_state["logged_in"] = True
            st.rerun()


def render_logout_button():
    """Render the logout button."""
    with st.container():
        col_space, col_logout = st.columns([5, 1])
        with col_logout:
            if st.button("Sign out", key="logout"):
                for k in ["logged_in", "user_id", "username", "keywords",
                          "save_success", "dendro_results", "insight_report",
                          "has_seen_intro"]:
                    st.session_state.pop(k, None)
                st.cache_data.clear()
                st.rerun()
