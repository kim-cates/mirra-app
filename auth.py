"""Authentication for Mirra — sign in / create account.

Identity lives in the custom `public.users` table (username + SHA256 password
hash), not Supabase Auth — see the identity note in migrations.sql before
adding per-user tables.

This module is the single implementation of the auth surface: app.py imports
`render_login_page`, `render_logout_button` and `hash_pw` from here.

Sign in and Create account are two explicit modes, and they must stay
distinct: signing in returns you to the app you already set up, while
creating an account is the only path that starts onboarding. The onboarding
gates themselves read completion markers from the database (see
profile_form.user_has_completed_profile), so a returning user is never asked
the onboarding questions twice.
"""

import base64
import hashlib
import re

import streamlit as st

MIN_PASSWORD_LENGTH = 6
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")


def hash_pw(password: str) -> str:
    """Hash a password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def _logo_base64() -> str | None:
    try:
        with open("logo.png", "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return None


def _start_session(user_id: str, username: str, *, new_account: bool) -> None:
    st.session_state["user_id"] = user_id
    st.session_state["username"] = username
    st.session_state["logged_in"] = True
    # Onboarding is driven by database markers; this only tells the app which
    # copy to show on the first screen after a brand-new sign-up.
    st.session_state["new_account"] = new_account
    st.rerun()


# ── Pages ─────────────────────────────────────────────────────────────────────
def render_login_page(supabase) -> None:
    """Render the signed-out screen: Sign in | Create account."""
    logo_b64 = _logo_base64()

    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    if logo_b64:
        st.markdown(
            f'<div class="login-logo"><img src="data:image/png;base64,{logo_b64}" width="320"/></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="login-title">mirra</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">Where patterns become awareness</div>', unsafe_allow_html=True)

    # A keyed radio (not st.tabs) because tabs reset to the first tab on every
    # rerun — an error raised by the second tab's button would never be seen.
    mode = st.radio(
        "Account", ["Sign in", "Create account"],
        horizontal=True, label_visibility="collapsed", key="auth_mode",
    )

    if mode == "Sign in":
        _render_signin(supabase)
    else:
        _render_signup(supabase)


def _render_signin(supabase) -> None:
    with st.container(border=True):
        with st.form("signin_form", border=False):
            username = st.text_input("Username", key="signin_user", placeholder="your username")
            password = st.text_input("Password", key="signin_pass", type="password",
                                     placeholder="••••••••")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            handle_signin(supabase, username, password)
    st.caption("New to Mirra? Switch to **Create account** above.")


def _render_signup(supabase) -> None:
    with st.container(border=True):
        with st.form("signup_form", border=False):
            username = st.text_input("Username", key="signup_user", placeholder="pick a username")
            password = st.text_input("Password", key="signup_pass", type="password",
                                     placeholder=f"at least {MIN_PASSWORD_LENGTH} characters")
            confirm = st.text_input("Confirm password", key="signup_confirm", type="password",
                                    placeholder="repeat your password")
            submitted = st.form_submit_button("Create account", type="primary",
                                              use_container_width=True)
        if submitted:
            handle_signup(supabase, username, password, confirm)
    st.caption("Already have an account? Switch to **Sign in** above.")


# ── Handlers ──────────────────────────────────────────────────────────────────
def handle_signin(supabase, username: str, password: str) -> None:
    """Verify credentials and open a session."""
    if not username or not password:
        st.error("Please enter both username and password.")
        return

    clean = username.strip().lower()
    try:
        res = (supabase.table("users").select("id,username,password_hash")
               .eq("username", clean).limit(1).execute())
    except Exception:
        st.error("Couldn't reach the database. Please try again in a moment.")
        return

    # One generic message for both failure modes so the form can't be used to
    # find out which usernames exist.
    if not res.data or res.data[0]["password_hash"] != hash_pw(password):
        st.error("Incorrect username or password.")
        return

    _start_session(res.data[0]["id"], res.data[0]["username"], new_account=False)


def handle_signup(supabase, username: str, password: str, confirm: str = None) -> None:
    """Create an account and open a session."""
    clean = (username or "").strip().lower()

    if not clean or not password:
        st.error("Please fill in all fields.")
        return
    if not USERNAME_PATTERN.match(clean):
        st.error("Username must be 3–32 characters: letters, numbers, dot, dash or underscore.")
        return
    if len(password) < MIN_PASSWORD_LENGTH:
        st.error(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return
    if confirm is not None and password != confirm:
        st.error("The two passwords don't match.")
        return

    try:
        existing = supabase.table("users").select("id").eq("username", clean).limit(1).execute()
        if existing.data:
            st.error("That username is taken. Try another one — or sign in instead.")
            return
        new_user = supabase.table("users").insert({
            "username": clean,
            "password_hash": hash_pw(password),
        }).execute()
    except Exception:
        st.error("Couldn't create the account right now. Please try again in a moment.")
        return

    _start_session(new_user.data[0]["id"], clean, new_account=True)


def change_password(supabase, user_id: str, current: str, new: str,
                    confirm: str) -> tuple[bool, str]:
    """Change the signed-in user's password. Returns (ok, message)."""
    if not current or not new:
        return False, "Please fill in both your current and new password."
    if len(new) < MIN_PASSWORD_LENGTH:
        return False, f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    if new != confirm:
        return False, "The two new passwords don't match."
    if new == current:
        return False, "That's your current password — pick a new one."

    try:
        res = (supabase.table("users").select("password_hash")
               .eq("id", user_id).limit(1).execute())
        if not res.data or res.data[0]["password_hash"] != hash_pw(current):
            return False, "Your current password isn't right."
        supabase.table("users").update(
            {"password_hash": hash_pw(new)}
        ).eq("id", user_id).execute()
    except Exception:
        return False, "Couldn't reach the database. Please try again in a moment."

    return True, "Password updated."


def sign_out() -> None:
    """Drop the whole session so nothing leaks into the next account."""
    st.session_state.clear()
    st.cache_data.clear()
    st.rerun()


def render_logout_button() -> None:
    """Render the top-right sign-out button."""
    with st.container():
        _, col_logout = st.columns([5, 1])
        with col_logout:
            if st.button("Sign out", key="logout"):
                sign_out()
