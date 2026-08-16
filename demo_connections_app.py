"""
MIR-3 · Standalone Connections demo — run the real OAuth cycle against a real
provider account, without touching production data.

    streamlit run demo_connections_app.py --server.port 8501

Why a separate entry point instead of the full app: `app.py` needs a Mirra login
(which would mean writing a test user into Kim's Supabase) and loads the whole
NLP stack. This page renders the *same* `connections_ui` code the app tab uses,
with a fixed demo user id and the local file store, so nothing is written to
Supabase at all.

Requires in .streamlit/secrets.toml:
    SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
    OAUTH_REDIRECT_URI   (must match the app's redirect exactly)
    TOKEN_ENC_KEY
    CONNECTIONS_BACKEND = "local"
"""
from __future__ import annotations

import json
import os

import streamlit as st

import connections_ui
from providers import registry
from providers.local_store import choose_backend

# Fixed pseudo-user so the demo is reproducible. In the real app this is
# st.session_state["user_id"] from public.users.
DEMO_USER_ID = "00000000-0000-0000-0000-0000000000de"

st.set_page_config(page_title="Mirra · Connections demo", layout="centered")
st.title("Mirra — Connections (MIR-3 demo)")
st.caption("Same `connections_ui` code as the app's Connections tab. "
           "Storage is a local encrypted file — Supabase is never touched.")

if (st.secrets.get("CONNECTIONS_BACKEND") or "").lower() != "local":
    st.error("Set CONNECTIONS_BACKEND = \"local\" in secrets.toml before demoing.")
    st.stop()

store = choose_backend(None, st.secrets)

# 1) OAuth callback must run before anything renders.
connections_ui.handle_oauth_callback(None, DEMO_USER_ID)

# 2) The actual page under test.
connections_ui.render_connections_page(None, DEMO_USER_ID)

st.divider()

# ── Proof panel: what actually landed on disk ────────────────────────────────
st.subheader("What's stored (proof)")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**`connections` rows** — tokens encrypted at rest")
    rows = store.dump("connections")
    if not rows:
        st.info("No connections yet.")
    for r in rows:
        st.json({
            "provider": r.get("provider"),
            "status": r.get("status"),
            "auth_type": r.get("auth_type"),
            "access_token": (r.get("access_token") or "")[:28] + "…",
            "refresh_token": (r.get("refresh_token") or "")[:28] + "…",
            "token_expires_at": r.get("token_expires_at"),
            "scopes": r.get("scopes"),
        })

with col2:
    st.markdown("**`spotify_daily` rows** — synced listening data")
    days = sorted(store.dump("spotify_daily"), key=lambda r: r.get("entry_date", ""))
    if not days:
        st.info("No data yet — connect Spotify.")
    for r in days:
        st.write(
            f"**{r.get('entry_date')}** · plays {r.get('track_count')} · "
            f"artists {r.get('unique_artists')} · "
            f"{round((r.get('listening_ms') or 0)/60000)} min"
            + (f" · valence {r.get('valence')}" if r.get("valence") is not None else "")
        )

with st.expander("Manual sync / debug"):
    key = st.selectbox("Provider", registry.available_keys())
    if st.button("Sync now"):
        from providers import token_store
        provider = registry.build_from_secrets(key, st.secrets)
        tok = token_store.get_valid_token(store, provider, DEMO_USER_ID,
                                          enc_key=st.secrets["TOKEN_ENC_KEY"])
        if not tok:
            st.warning("Not connected.")
        else:
            n = provider.sync(supabase=store, user_id=DEMO_USER_ID,
                              access_token=tok, days_back=7)
            st.success(f"Synced {n} day-rows.")
            st.rerun()
    st.caption(f"Store file: `{st.secrets.get('CONNECTIONS_LOCAL_PATH')}`")
