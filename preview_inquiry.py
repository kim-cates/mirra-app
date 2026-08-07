"""Standalone visual preview of the insight inquiry (MIR-1 #43).

Runs the survey UI without Supabase/secrets so the founders can iterate on
the visual design:  streamlit run preview_inquiry.py
Not part of the app flow — dev tool only.
"""

import json

import streamlit as st

from config import configure_page, apply_styling
from insight_inquiry import render_insight_inquiry, _STATE_KEY

# The app's real design system (config.py) — the quiz inherits it in app.py,
# so the preview must render with the exact same styling, not custom CSS.
configure_page()
apply_styling()

st.markdown("## mirra")
st.caption("Preview: onboarding insight inquiry (#43) — not wired to the database")

render_insight_inquiry(supabase=None, user_id="preview-user")

if st.session_state.get(_STATE_KEY):
    st.divider()
    st.markdown("**Captured payload** (what will be saved to the DB):")
    st.code(json.dumps(st.session_state[_STATE_KEY], indent=2, ensure_ascii=False), language="json")
    if st.button("Reset preview"):
        st.session_state.pop(_STATE_KEY, None)
        for k in list(st.session_state.keys()):
            if str(k).startswith("inquiry_"):
                st.session_state.pop(k, None)
        st.rerun()
