"""Standalone visual preview of the insight inquiry (MIR-1 #43).

Runs the survey UI without Supabase/secrets so the founders can iterate on
the visual design:  streamlit run preview_inquiry.py
Not part of the app flow — dev tool only.
"""

import json

import streamlit as st

from insight_inquiry import render_insight_inquiry, _STATE_KEY

st.set_page_config(page_title="Mirra — inquiry preview", page_icon="🪞", layout="centered")

st.markdown(
    """
    <style>
      /* Mirra-ish look: cream background, sage accent (config.py palette) */
      .stApp { background-color: #faf9f5; }
      h1, h2, h3 { font-family: Georgia, 'Lora', serif; color: #2f3e34; }
      .stButton > button[kind="primary"] { background-color: #3dab7a; border: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

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
