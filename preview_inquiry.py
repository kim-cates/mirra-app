"""Standalone visual preview of the insight inquiry (MIR-1 #43).

Runs the survey UI without Supabase/secrets so the founders can iterate on
the visual design:  streamlit run preview_inquiry.py
Not part of the app flow — dev tool only.
"""

import json

import streamlit as st

from config import configure_page, apply_styling
from insight_inquiry import render_insight_inquiry, _STATE_KEY as INQUIRY_KEY
from profile_form import render_profile_form, _STATE_KEY as PROFILE_KEY

# The app's real design system (config.py) — these screens inherit it in
# app.py, so the preview must render with the exact same styling.
configure_page()
apply_styling()

st.markdown("## mirra")
view = st.radio(
    "Preview screen",
    ["Insight inquiry (#43)", "Profile form (#16)", "Profile Settings (#18)"],
    horizontal=True,
    label_visibility="collapsed",
)
st.caption("Preview only — not wired to the database")

if view.startswith("Insight"):
    render_insight_inquiry(supabase=None, user_id="preview-user")
    captured = st.session_state.get(INQUIRY_KEY)
elif view.startswith("Profile form"):
    render_profile_form(supabase=None, user_id="preview-user", mode="create")
    captured = st.session_state.get(PROFILE_KEY)
else:
    render_profile_form(supabase=None, user_id="preview-user", mode="edit")
    captured = st.session_state.get(PROFILE_KEY)

if captured:
    st.divider()
    st.markdown("**Captured payload** (what will be saved to the DB):")
    st.code(json.dumps(captured, indent=2, ensure_ascii=False), language="json")
    if st.button("Reset preview"):
        for key in (INQUIRY_KEY, PROFILE_KEY):
            st.session_state.pop(key, None)
        for k in list(st.session_state.keys()):
            if str(k).startswith(("inquiry_", "profile_")):
                st.session_state.pop(k, None)
        st.rerun()
