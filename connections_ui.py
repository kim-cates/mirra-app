"""
MIR-3 · Connections page — issue #29 (skeleton).

A single page that lists every registered provider as Connected / Not connected /
Needs reauth, with one-click connect and disconnect. It is fully provider-driven:
it iterates `providers.registry`, so a new connector appears here automatically.

This generalizes `oura_ui.handle_oauth_callback` / `render_settings_tab` into a
vendor-agnostic flow. It is NOT yet wired into app.py — wiring waits on the
`connections` table migration (#27) and Kim's review. Kept here so the UX and the
CSRF-safe callback are reviewable next to the interface.

CSRF: `state` is `"<provider_key>:<nonce>"`. The nonce is stashed in session per
provider and re-checked on callback; a mismatch aborts (AC: "Callback handler
validates state parameter").
"""
from __future__ import annotations

import secrets as _secrets
from typing import Optional

import streamlit as st

import providers
from providers import registry, token_store
from providers.base import ConnectionState, ProviderError

_STATE_SESSION_PREFIX = "oauth_state_"   # session key per provider
_BACKFILL_DAYS = 30


# ── secrets helpers ───────────────────────────────────────────────────────────
def _enc_key() -> str:
    return st.secrets.get("TOKEN_ENC_KEY", "")


def _build(provider_key: str):
    """Build a provider from st.secrets, surfacing config errors to the UI."""
    return registry.build_from_secrets(provider_key, st.secrets)


# ── OAuth callback (call once at top of app, after login) ─────────────────────
def handle_oauth_callback(supabase, user_id: str) -> None:
    """
    Generalized callback handler. Reads ?code & ?state, routes to the provider
    named in `state`, validates the nonce, exchanges the code, persists tokens,
    and kicks off an initial backfill.
    """
    qp = st.query_params
    code = qp.get("code")
    state = qp.get("state")
    if not code or not state or ":" not in state:
        return

    provider_key, _, nonce = state.partition(":")
    expected = st.session_state.get(_STATE_SESSION_PREFIX + provider_key)
    if not expected or nonce != expected:
        st.error("Connection failed: security check (state) did not match. Please retry.")
        st.query_params.clear()
        return

    try:
        provider = _build(provider_key)
        bundle = provider.exchange_code(code=code)
        token_store.save_oauth(supabase, user_id, provider_key, bundle, enc_key=_enc_key())
        with st.spinner(f"Connected! Backfilling {_BACKFILL_DAYS} days from {provider.meta.label}…"):
            provider.sync(supabase=supabase, user_id=user_id,
                          access_token=bundle.access_token, days_back=_BACKFILL_DAYS)
    except NotImplementedError:
        # Provider connected but its sync() is still a skeleton — that's fine,
        # the credential is saved; data will flow once sync lands.
        st.info(f"{provider_key.title()} connected. Data sync coming soon.")
    except ProviderError as e:
        st.error(f"Couldn't connect {provider_key.title()}: {e}")
    finally:
        st.session_state.pop(_STATE_SESSION_PREFIX + provider_key, None)
        st.query_params.clear()


# ── Page ──────────────────────────────────────────────────────────────────────
def render_connections_page(supabase, user_id: str) -> None:
    """Render one card per registered provider with connect/disconnect controls."""
    st.markdown('<div class="section-label">Connections</div>', unsafe_allow_html=True)

    configured = set(registry.configured_keys(st.secrets))
    for meta in registry.all_meta():
        state = token_store.connection_state(supabase, user_id, meta.key)
        _render_provider_card(supabase, user_id, meta, state,
                              is_configured=meta.key in configured)


def _render_provider_card(supabase, user_id: str, meta, state: ConnectionState,
                          *, is_configured: bool) -> None:
    label, badge = _state_labels(state)
    cols = st.columns([0.6, 0.4])
    with cols[0]:
        st.markdown(f"**{meta.icon} {meta.label}** — {badge}")
    with cols[1]:
        if not is_configured:
            st.caption("Coming soon")
            return
        if state == ConnectionState.NOT_CONNECTED:
            if st.button("Connect", key=f"connect_{meta.key}"):
                _start_connect(meta.key)
        elif state == ConnectionState.NEEDS_REAUTH:
            if st.button("Reconnect", key=f"reconnect_{meta.key}"):
                _start_connect(meta.key)
        else:  # CONNECTED
            if st.button("Disconnect", key=f"disconnect_{meta.key}"):
                _disconnect(supabase, user_id, meta.key)


def _state_labels(state: ConnectionState) -> tuple[str, str]:
    return {
        ConnectionState.CONNECTED: ("connected", "🟢 Connected"),
        ConnectionState.NEEDS_REAUTH: ("needs_reauth", "🟡 Needs reauth"),
        ConnectionState.NOT_CONNECTED: ("not_connected", "⚪ Not connected"),
    }[state]


def _start_connect(provider_key: str) -> None:
    """Mint a CSRF nonce, stash it in session, and redirect to the vendor."""
    try:
        provider = _build(provider_key)
    except ProviderError as e:
        st.error(str(e))
        return
    nonce = _secrets.token_urlsafe(24)
    st.session_state[_STATE_SESSION_PREFIX + provider_key] = nonce
    url = provider.authorize_url(state=f"{provider_key}:{nonce}")
    # Redirect the top window to the provider's consent screen.
    st.markdown(f'<meta http-equiv="refresh" content="0;url={url}">', unsafe_allow_html=True)
    st.link_button(f"Continue to {provider.meta.label} →", url)


def _disconnect(supabase, user_id: str, provider_key: str) -> None:
    try:
        provider = _build(provider_key)
        conn = token_store.load_connection(supabase, user_id, provider_key, enc_key=_enc_key())
        if conn and conn.auth_type.value == "oauth":
            provider.revoke(access_token=conn.access_token, refresh_token=conn.refresh_token)
    except ProviderError:
        pass  # best-effort revoke; we drop the local credential regardless
    token_store.delete_connection(supabase, user_id, provider_key)
    st.rerun()
