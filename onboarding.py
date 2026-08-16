"""Onboarding gate policy (MIR-1).

The chain is login → intro → profile → inquiry → app, and each screen is
supposed to appear once per account. "Once" needs somewhere to remember it:
the marker columns on `users` (has_seen_intro, profile_completed_at,
inquiry_completed_at) added by the MIR-1 block in migrations.sql.

Until that migration is applied to a given Supabase project there is nowhere
to write "done", so completion would reset on every sign-in and returning
users would be walked through onboarding again and again. Rather than
trapping them, we fall back to a narrower rule: only accounts created in this
session are walked through the chain; everyone else goes straight into the
app and can fill in their profile from the Profile tab.

Once the migration lands, `markers_available` flips to True and the markers
take over — including for people who abandoned onboarding halfway.
"""

import streamlit as st

_AVAILABLE_KEY = "onboarding_markers_available"


def markers_available(supabase) -> bool:
    """True if the users table can persist onboarding completion.

    Probed once per session — the answer only changes when a migration runs.
    """
    if _AVAILABLE_KEY in st.session_state:
        return st.session_state[_AVAILABLE_KEY]

    available = False
    if supabase is not None:
        try:
            supabase.table("users").select(
                "has_seen_intro,profile_completed_at,inquiry_completed_at"
            ).limit(1).execute()
            available = True
        except Exception:
            available = False  # migration not applied on this project yet

    st.session_state[_AVAILABLE_KEY] = available
    return available


def should_run_onboarding(supabase) -> bool:
    """Whether the onboarding gates apply to the current session."""
    return markers_available(supabase) or bool(st.session_state.get("new_account"))
