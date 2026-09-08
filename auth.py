"""Authentication for Mirra — sign in / create account, backed by Supabase Auth.

Identity is Supabase Auth (`auth.users`). `public.users` is a profile table whose
primary key IS the auth id, so `st.session_state["user_id"]` still holds the id
every other module already uses — intro_page, profile_form, insight_inquiry and
the MIR-3 provider tables need no changes.

Why this replaced the custom login: the app talks to Supabase with the anon key,
which by design reaches the browser. While identity lived in a custom table,
`auth.uid()` was null, RLS could not be enabled, and that key could read every
user's rows. With Supabase Auth, RLS finally has an identity to match on.

Things worth knowing:

  * **Sign-in is by email, not username.** Supabase Auth keys on email. The
    username is kept as a display name in user metadata and on the profile row.
  * **Each Streamlit session needs its OWN Supabase client.** A client cached
    with @st.cache_resource is shared across all users of the deployment, so
    storing one user's auth session on it would hand that session to everyone
    else. `get_client()` therefore keeps a per-session client in session_state.
  * **Links in Supabase emails land on the project's Site URL** (confirmation,
    password reset). Streamlit can't read the `#access_token` fragment those
    links carry, so a confirmation link only brings the user back to this login
    screen — they then sign in normally. `APP_URL` (secrets, defaulting to the
    hosted app) must be in the project's Redirect URL allow-list or Supabase
    silently falls back to the Site URL.
  * **The profile row.** With "Confirm email" on, sign-up returns no session, so
    the app can't write `public.users` at that moment (RLS needs auth.uid()).
    The `on_auth_user_created` trigger in migrations.sql creates the row server-
    side; `_ensure_profile_row` at sign-in is the belt-and-braces fallback so a
    user whose row is missing is never walked through onboarding forever.

Sign in and Create account stay two explicit modes: signing in returns you to the
app you already set up, while creating an account is the only path that starts
onboarding. The onboarding gates read completion markers from the database, so a
returning user is never asked the onboarding questions twice.
"""

import base64
import re

import streamlit as st
from supabase import create_client

MIN_PASSWORD_LENGTH = 6
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_APP_URL = "https://mirra-reflections.streamlit.app"

_UNCONFIRMED_KEY = "auth_unconfirmed_email"


# ── Per-session client ────────────────────────────────────────────────────────
def get_client():
    """
    The Supabase client for THIS browser session, carrying this user's auth
    session. Never cache this globally — see the module docstring.
    """
    if "sb_client" not in st.session_state:
        st.session_state["sb_client"] = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        )
    return st.session_state["sb_client"]


def _app_url() -> str:
    """Where Supabase should send people back to from its emails."""
    try:
        return (st.secrets.get("APP_URL") or DEFAULT_APP_URL).rstrip("/")
    except Exception:  # no secrets file at all (bare local run)
        return DEFAULT_APP_URL


def _logo_base64() -> str | None:
    try:
        with open("logo.png", "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return None


def _start_session(user_id: str, username: str, email: str, *, new_account: bool) -> None:
    st.session_state["user_id"] = user_id
    st.session_state["username"] = username
    st.session_state["email"] = email  # change_password re-verifies against it
    st.session_state["logged_in"] = True
    # Onboarding is driven by database markers; this only tells the app which
    # copy to show on the first screen after a brand-new sign-up.
    st.session_state["new_account"] = new_account
    st.session_state.pop(_UNCONFIRMED_KEY, None)
    st.rerun()


def _display_name(user, fallback: str = "") -> str:
    meta = getattr(user, "user_metadata", None) or {}
    return meta.get("username") or (user.email or fallback).split("@")[0]


def auth_error_kind(exc: Exception) -> str:
    """
    Classify a Supabase Auth failure: 'unconfirmed' | 'exists' | 'rate_limit' | 'other'.

    supabase-py raises AuthApiError with a stable `code` on recent versions and
    only a message on older ones, so both are checked. Kept free of Streamlit so
    it can be unit-tested.
    """
    code = (getattr(exc, "code", None) or "").lower()
    msg = str(exc).lower()
    if code == "email_not_confirmed" or "not confirmed" in msg:
        return "unconfirmed"
    if code in ("user_already_exists", "email_exists") or "already" in msg or "registered" in msg:
        return "exists"
    if code.endswith("rate_limit") or "rate limit" in msg:
        return "rate_limit"
    return "other"


def _ensure_profile_row(client, user) -> None:
    """
    Make sure `public.users` has this user's row.

    Normally the database trigger creates it at sign-up. This covers accounts
    created before the trigger existed, or while "Confirm email" was on and the
    app had no session to write with. Without the row, every onboarding marker
    update silently matches nothing and the user re-enters onboarding forever.
    """
    try:
        existing = client.table("users").select("id").eq("id", user.id).limit(1).execute()
        if existing.data:
            return
        client.table("users").insert({
            "id": user.id,
            "username": _display_name(user),
            "email": user.email,
        }).execute()
    except Exception:
        pass  # the app still runs from session state; retried on next sign-in


# ── Pages ─────────────────────────────────────────────────────────────────────
def render_login_page(supabase=None) -> None:
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
        _render_signin()
    else:
        _render_signup()


def _render_signin() -> None:
    with st.container(border=True):
        with st.form("signin_form", border=False):
            email = st.text_input("Email", key="signin_email", placeholder="you@example.com")
            password = st.text_input("Password", key="signin_pass", type="password",
                                     placeholder="••••••••")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            handle_signin(email, password)
        _render_resend_confirmation()
        if st.button("Forgot password?", key="forgot_pw"):
            send_password_reset(st.session_state.get("signin_email", ""))
    st.caption("New to Mirra? Switch to **Create account** above.")


def _render_signup() -> None:
    with st.container(border=True):
        with st.form("signup_form", border=False):
            email = st.text_input("Email", key="signup_email", placeholder="you@example.com")
            username = st.text_input("Username", key="signup_user", placeholder="pick a username")
            password = st.text_input("Password", key="signup_pass", type="password",
                                     placeholder=f"at least {MIN_PASSWORD_LENGTH} characters")
            confirm = st.text_input("Confirm password", key="signup_confirm", type="password",
                                    placeholder="repeat your password")
            submitted = st.form_submit_button("Create account", type="primary",
                                              use_container_width=True)
        if submitted:
            handle_signup(email, username, password, confirm)
        _render_resend_confirmation()
    st.caption("Already have an account? Switch to **Sign in** above.")


def _render_resend_confirmation() -> None:
    """Offer a fresh confirmation email once we know an address is unconfirmed."""
    email = st.session_state.get(_UNCONFIRMED_KEY)
    if not email:
        return
    if st.button("Resend confirmation email", key=f"resend_{email}"):
        resend_confirmation(email)


# ── Handlers ──────────────────────────────────────────────────────────────────
def handle_signin(email: str, password: str) -> None:
    """Verify credentials against Supabase Auth and open a session."""
    email = (email or "").strip().lower()
    if not email or not password:
        st.error("Please enter both email and password.")
        return

    client = get_client()
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        # Supabase checks the password before the confirmation state, so this
        # branch is only reachable with the right password — it reveals nothing
        # to someone probing for accounts.
        if auth_error_kind(exc) == "unconfirmed":
            st.session_state[_UNCONFIRMED_KEY] = email
            st.warning("Your email isn't confirmed yet. Open the link we sent you, "
                       "then sign in again.")
            return
        # One generic message for everything else: never reveal whether an
        # account exists.
        st.error("Incorrect email or password.")
        return

    if not res or not res.user:
        st.error("Incorrect email or password.")
        return

    _ensure_profile_row(client, res.user)
    _start_session(res.user.id, _display_name(res.user), res.user.email or email,
                   new_account=False)


def handle_signup(email: str, username: str, password: str, confirm: str = None) -> None:
    """Create a Supabase Auth account plus its profile row, and open a session."""
    email = (email or "").strip().lower()
    clean = (username or "").strip().lower()

    if not email or not clean or not password:
        st.error("Please fill in all fields.")
        return
    if not EMAIL_PATTERN.match(email):
        st.error("That doesn't look like a valid email address.")
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

    client = get_client()
    try:
        res = client.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {"username": clean},
                # Must be in the project's Redirect URL allow-list, or Supabase
                # ignores it and uses the Site URL instead.
                "email_redirect_to": _app_url(),
            },
        })
    except Exception as exc:
        kind = auth_error_kind(exc)
        if kind == "exists":
            st.error("That email is already registered. Try signing in instead.")
        elif kind == "rate_limit":
            st.error("Too many sign-up emails just now. Please wait a minute and try again.")
        else:
            st.error("Couldn't create the account right now. Please try again in a moment.")
        return

    if not res or not res.user:
        st.error("Couldn't create the account right now. Please try again in a moment.")
        return

    # If the project requires email confirmation, there's no session yet — say so
    # rather than dropping the user on a blank screen. The profile row is created
    # by the database trigger; the app can't write it without a session.
    if not getattr(res, "session", None):
        st.session_state[_UNCONFIRMED_KEY] = email
        st.success("Account created. Open the confirmation link we just emailed you — "
                   "it brings you back here — then sign in.")
        return

    # Profile row: primary key IS the auth id (see MIR-56 migration). The trigger
    # normally beat us to it; the upsert just keeps username/email in sync.
    try:
        client.table("users").upsert(
            {"id": res.user.id, "username": clean, "email": email},
            on_conflict="id",
        ).execute()
    except Exception:
        # The account exists; _ensure_profile_row retries on the next sign-in,
        # so don't strand the user here.
        pass

    _start_session(res.user.id, clean, email, new_account=True)


def resend_confirmation(email: str) -> None:
    """Send the sign-up confirmation email again. Always reports success."""
    email = (email or "").strip().lower()
    if not EMAIL_PATTERN.match(email):
        st.error("Enter your email address above first.")
        return
    try:
        get_client().auth.resend({
            "type": "signup",
            "email": email,
            "options": {"email_redirect_to": _app_url()},
        })
    except Exception as exc:
        if auth_error_kind(exc) == "rate_limit":
            st.error("A confirmation email was sent very recently. Please wait a minute "
                     "before asking for another.")
            return
    st.success("If that email has an unconfirmed account, a new link is on its way.")


def send_password_reset(email: str) -> None:
    """Email a reset link. Always reports success so the form can't probe accounts."""
    email = (email or "").strip().lower()
    if not EMAIL_PATTERN.match(email):
        st.error("Enter your email address above first.")
        return
    try:
        get_client().auth.reset_password_email(email, {"redirect_to": _app_url()})
    except Exception:
        pass
    st.success("If that email has an account, a reset link is on its way.")


def change_password(supabase, user_id: str, current: str, new: str,
                    confirm: str) -> tuple[bool, str]:
    """
    Change the signed-in user's password. Returns (ok, message).

    `supabase` and `user_id` are kept in the signature for the existing caller in
    profile_tab; the operation itself acts on the current Supabase session.
    """
    if not current or not new:
        return False, "Please fill in both your current and new password."
    if len(new) < MIN_PASSWORD_LENGTH:
        return False, f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    if new != confirm:
        return False, "The two new passwords don't match."
    if new == current:
        return False, "That's your current password — pick a new one."

    client = get_client()
    email = st.session_state.get("email") or ""
    try:
        # Re-verify the current password before allowing a change.
        if email:
            client.auth.sign_in_with_password({"email": email, "password": current})
        client.auth.update_user({"password": new})
    except Exception:
        return False, "Your current password isn't right."

    return True, "Password updated."


def sign_out() -> None:
    """Drop the whole session so nothing leaks into the next account."""
    try:
        if "sb_client" in st.session_state:
            st.session_state["sb_client"].auth.sign_out()
    except Exception:
        pass
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
