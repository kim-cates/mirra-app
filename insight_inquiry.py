"""User insight inquiry — onboarding survey (MIR-1, sub-issue #43).

Flow per question (Igor's note #1, building on Kim's #43 design):
  1. Open-ended response — a text box, ~200-300 words.
  2. The same question with selectable categories. Categories are SUGGESTIVE:
     picking one can surface related ones (e.g. "Improve sleep" suggests
     "Evening wind-down routine"; time organization ties into productivity).
  3. Follow-up: "Out of these categories, which 2-3 do you want to focus on
     right now?" — options are what the user just selected, capped at 3.
  4. Question wording is a draft — Kim corrects it once the schema is sent.

Questions, categories and suggestion links live in config lists below so the
founders can add/reword them without touching logic.

Storage: answers are collected into a plain dict and handed to
``save_inquiry_responses``. The target table is being aligned with MIR-2's
goals schema (issue #20) — until that lands, responses live in
``st.session_state`` and the save seam is the single place to wire the DB in.
"""

import streamlit as st

# ── Survey configuration (edit freely — order defines display order) ─────────
# Each question: key (stable id for storage), prompt, base categories.
# ``suggests`` maps a category → related categories that appear as options
# once it is selected (suggestive categories, step 2 of the flow).
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
        "suggests": {
            "Improve sleep": ["Evening wind-down routine", "Consistent wake time"],
            "Time management": ["Productivity", "Prioritizing deep work"],
            "Manage stress": ["Mindfulness practice", "Recovery time"],
            "Schedule organization": ["Weekly planning ritual"],
        },
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
        "suggests": {
            "Doomscrolling / screen time": ["Phone-free mornings", "App time limits"],
            "Late nights": ["Evening wind-down routine"],
            "Overcommitting": ["Saying no more often"],
        },
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
        "suggests": {
            "Career growth": ["Skill building", "Portfolio / side projects"],
            "Health & fitness": ["Consistent training", "Nutrition"],
            "Financial stability": ["Saving routine", "Passive income"],
        },
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
        "suggests": {
            "Social media": ["Notification overload"],
            "Multitasking": ["Context switching"],
            "Irregular routine": ["Inconsistent sleep schedule"],
        },
    },
]

FOCUS_LIMIT = 3          # step 3: pick up to this many categories to focus on
OPEN_ENDED_HINT = "Write 2–3 sentences (around 200–300 words max)…"

_STATE_KEY = "insight_inquiry_responses"


def category_options(question: dict, selected: list[str]) -> list[str]:
    """Base categories plus suggestions triggered by the current selection.

    Selected values always stay in the list (Streamlit requires it), and each
    selected category surfaces its related suggestions as new options.
    """
    options = list(question["categories"])
    for cat in selected:
        if cat not in options:
            options.append(cat)
        for suggestion in question.get("suggests", {}).get(cat, []):
            if suggestion not in options:
                options.append(suggestion)
    return options


def collect_responses() -> dict:
    """Read widget values → {key: {"text", "categories", "focus"}}."""
    responses = {}
    for q in INQUIRY_QUESTIONS:
        selected = st.session_state.get(f"inquiry_cats_{q['key']}", [])
        focus = st.session_state.get(f"inquiry_focus_{q['key']}", [])
        responses[q["key"]] = {
            "text": st.session_state.get(f"inquiry_text_{q['key']}", "").strip(),
            "categories": selected,
            "focus": [f for f in focus if f in selected][:FOCUS_LIMIT],
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
    """Render the survey. Calls ``on_complete()`` after saving."""
    st.markdown("### Tell Mirra what matters to you")
    st.caption(
        "Answer in your own words, pick the categories that fit — or both. "
        "Everything is optional; you can change these later."
    )

    for q in INQUIRY_QUESTIONS:
        with st.container(border=True):
            st.markdown(f"**{q['prompt']}**")

            # Step 1 — open-ended response (~200-300 words)
            st.text_area(
                "In your own words",
                key=f"inquiry_text_{q['key']}",
                placeholder=OPEN_ENDED_HINT,
                height=120,
                label_visibility="collapsed",
            )

            # Step 2 — categories (suggestive: selection surfaces related ones)
            selected = st.session_state.get(f"inquiry_cats_{q['key']}", [])
            st.multiselect(
                "Categories",
                options=category_options(q, selected),
                key=f"inquiry_cats_{q['key']}",
                placeholder="Select categories…",
                label_visibility="collapsed",
            )
            newly_suggested = [
                s
                for cat in selected
                for s in q.get("suggests", {}).get(cat, [])
                if s not in selected
            ]
            if newly_suggested:
                st.caption("Suggested for you: " + " · ".join(dict.fromkeys(newly_suggested)))

            # Step 3 — focus follow-up (2-3 out of the selected categories)
            if len(selected) > 1:
                st.markdown(
                    f"<small>Out of these, which {min(FOCUS_LIMIT, len(selected))} "
                    "do you want to focus on right now?</small>",
                    unsafe_allow_html=True,
                )
                st.multiselect(
                    "Focus now",
                    options=selected,
                    key=f"inquiry_focus_{q['key']}",
                    max_selections=FOCUS_LIMIT,
                    placeholder=f"Pick up to {FOCUS_LIMIT}…",
                    label_visibility="collapsed",
                )

    if st.button("Save my answers", type="primary", use_container_width=True):
        save_inquiry_responses(supabase, user_id, collect_responses())
        st.success("Saved — Mirra will use this to personalize your insights.")
        if on_complete:
            on_complete()
        st.rerun()
