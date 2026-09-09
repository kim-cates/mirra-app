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

Storage: answers accumulate in ``st.session_state[_DRAFT_KEY]`` as they are
typed, and ``collect_responses`` hands that dict to
``save_inquiry_responses``, which writes ``users.inquiry_responses`` (jsonb)
plus the ``users.inquiry_completed_at`` marker that stops the onboarding
chain from replaying on the next sign-in. The target table is still being
aligned with MIR-2's goals schema (issue #20); when it lands, the jsonb
column gets backfilled and these two functions are the only place to change.

Why a draft dict instead of just reading the widgets at save time: Streamlit
garbage-collects a widget's session_state entry once the widget stops being
rendered — one rerun of grace, then it is gone. This wizard shows one question
per page, so by the time "Save my answers" runs, every page except the last has
already been culled, and reading the widget keys yields empty strings. That is
exactly what used to reach the database: every answer blank, only the final
page's ``period`` intact. The widgets are the input surface; this dict is the
storage.
"""

from datetime import datetime, timezone

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

# Final step (Igor's note #2): after all questions, the user commits to their
# top priorities for a chosen period. When the period ends, the backend will
# trigger a new wave of the inquiry informed by the past month (future work —
# being designed with Kim; see for-kim/note-2-focus-cycle.md).
PRIORITY_LIMIT = 3
FOCUS_PERIODS = ["1 week", "2 weeks", "1 month"]

_STATE_KEY = "insight_inquiry_responses"
_STEP_KEY = "inquiry_step"
# Answers-so-far, outside widget state so Streamlit's widget cleanup can't take
# them (see the module docstring). Named with the "inquiry_" prefix so
# preview_inquiry.py's reset button clears it along with the widget keys.
_DRAFT_KEY = "inquiry_draft"
# Whether this session has passed the inquiry gate. Kept separate from
# _STATE_KEY: overloading the answers key as a completion flag is what used to
# turn "we could not read your answers" into "you have no answers".
_COMPLETED_KEY = "insight_inquiry_completed"


def _draft() -> dict:
    """The wizard's own copy of the answers, keyed outside widget state."""
    draft = st.session_state.get(_DRAFT_KEY)
    if not isinstance(draft, dict):
        draft = {}
        st.session_state[_DRAFT_KEY] = draft
    return draft


def _widget_keys(question_key: str) -> tuple[str, str, str]:
    """The (text, categories, focus) widget keys for one question."""
    return (
        f"inquiry_text_{question_key}",
        f"inquiry_cats_{question_key}",
        f"inquiry_focus_{question_key}",
    )


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
    """Per-question answers + the final priorities block, ready to save.

    Reads the draft, never the widgets: at save time only the last page's
    widgets still exist.
    """
    draft = _draft()
    responses = {}
    for q in INQUIRY_QUESTIONS:
        answer = draft.get(q["key"]) or {}
        selected = list(answer.get("categories", []))
        focus = answer.get("focus", [])
        responses[q["key"]] = {
            "text": (answer.get("text") or "").strip(),
            "categories": selected,
            "focus": [f for f in focus if f in selected][:FOCUS_LIMIT],
        }
    priorities = draft.get("_priorities") or {}
    responses["_priorities"] = {
        "top": list(priorities.get("top", []))[:PRIORITY_LIMIT],
        "period": priorities.get("period", FOCUS_PERIODS[-1]),
    }
    return responses


def _all_selected_categories() -> list[str]:
    """Union of everything the user picked, focus selections first.

    From the draft, not the widgets — the priorities page is the last step, so
    every question's widgets are gone by then. Reading them is why this list
    used to come up empty however much the user had selected, leaving the
    priorities multiselect with no options to offer.
    """
    draft = _draft()
    picked: list[str] = []
    for field in ("focus", "categories"):
        for q in INQUIRY_QUESTIONS:
            for item in (draft.get(q["key"]) or {}).get(field, []):
                if item not in picked:
                    picked.append(item)
    return picked


def save_inquiry_responses(supabase, user_id: str, responses: dict) -> bool:
    """Persist inquiry responses. Returns True if they reached the database.

    Interim storage (#43 ↔ #20): writes users.inquiry_responses (jsonb) +
    users.inquiry_completed_at until Kim's user_goals schema (#20) lands —
    then this becomes per-row inserts and the jsonb column gets backfilled
    and dropped. Session state is the pre-migration fallback.
    """
    st.session_state[_STATE_KEY] = responses
    st.session_state[_COMPLETED_KEY] = True
    if supabase is None:
        return False
    try:
        res = supabase.table("users").update({
            "inquiry_responses": responses,
            "inquiry_completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()
    except Exception:
        return False  # pre-migration — session fallback keeps the flow working
    # An UPDATE matching no row is a 200 with an empty body, not an error, so
    # RLS filtering the row out is indistinguishable from success unless we look
    # at what came back. postgrest-py asks for the updated representation by
    # default, so an empty list means nothing was written.
    return bool(getattr(res, "data", None))


def mark_inquiry_completed(supabase, user_id: str) -> None:
    """Record that the user passed the inquiry screen (e.g. skipped it)."""
    st.session_state[_COMPLETED_KEY] = True
    if supabase is None:
        return
    try:
        supabase.table("users").update(
            {"inquiry_completed_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", user_id).execute()
    except Exception:
        pass  # pre-migration — the session marker above still closes the gate


def load_inquiry_responses(supabase, user_id: str) -> dict:
    """Read saved inquiry answers ({} if none / pre-migration)."""
    if supabase is not None:
        try:
            res = (supabase.table("users").select("inquiry_responses")
                   .eq("id", user_id).limit(1).execute())
            if res.data and res.data[0].get("inquiry_responses"):
                return res.data[0]["inquiry_responses"]
        except Exception:
            pass
    return dict(st.session_state.get(_STATE_KEY) or {})


def user_has_completed_inquiry(supabase, user_id: str) -> bool:
    """True once the user submitted (or skipped) the inquiry.

    Reads users.inquiry_completed_at, with session state as the
    pre-migration fallback.
    """
    if st.session_state.get(_COMPLETED_KEY):
        return True
    if st.session_state.get(_STATE_KEY) is not None:
        return True
    if supabase is not None:
        try:
            res = (supabase.table("users").select("inquiry_completed_at")
                   .eq("id", user_id).limit(1).execute())
            if res.data and res.data[0].get("inquiry_completed_at"):
                # Only the completion flag. This used to write
                # `_STATE_KEY = {}`, which made load_inquiry_responses fall back
                # to an empty dict — reporting "you have not answered" whenever
                # the answers themselves could not be read.
                st.session_state[_COMPLETED_KEY] = True
                return True
        except Exception:
            pass
    return False


def _render_question(q: dict) -> None:
    """One question page: open text → suggestive categories → focus pick."""
    draft = _draft()
    saved = draft.get(q["key"]) or {}
    text_key, cats_key, focus_key = _widget_keys(q["key"])
    # Re-seed the widgets from the draft, because revisiting this page (Back, or
    # a retake from the Profile tab) starts from culled widget state.
    # setdefault, not assignment: on the run right after the user typed, the
    # widget entry still exists and is the fresher value of the two.
    st.session_state.setdefault(text_key, saved.get("text", "") or "")
    st.session_state.setdefault(cats_key, list(saved.get("categories", [])))
    st.session_state.setdefault(focus_key, list(saved.get("focus", []))[:FOCUS_LIMIT])

    with st.container(border=True):
        st.markdown(f"**{q['prompt']}**")

        # Step 1 — open-ended response (~200-300 words)
        st.text_area(
            "In your own words",
            key=text_key,
            placeholder=OPEN_ENDED_HINT,
            height=140,
            label_visibility="collapsed",
        )

        # Step 2 — categories (suggestive: selection surfaces related ones)
        selected = list(st.session_state.get(cats_key) or [])
        st.multiselect(
            "Categories",
            options=category_options(q, selected),
            key=cats_key,
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
                key=focus_key,
                max_selections=FOCUS_LIMIT,
                placeholder=f"Pick up to {FOCUS_LIMIT}…",
                label_visibility="collapsed",
            )

    # Mirror this page into the draft. Nothing culls the draft, so this is what
    # survives to the save step.
    chosen = list(st.session_state.get(cats_key) or [])
    focus = [f for f in (st.session_state.get(focus_key) or []) if f in chosen]
    draft[q["key"]] = {
        "text": (st.session_state.get(text_key) or "").strip(),
        "categories": chosen,
        "focus": focus[:FOCUS_LIMIT],
    }


def _render_priorities_page() -> None:
    """Final page: commit to top priorities for the next period (note #2)."""
    draft = _draft()
    saved = draft.get("_priorities") or {}
    picked = _all_selected_categories()
    # Seeded rather than passed as `index=`/`default=` so a revisit keeps what
    # the user chose. Priorities are filtered to what is still selected, because
    # a stale value outside `options` makes st.multiselect raise.
    st.session_state.setdefault(
        "inquiry_priorities",
        [p for p in saved.get("top", []) if p in picked][:PRIORITY_LIMIT],
    )
    st.session_state.setdefault("inquiry_period",
                                saved.get("period", FOCUS_PERIODS[-1]))

    with st.container(border=True):
        st.markdown("**What do you want to focus on next?**")
        if picked:
            st.caption(
                f"Out of everything you selected, choose your top {PRIORITY_LIMIT} "
                "priorities for the period ahead."
            )
            st.multiselect(
                "Top priorities",
                options=picked,
                key="inquiry_priorities",
                max_selections=PRIORITY_LIMIT,
                placeholder=f"Pick up to {PRIORITY_LIMIT}…",
                label_visibility="collapsed",
            )
        else:
            st.caption("You haven't selected any categories — you can go back, "
                       "or just save your written answers.")
        st.radio(
            "For how long?",
            options=FOCUS_PERIODS,
            key="inquiry_period",
            horizontal=True,
        )
        st.caption(
            "When this period ends, Mirra will check in with a fresh round of "
            "questions — informed by your past weeks."
        )

    draft["_priorities"] = {
        "top": list(st.session_state.get("inquiry_priorities") or [])[:PRIORITY_LIMIT],
        "period": st.session_state.get("inquiry_period") or FOCUS_PERIODS[-1],
    }


def seed_widget_state(responses: dict) -> None:
    """Prefill the wizard from saved answers (used when retaking).

    Loads the draft and drops any leftover widget entries so each page re-seeds
    from it. Without the clear, a stale widget value from an earlier visit would
    win over the answers just loaded from the database.
    """
    draft: dict = {}
    for q in INQUIRY_QUESTIONS:
        answer = (responses or {}).get(q["key"]) or {}
        draft[q["key"]] = {
            "text": answer.get("text", "") or "",
            "categories": list(answer.get("categories", [])),
            "focus": list(answer.get("focus", [])),
        }
        for key in _widget_keys(q["key"]):
            st.session_state.pop(key, None)
    priorities = (responses or {}).get("_priorities") or {}
    draft["_priorities"] = {
        "top": list(priorities.get("top", [])),
        "period": priorities.get("period", FOCUS_PERIODS[-1]),
    }
    st.session_state.pop("inquiry_priorities", None)
    st.session_state.pop("inquiry_period", None)
    st.session_state[_DRAFT_KEY] = draft


def render_insight_inquiry(supabase, user_id: str, on_complete=None,
                           mode: str = "create") -> None:
    """Render the survey as a wizard — one question per page + a focus page.

    mode="create" is the onboarding gate (skippable); mode="edit" is retaking
    it later from the Profile tab.
    """
    step = st.session_state.get(_STEP_KEY, 0)
    total = len(INQUIRY_QUESTIONS) + 1  # questions + final priorities page

    if mode == "create":
        st.markdown("### Tell Mirra what matters to you")
    if step < len(INQUIRY_QUESTIONS):
        st.caption(f"Question {step + 1} of {len(INQUIRY_QUESTIONS)} — answer in "
                   "your own words, pick categories, or both. Everything is optional.")
    else:
        st.caption("Last step — set your focus.")
    st.progress((step + 1) / total)

    if step < len(INQUIRY_QUESTIONS):
        _render_question(INQUIRY_QUESTIONS[step])
    else:
        _render_priorities_page()

    back_col, next_col = st.columns(2)
    with back_col:
        if step > 0 and st.button("← Back", use_container_width=True):
            st.session_state[_STEP_KEY] = step - 1
            st.rerun()
    with next_col:
        if step < total - 1:
            if st.button("Next →", type="primary", use_container_width=True):
                st.session_state[_STEP_KEY] = step + 1
                st.rerun()
        else:
            if st.button("Save my answers", type="primary", use_container_width=True):
                saved = save_inquiry_responses(supabase, user_id, collect_responses())
                st.session_state.pop(_STEP_KEY, None)
                # The answers now live in _STATE_KEY (and the database when the
                # write landed). Leaving the draft would let it shadow a later
                # retake seeded from the database.
                st.session_state.pop(_DRAFT_KEY, None)
                if not saved:
                    # Reached when the UPDATE raised, or matched no row. Don't
                    # name a cause we haven't established — the column does
                    # exist in production, so the likelier reasons are a lost
                    # sign-in (RLS matches nothing without a session) or a
                    # project missing the migration.
                    st.warning(
                        "Your answers are held for this session but could not be "
                        "written to the database. Try signing out and back in; if "
                        "it keeps happening the users table may be missing the "
                        "inquiry columns."
                    )
                if on_complete:
                    on_complete()
                st.rerun()

    # Onboarding is optional: closing the gate without answers beats trapping
    # a returning user behind a survey they already skipped once.
    if mode == "create":
        if st.button("Skip for now", key="inquiry_skip"):
            mark_inquiry_completed(supabase, user_id)
            st.session_state.pop(_STEP_KEY, None)
            st.rerun()
