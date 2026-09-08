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

from typing import Optional

import streamlit as st
import streamlit.components.v1 as components

import providers
from providers import oauth_state, registry, token_store
from providers.base import (
    ConnectionState,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)
from providers.local_store import choose_backend

_BACKFILL_DAYS = 30


# ── secrets helpers ───────────────────────────────────────────────────────────
def _enc_key() -> str:
    return st.secrets.get("TOKEN_ENC_KEY", "")


def _db(supabase):
    """
    Where connections/provider rows are written. Production → the real Supabase
    client passed in. Demo (`CONNECTIONS_BACKEND="local"` in secrets) → a
    file-backed local store, so we never touch the prod schema while demoing.
    """
    return choose_backend(supabase, st.secrets)


def _is_local_demo() -> bool:
    return (st.secrets.get("CONNECTIONS_BACKEND") or "").lower() == "local"


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

    supabase = _db(supabase)  # prod Supabase, or local demo store
    provider_key, _, nonce = state.partition(":")

    # Validate the CSRF nonce against the PERSISTED store, not st.session_state:
    # the vendor redirect starts a fresh Streamlit session, so session state is
    # already gone by the time we get here. consume() is single-use + expiring.
    issued_for = oauth_state.consume(supabase, nonce=nonce, provider=provider_key)
    if not issued_for:
        st.error("Connection failed: security check (state) did not match or expired. Please retry.")
        st.query_params.clear()
        return
    # Bind the callback to the user the nonce was issued for.
    user_id = issued_for

    try:
        provider = _build(provider_key)
        bundle = provider.exchange_code(code=code)
        token_store.save_oauth(supabase, user_id, provider_key, bundle, enc_key=_enc_key())
    except ProviderError as e:
        st.error(f"Couldn't connect {provider_key.title()}: {e}")
        st.session_state.pop(f"_oauth_nonce_{provider_key}", None)
        st.query_params.clear()
        return

    # The credential is saved from here on, so a failing backfill must not read
    # as a failed connection — say so, and leave the manual Sync buttons to
    # retry (render_sync_section).
    label = provider.meta.label
    try:
        with st.spinner(f"Connected! Backfilling {_BACKFILL_DAYS} days from {label}…"):
            n = provider.sync(supabase=supabase, user_id=user_id,
                              access_token=bundle.access_token, days_back=_BACKFILL_DAYS)
        st.success(f"{label} connected ✓ — {n} day(s) of data synced.")
    except NotImplementedError:
        # Provider connected but its sync() is still a skeleton — that's fine,
        # the credential is saved; data will flow once sync lands.
        st.info(f"{label} connected. Data sync coming soon.")
    except ProviderError as e:
        st.warning(f"{label} connected, but the initial backfill failed: {e}")
    except Exception as e:  # storage/schema errors must not blank the whole app
        st.warning(f"{label} connected, but the initial backfill couldn't be saved: {e}")
    finally:
        # The nonce is spent (single-use); drop the cached copy so the next
        # render mints a fresh one for Reconnect.
        st.session_state.pop(f"_oauth_nonce_{provider_key}", None)
        st.query_params.clear()


# ── Page ──────────────────────────────────────────────────────────────────────
def render_connections_page(supabase, user_id: str) -> None:
    """Render one card per registered provider with connect/disconnect controls."""
    st.markdown('<div class="section-label">Connections</div>', unsafe_allow_html=True)
    supabase = _db(supabase)  # prod Supabase, or local demo store
    if _is_local_demo():
        st.caption("🧪 Demo mode — connections stored locally (encrypted), not in Supabase.")

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
                _start_connect(supabase, user_id, meta.key)
        elif state == ConnectionState.NEEDS_REAUTH:
            if st.button("Reconnect", key=f"reconnect_{meta.key}"):
                _start_connect(supabase, user_id, meta.key)
        else:  # CONNECTED
            if st.button("Disconnect", key=f"disconnect_{meta.key}"):
                _disconnect(supabase, user_id, meta.key)


def _state_labels(state: ConnectionState) -> tuple[str, str]:
    return {
        ConnectionState.CONNECTED: ("connected", "🟢 Connected"),
        ConnectionState.NEEDS_REAUTH: ("needs_reauth", "🟡 Needs reauth"),
        ConnectionState.NOT_CONNECTED: ("not_connected", "⚪ Not connected"),
    }[state]


def _start_connect(db, user_id: str, provider_key: str) -> None:
    """Mint a CSRF nonce, persist it, and send the user to the vendor."""
    try:
        provider = _build(provider_key)
    except ProviderError as e:
        st.error(str(e))
        return
    oauth_state.sweep(db)  # opportunistic cleanup of expired nonces
    nonce = oauth_state.issue(db, provider=provider_key, user_id=user_id)
    url = provider.authorize_url(state=f"{provider_key}:{nonce}")
    # Streamlit renders markdown inside a sandboxed iframe, so a <meta refresh>
    # can't navigate the top window reliably. Give the user an explicit link
    # (honest "you're leaving to <vendor>" UX) and try a top-window JS hop as a
    # convenience.
    st.link_button(f"Continue to {provider.meta.label} →", url, type="primary")
    components.html(
        f"<script>try{{window.top.location.href={url!r};}}catch(e){{}}</script>",
        height=0,
    )


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


# ── Connected-provider controls (sync / reconnect / disconnect) ──────────────
# The mirror of oura_ui's Oura panel, but provider-driven: any registered
# provider whose meta declares a `data_table` gets the same affordances, so
# "Sync last 30 days" is not a thing only Oura users have.
def render_sync_section(supabase, user_id: str, provider_key: str,
                        *, day_options: tuple[int, ...] = (7, _BACKFILL_DAYS)) -> None:
    """Render backfill/reconnect/disconnect controls for one connected provider.

    Renders nothing when the provider isn't configured, isn't connected, or has
    no normalized table to write into — the Connections card above already tells
    that story, and this section would be an empty shell.

    Like `provider_card`, it never raises: a missing `connections` table degrades
    to silence rather than taking the Connections tab down.
    """
    try:
        meta = registry.meta_for(provider_key)
    except ProviderError:
        return
    if not meta.data_table or provider_key not in set(registry.configured_keys(st.secrets)):
        return

    db = _db(supabase)
    try:
        state = token_store.connection_state(db, user_id, provider_key)
    except Exception:
        return
    if state == ConnectionState.NOT_CONNECTED:
        return

    st.markdown(f'<div class="section-label">{meta.label}</div>', unsafe_allow_html=True)

    if state == ConnectionState.NEEDS_REAUTH:
        st.warning(f"{meta.label} needs to be reconnected before it can sync again.")
    else:
        st.markdown(
            f'<div class="save-msg">&check; {meta.label} connected via OAuth.</div>',
            unsafe_allow_html=True,
        )

    n_days = _stored_day_count(db, user_id, meta.data_table)
    if n_days is not None:
        st.markdown(
            f'<div style="color:#888; font-size:0.9rem; margin:0.6rem 0 1rem">'
            f'{n_days} days of {meta.label} data stored.</div>',
            unsafe_allow_html=True,
        )

    cols = st.columns(len(day_options) + 2)
    for col, days in zip(cols, day_options):
        with col:
            if st.button(f"Sync last {days} days", key=f"sync_{provider_key}_{days}",
                         use_container_width=True):
                _do_sync(db, user_id, provider_key, days_back=days)
    with cols[-2]:
        if st.button("Reconnect", key=f"sync_reconnect_{provider_key}",
                     use_container_width=True):
            _start_connect(db, user_id, provider_key)
    with cols[-1]:
        if st.button("Disconnect", key=f"sync_disconnect_{provider_key}",
                     use_container_width=True):
            _disconnect(db, user_id, provider_key)

    if provider_key == "spotify":
        # Be honest about the ceiling rather than letting a 3-row result read as
        # a bug: Spotify only hands back roughly the last 50 plays, so a 30-day
        # button fills in whatever of that window still exists. History accrues
        # by syncing regularly.
        st.caption(
            "Spotify only returns your ~50 most recent plays, so a 30-day sync "
            "covers as much of that window as Spotify still has. Sync regularly "
            "to build history."
        )


def _stored_day_count(db, user_id: str, table: str) -> Optional[int]:
    """How many daily rows this user has in `table`, or None if unreadable."""
    try:
        res = db.table(table).select("entry_date").eq("user_id", user_id).execute()
    except Exception:
        return None
    return len(res.data or [])


def _do_sync(db, user_id: str, provider_key: str, *, days_back: int) -> None:
    """Refresh the token if needed, pull `days_back` days, report what landed."""
    try:
        provider = _build(provider_key)
    except ProviderError as e:
        st.error(str(e))
        return

    label = provider.meta.label
    try:
        token = token_store.get_valid_token(db, provider, user_id, enc_key=_enc_key())
        if not token:
            st.error(f"No stored {label} credential — connect first.")
            return
        with st.spinner(f"Syncing {days_back} days from {label}…"):
            n = provider.sync(supabase=db, user_id=user_id,
                              access_token=token, days_back=days_back)
    except ProviderAuthError:
        # get_valid_token/sync already flagged the connection as needs_reauth.
        st.error(f"{label} access expired. Use Reconnect to authorize again.")
        return
    except ProviderRateLimitError:
        st.warning(f"{label} rate limit hit. Try again in a few minutes.")
        return
    except NotImplementedError:
        st.info(f"{label} sync isn't available yet.")
        return
    except ProviderError as e:
        st.error(f"Sync failed: {e}")
        return
    except Exception as e:  # storage/schema problems shouldn't blank the tab
        st.error(f"Sync failed while saving: {e}")
        return

    if n:
        st.success(f"Synced {n} day(s) of {label} data ✓")
    else:
        st.info(f"No new {label} activity in the last {days_back} days.")
    st.cache_data.clear()


# ── Adapter for the existing Connections tab in app.py ───────────────────────
# app.py renders a list of {name, description, status, action_url, action_label}
# cards. This returns that dict for any registered provider, so a card can be
# swapped from a "Coming soon" placeholder to a live connection with one call.
#
# It NEVER raises: if secrets are missing or the `connections`/`oauth_states`
# tables aren't migrated yet, the card degrades to "Not configured" rather than
# taking the whole tab down. That matters because this ships before the
# migration is applied.
def _short_error(e: Exception) -> str:
    """
    One readable line for a card. Keeps the useful part of a PostgREST error
    (e.g. 'new row violates row-level security policy') without dumping a raw
    payload into the UI.
    """
    msg = str(e).strip().replace("\n", " ")
    low = msg.lower()
    if "row-level security" in low or "violates row level security" in low:
        return "database rejected the write (row-level security)"
    if "does not exist" in low or "not found" in low:
        return "table missing — run the migration"
    if "permission denied" in low:
        return "permission denied on the table"
    return (msg[:110] + "…") if len(msg) > 110 else (msg or type(e).__name__)


def provider_card(supabase, user_id: str, provider_key: str, *,
                  description: str = "") -> dict:
    """Build one app-card dict for `provider_key`, degrading safely on error."""
    meta = registry.meta_for(provider_key)
    card = {
        "name": meta.label,
        "description": description or f"Connect {meta.label}.",
        "status": "Not configured",
        "action_url": None,
        "action_label": "Connect",
    }

    if not st.secrets.get(f"{provider_key.upper()}_CLIENT_ID"):
        return card  # no credentials yet → stays a placeholder

    # Checked up front: without it the connect flow gets past the button and then
    # dies inside crypto.encrypt, which is a much harder failure to read.
    if not st.secrets.get("TOKEN_ENC_KEY"):
        card["status"] = "Setup required — TOKEN_ENC_KEY missing from secrets"
        return card

    db = _db(supabase)
    try:
        connected = token_store.connection_state(db, user_id, provider_key)
    except Exception as e:
        # Say WHY. A silent "Setup required" hides permission errors (RLS
        # rejecting the write) behind what looks like unfinished configuration —
        # that cost us a long debugging session once already.
        card["status"] = f"Setup required — {_short_error(e)}"
        return card

    # Streamlit re-runs this on every interaction, so reuse one nonce per session
    # instead of writing a fresh row each render. A lost session just mints a new
    # one; the orphan expires (10 min TTL) and gets swept.
    sess_key = f"_oauth_nonce_{provider_key}"
    try:
        provider = _build(provider_key)
        nonce = st.session_state.get(sess_key)
        if not nonce:
            oauth_state.sweep(db)
            nonce = oauth_state.issue(db, provider=provider_key, user_id=user_id)
            st.session_state[sess_key] = nonce
        card["action_url"] = provider.authorize_url(state=f"{provider_key}:{nonce}")
    except ProviderError as e:
        card["status"] = f"Not configured — {_short_error(e)}"
        return card
    except Exception as e:
        # Most likely the oauth_states insert being refused (RLS), which is a
        # permissions problem, not a missing migration. Name it.
        card["status"] = f"Setup required — {_short_error(e)}"
        return card

    if connected == ConnectionState.CONNECTED:
        card["status"] = "Connected"
        card["action_label"] = "Reconnect"
    elif connected == ConnectionState.NEEDS_REAUTH:
        card["status"] = "Needs reauth"
        card["action_label"] = "Reconnect"
    else:
        card["status"] = "Ready to connect"
    return card
