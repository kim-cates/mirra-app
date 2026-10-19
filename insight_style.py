"""Insight style — how the user wants their insights delivered.

Three settings, one axis: how much of the evidence to show versus how much of
the interpretation.

  • data-driven     — numbers first. Charts, tables, sample sizes, model scores;
                      interpretation kept to a minimum.
  • hybrid          — both: a plain-language takeaway, then the evidence behind
                      it. This is the default, and what the app did before the
                      setting existed.
  • insight-focused — takeaways first, in plain language. The supporting tables
                      and charts are still there, tucked into expanders.

Storage: ``users.insight_style`` (text, see docs/migrations/personalization.sql).
Session state is the pre-migration fallback, same pattern as insight_inquiry:
the choice still applies for the session even if the write can't land.
"""

import streamlit as st

DATA_DRIVEN = "data_driven"
HYBRID = "hybrid"
INSIGHT_FOCUSED = "insight_focused"

STYLES = [DATA_DRIVEN, HYBRID, INSIGHT_FOCUSED]
DEFAULT_STYLE = HYBRID

LABELS = {
    DATA_DRIVEN: "Data-driven",
    HYBRID: "Hybrid",
    INSIGHT_FOCUSED: "Insight-focused",
}

DESCRIPTIONS = {
    DATA_DRIVEN: "Lead with the numbers — charts, tables, averages and sample "
                 "sizes, with as little interpretation as possible.",
    HYBRID: "A plain-language takeaway, followed by the data that backs it up.",
    INSIGHT_FOCUSED: "Lead with what it means for you, in plain language. The "
                     "underlying numbers stay one click away.",
}

# Appended to LLM prompts so the generated reports follow the same setting.
PROMPT_GUIDANCE = {
    DATA_DRIVEN: (
        "The user prefers DATA-DRIVEN insights. Lead every section with the "
        "concrete numbers — averages, dates, counts, correlation coefficients "
        "and sample sizes. Keep interpretation brief and literal, avoid "
        "metaphor and encouragement, and prefer a compact, factual tone."
    ),
    HYBRID: (
        "The user prefers a HYBRID of data and insight. Open each section with "
        "a plain-language takeaway, then support it with the specific numbers "
        "(values, dates, correlations) that justify it. Sound like a "
        "perceptive friend, not a clinical report."
    ),
    INSIGHT_FOCUSED: (
        "The user prefers INSIGHT-FOCUSED reflections. Lead with what the "
        "patterns mean for them and how it might feel, in warm, plain "
        "language. Use numbers sparingly — only where a single figure makes "
        "the point clearer — and never list statistics."
    ),
}

_STATE_KEY = "insight_style"


def normalize(value) -> str:
    """Any stored value → a known style, falling back to the default."""
    return value if value in STYLES else DEFAULT_STYLE


def load_insight_style(supabase, user_id: str) -> str:
    """The user's saved style, or the default if unset / pre-migration."""
    if _STATE_KEY in st.session_state:
        return normalize(st.session_state[_STATE_KEY])
    style = None
    if supabase is not None:
        try:
            res = (supabase.table("users").select("insight_style")
                   .eq("id", user_id).limit(1).execute())
            if res.data:
                style = res.data[0].get("insight_style")
        except Exception:
            pass  # column not migrated yet — default below
    style = normalize(style)
    st.session_state[_STATE_KEY] = style
    return style


def save_insight_style(supabase, user_id: str, style: str) -> bool:
    """Persist the style. Returns True if it reached the database."""
    style = normalize(style)
    st.session_state[_STATE_KEY] = style
    if supabase is None:
        return False
    try:
        res = (supabase.table("users").update({"insight_style": style})
               .eq("id", user_id).execute())
    except Exception:
        return False
    # An UPDATE that RLS filters out returns 200 with no rows (see
    # insight_inquiry.save_inquiry_responses), so check what came back.
    return bool(getattr(res, "data", None))


def prompt_guidance(style: str) -> str:
    return PROMPT_GUIDANCE[normalize(style)]


# ── Widgets ──────────────────────────────────────────────────────────────────
# The same setting has several controls: the radio in Profile → Personalization
# (saved by that tab's "Save changes" button) and the toggles at the top of
# Simples and Personalized Insights (saved on click). All are on screen in one
# run (tabs render every panel), so whichever one saves writes the new value
# into the others' widget state too. Otherwise a stale one would still show the
# old style. That write has to happen in a callback: once a widget has rendered
# in a run, Streamlit refuses changes to its state.
_PICKER_KEY = "insight_style_picker"
# One toggle per page that has one; each needs its own widget key.
_TOGGLE_PAGES = ("simples", "pi")
_WIDGET_KEYS = (_PICKER_KEY,) + tuple(f"insight_style_toggle_{p}" for p in _TOGGLE_PAGES)
_FAILED_KEY = "insight_style_save_failed"


def _apply(source_key: str, supabase, user_id: str) -> bool:
    """Save the style held by one control and mirror it into the other."""
    choice = st.session_state.get(source_key)
    if choice not in STYLES:
        # A segmented control can be clicked off. Keep the style as it was.
        choice = normalize(st.session_state.get(_STATE_KEY))
    saved = save_insight_style(supabase, user_id, choice)
    st.session_state[_FAILED_KEY] = not saved
    for key in _WIDGET_KEYS:
        st.session_state[key] = choice
    return saved


def _on_widget_change(source_key: str, supabase, user_id: str) -> None:
    _apply(source_key, supabase, user_id)


def save_from_picker(supabase, user_id: str) -> bool:
    """For the Profile form's submit callback. True if it reached the database."""
    return _apply(_PICKER_KEY, supabase, user_id)


def _bind(key: str, supabase, user_id: str) -> dict:
    """Seed the widget from the saved style, then wire up the shared callback.

    Seeded through session state, not `index=`/`default=`, because the callback
    also writes this key, and Streamlit rejects a widget that sets both.
    """
    st.session_state.setdefault(key, load_insight_style(supabase, user_id))
    return dict(key=key, on_change=_on_widget_change, args=(key, supabase, user_id))


def _render_save_warning() -> None:
    if st.session_state.get(_FAILED_KEY):
        st.warning(
            "Your choice applies for this session but couldn't be saved. "
            "The users table may be missing the insight_style column — "
            "see docs/migrations/personalization.sql."
        )


def render_style_field(supabase, user_id: str) -> None:
    """The setting as it appears in the Profile → Personalization form.

    Only renders the field; the form's "Save changes" button saves it via
    save_from_picker. No on_change: widgets inside a form can't have one.
    """
    st.session_state.setdefault(_PICKER_KEY, load_insight_style(supabase, user_id))
    st.markdown("**How should Mirra present your insights?**")
    st.radio(
        "Insight style",
        options=STYLES,
        format_func=lambda s: LABELS[s],
        captions=[DESCRIPTIONS[s] for s in STYLES],
        key=_PICKER_KEY,
        label_visibility="collapsed",
    )


def render_style_toggle(supabase, user_id: str, where: str = "simples") -> str:
    """Compact switcher for the top of a page. Returns the style in effect.

    `where` names the page (one of _TOGGLE_PAGES) so two pages' toggles, both
    rendered in the same run, don't collide on a widget key.
    """
    st.segmented_control(
        "Insight style",
        options=STYLES,
        format_func=lambda s: LABELS[s],
        label_visibility="collapsed",
        **_bind(f"insight_style_toggle_{where}", supabase, user_id),
    )
    _render_save_warning()
    return load_insight_style(supabase, user_id)
