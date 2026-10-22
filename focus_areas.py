"""Focus areas — which parts of their record a user wants Mirra to lead with.

Today there are three: sleep, stress and mood. Each maps onto columns that
insights_data.load_daily_frame already builds, so adding an area later is one
entry in FOCUS_AREAS once the data for it exists.

Stress has no direct measurement in Mirra. Its area is made of the signals that
move with it — HRV and resting heart rate from Oura, plus the intensity of the
hard feelings (stressed, anxious, overwhelmed…) the user logs — and the label
says so wherever it is shown.

Storage: ``users.focus_areas`` (text[], see docs/migrations/personalization.sql)
with session state as the pre-migration fallback, as in insight_style.py. An
empty or missing value means "not chosen yet", and default_areas() fills in
from the inquiry priorities, then from whatever data the user has.
"""

import pandas as pd
import streamlit as st

SLEEP = "sleep"
STRESS = "stress"
MOOD = "mood"

# key → (label, columns in the daily frame, source hint for an empty state)
FOCUS_AREAS = {
    SLEEP:  ("Sleep",  ("sleep_hours", "sleep_score"), "Connect Oura"),
    STRESS: ("Stress", ("hrv_avg", "resting_hr", "feel_negative"),
             "Connect Oura, or log feelings with your reflections"),
    MOOD:   ("Mood",   ("mood", "feel_positive"), "Write a few reflections"),
}
AREA_KEYS = list(FOCUS_AREAS)

AREA_NOTES = {
    STRESS: "Mirra doesn't measure stress directly. This area follows the "
            "signals that move with it: HRV, resting heart rate, and how "
            "strongly you logged hard feelings.",
}

# Words in a free-text inquiry priority that point at an area.
_PRIORITY_CUES = {
    SLEEP: ("sleep", "wind-down", "wake", "late night", "rest"),
    STRESS: ("stress", "anxi", "overwhelm", "mindful", "recovery", "calm"),
    MOOD: ("mood", "emotion", "feel", "happi", "depress"),
}

_STATE_KEY = "focus_areas"
_WIDGET_KEY = "focus_areas_picker"


def label(area: str) -> str:
    return FOCUS_AREAS[area][0]


def columns_for(areas: list[str]) -> list[str]:
    """Columns for these areas, in area order, without repeats."""
    out: list[str] = []
    for area in areas:
        for col in FOCUS_AREAS[area][1]:
            if col not in out:
                out.append(col)
    return out


def normalize(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [a for a in AREA_KEYS if a in value]


def days_with_data(df: pd.DataFrame, area: str) -> int:
    """Days on which at least one of the area's columns has a reading."""
    cols = [c for c in FOCUS_AREAS[area][1] if c in df.columns]
    if df.empty or not cols:
        return 0
    return int(df[cols].notna().any(axis=1).sum())


def default_areas(priorities: list[str], df: pd.DataFrame) -> list[str]:
    """Areas the user hinted at in the inquiry, else the ones they have data for."""
    text = " ".join(priorities).lower()
    hinted = [a for a in AREA_KEYS if any(cue in text for cue in _PRIORITY_CUES[a])]
    if hinted:
        return hinted
    with_data = [a for a in AREA_KEYS if days_with_data(df, a) > 0]
    return with_data or list(AREA_KEYS)


def load_saved_areas(supabase, user_id: str) -> list[str]:
    """What the user explicitly chose ([] if nothing yet / pre-migration)."""
    if _STATE_KEY in st.session_state:
        return normalize(st.session_state[_STATE_KEY])
    areas: list[str] = []
    if supabase is not None:
        try:
            res = (supabase.table("users").select("focus_areas")
                   .eq("id", user_id).limit(1).execute())
            if res.data:
                areas = normalize(res.data[0].get("focus_areas"))
        except Exception:
            pass  # column not migrated yet
    st.session_state[_STATE_KEY] = areas
    return areas


def load_focus_areas(supabase, user_id: str, priorities: list[str],
                     df: pd.DataFrame) -> list[str]:
    """The areas to lead with: the saved choice, or a sensible default."""
    return load_saved_areas(supabase, user_id) or default_areas(priorities, df)


def save_focus_areas(supabase, user_id: str, areas: list[str]) -> bool:
    areas = normalize(areas)
    st.session_state[_STATE_KEY] = areas
    if supabase is None:
        return False
    try:
        res = (supabase.table("users").update({"focus_areas": areas})
               .eq("id", user_id).execute())
    except Exception:
        return False
    return bool(getattr(res, "data", None))


def save_from_picker(supabase, user_id: str) -> bool:
    """For the Profile form's submit callback. True if it reached the database."""
    return save_focus_areas(supabase, user_id,
                            normalize(st.session_state.get(_WIDGET_KEY)))


def render_focus_field(supabase, user_id: str, priorities: list[str],
                       df: pd.DataFrame) -> None:
    """The areas field in the Profile → Personalization form, with what data
    backs each one. Saved by the form's "Save changes" via save_from_picker."""
    st.session_state.setdefault(
        _WIDGET_KEY, load_focus_areas(supabase, user_id, priorities, df))
    st.markdown("**What do you want to focus on?**")
    st.caption("Simples leads with these. More areas will be added as Mirra "
               "learns to read more of your data.")
    st.multiselect(
        "Focus areas",
        options=AREA_KEYS,
        format_func=label,
        key=_WIDGET_KEY,
        placeholder="Pick one or more…",
        label_visibility="collapsed",
    )
    lines = []
    for area in AREA_KEYS:
        n = days_with_data(df, area)
        status = (f"{n} day{'s' if n != 1 else ''} of data" if n
                  else f"no data yet — {FOCUS_AREAS[area][2].lower()}")
        lines.append(f"**{label(area)}** · {status}")
    st.caption("  \n".join(lines))
    st.caption(AREA_NOTES[STRESS])
    if not load_saved_areas(supabase, user_id):
        st.caption("Nothing saved yet, so Mirra is using your insight answers "
                   "and the data you have to pick for you.")
