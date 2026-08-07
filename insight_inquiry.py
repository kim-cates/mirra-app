"""User insight inquiry — onboarding survey (MIR-1, sub-issue #43).

Four questions from the story, each captured BOTH ways (per Kim's note):
open-ended text + selectable categories. Questions and categories live in
config lists below so founders can add/reword them without touching logic.

Storage: answers are collected into a plain dict and handed to
``save_inquiry_responses``. The target table is still being aligned with
MIR-2's goals schema (issue #20) — until that lands, responses are stored on
``st.session_state`` and the save seam is the single place to wire the DB in.
"""

import streamlit as st

# ── Survey configuration (edit freely — order defines display order) ─────────
# Each question: key (stable id for storage), prompt, category options.
INQUIRY_QUESTIONS = [
    {
        "key": "improve",
        "prompt": "What habits do you want to improve?",
        "categories": [
            "Improve sleep",
            "Manage stress",
            "Time management",
            "Long-term planning",
            "Schedule organization",
        ],
    },
    {
        "key": "decrease",
        "prompt": "What habits do you want to decrease?",
        "categories": [
            "Doomscrolling / screen time",
            "Procrastination",
            "Overcommitting",
            "Late nights",
            "Stress eating",
        ],
    },
    {
        "key": "long_term_goals",
        "prompt": "What are your long-term goals?",
        "categories": [
            "Career growth",
            "Health & fitness",
            "Relationships",
            "Financial stability",
            "Creative projects",
        ],
    },
    {
        "key": "distractions",
        "prompt": (
            "What compulsions or habitual tendencies do you find distract "
            "from staying on track from these goals?"
        ),
        "categories": [
            "Social media",
            "Multitasking",
            "Perfectionism",
            "Saying yes to everything",
            "Irregular routine",
        ],
    },
]

_STATE_KEY = "insight_inquiry_responses"


def collect_responses() -> dict:
    """Read the current widget values into {key: {"text": str, "categories": [str]}}."""
    responses = {}
    for q in INQUIRY_QUESTIONS:
        responses[q["key"]] = {
            "text": st.session_state.get(f"inquiry_text_{q['key']}", "").strip(),
            "categories": st.session_state.get(f"inquiry_cats_{q['key']}", []),
        }
    return responses


def save_inquiry_responses(supabase, user_id: str, responses: dict) -> None:
    """Persist inquiry responses.

    DB seam (issue #43 ↔ #20): the goals/inquiry table is being aligned with
    Kim's MIR-2 schema (user_goals). Until that lands we keep responses in
    session state so the rest of the app can already read them; swapping this
    body for a Supabase upsert is the only change needed later.
    """
    st.session_state[_STATE_KEY] = responses


def user_has_completed_inquiry(user_id: str) -> bool:
    """True once the user submitted the inquiry (session-scoped for now)."""
    return bool(st.session_state.get(_STATE_KEY))


def render_insight_inquiry(supabase, user_id: str, on_complete=None) -> None:
    """Render the 4-question survey. Calls ``on_complete()`` after saving."""
    st.markdown("### Tell Mirra what matters to you")
    st.caption(
        "Answer in your own words, pick the categories that fit — or both. "
        "Everything is optional; you can change these later."
    )

    for q in INQUIRY_QUESTIONS:
        with st.container(border=True):
            st.markdown(f"**{q['prompt']}**")
            st.text_area(
                "In your own words",
                key=f"inquiry_text_{q['key']}",
                placeholder="2–3 sentences…",
                label_visibility="collapsed",
            )
            st.multiselect(
                "Categories",
                options=q["categories"],
                key=f"inquiry_cats_{q['key']}",
                placeholder="Select categories…",
                label_visibility="collapsed",
            )

    if st.button("Save my answers", type="primary", use_container_width=True):
        save_inquiry_responses(supabase, user_id, collect_responses())
        st.success("Saved — Mirra will use this to personalize your insights.")
        if on_complete:
            on_complete()
        st.rerun()
