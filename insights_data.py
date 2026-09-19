"""Shared per-day data layer for the Simples and Personalized Insights tabs.

One place that knows how Mirra's per-user daily tables in Supabase line up:

    reflections    entry_date, mood, content, keywords, feelings
    oura_daily     entry_date, sleep_score, readiness_score, activity_score,
                   total_sleep_seconds, hrv_avg, resting_hr, steps
    spotify_daily  entry_date, track_count, unique_artists, listening_ms,
                   valence, energy, tempo
    cycle_logs     entry_date — one row per logged period start. OPTIONAL and
                   new; see docs/migrations/cycle_logs.sql. Nothing else in the
                   schema carries cycle information, so until that table exists
                   the cycle lens has no input and says so.

Everything downstream works off `load_daily_frame()`: a date-indexed DataFrame
with one row per calendar day across the covered range — including days with no
data at all, so a gap in the record reads as a gap on the chart instead of
silently closing up.

Derived columns are marked in DERIVED_NOTES: they are computed here, not
measured by a device, and the UI labels them that way.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from config import PRESET_FEELINGS

# ── Feeling polarity ─────────────────────────────────────────────────────────
# PRESET_FEELINGS is an ordered spectrum in config.py (anxious → excited), but
# nothing there records which end is which. Clustering on "mood" needs that, so
# the split is stated once, here.
NEGATIVE_FEELINGS = {
    "anxious", "stressed", "overwhelmed", "depressed", "sad", "frustrated",
    "angry", "tired",
}
POSITIVE_FEELINGS = {
    "present", "calm", "relaxed", "content", "happy", "grateful", "energized",
    "focused", "excited",
}
# "neutral" deliberately belongs to neither.

# ── Productivity language cues ───────────────────────────────────────────────
# Mirra stores no productivity metric. The closest honest signal is the user's
# own words plus their self-reported "focused"/"energized" intensity, so
# `productivity` below is a PROXY and every surface that shows it says so.
PRODUCTIVE_TERMS = (
    "finished", "shipped", "completed", "accomplished", "productive", "progress",
    "launched", "built", "wrote", "cleared", "momentum", "tackled", "knocked out",
    "got through", "deep work", "focused", "crossed off", "made headway",
)
SCATTERED_TERMS = (
    "procrastinated", "procrastinating", "distracted", "stuck", "behind",
    "unfocused", "scattered", "wasted", "avoided", "spinning", "blocked",
    "couldn't focus", "nothing done", "fell behind", "put off",
)

DERIVED_NOTES = {
    "productivity": "Proxy — your self-reported focus plus language cues in your "
                    "reflections. Not a measured metric.",
    "cycle_phase": "Estimated from the period start dates you logged, using a "
                   "standard phase model. An approximation for spotting "
                   "patterns, not a medical calculation.",
    "sleep_hours": "oura_daily.total_sleep_seconds converted to hours.",
    "listening_minutes": "spotify_daily.listening_ms converted to minutes.",
}


# ── Loading ──────────────────────────────────────────────────────────────────
def _rows(supabase, table: str, user_id: str) -> list[dict]:
    """Every row of `table` for this user, or [] if the table isn't reachable.

    A missing table has to degrade rather than raise: cycle_logs is new and
    spotify_daily only exists once the MIR-3 migration has been applied, and
    neither should be able to take a whole tab down.
    """
    try:
        res = supabase.table(table).select("*").eq("user_id", user_id).execute()
    except Exception:
        return []
    return res.data or []


def table_available(supabase, table: str, user_id: str) -> bool:
    """Whether `table` can be read at all — used to explain an empty section."""
    try:
        supabase.table(table).select("entry_date").eq("user_id", user_id).limit(1).execute()
    except Exception:
        return False
    return True


@st.cache_data(ttl=60, show_spinner=False)
def load_daily_frame(_supabase, user_id: str) -> pd.DataFrame:
    """One row per calendar day, joining every per-user daily table.

    `_supabase` is underscore-prefixed so Streamlit skips hashing the client and
    caches on user_id alone — the same trick app.py's load_all_entries uses.
    """
    reflections = _rows(_supabase, "reflections", user_id)
    oura = _rows(_supabase, "oura_daily", user_id)
    spotify = _rows(_supabase, "spotify_daily", user_id)

    frames = []
    if reflections:
        frames.append(_reflection_frame(reflections))
    if oura:
        frames.append(_oura_frame(oura))
    if spotify:
        frames.append(_spotify_frame(spotify))
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, axis=1)
    df = df[~df.index.duplicated(keep="first")].sort_index()

    # Reindex across the full span so missing days are explicit NaN rows. Charts
    # then break the line at a gap instead of drawing straight through it.
    full = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full)
    df.index.name = "entry_date"
    return df


def _to_index(rows: list[dict]) -> pd.DatetimeIndex:
    return pd.to_datetime([r["entry_date"] for r in rows], errors="coerce")


def _reflection_frame(rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(index=_to_index(rows))
    out["mood"] = [_num(r.get("mood")) for r in rows]
    out["word_count"] = [len((r.get("content") or "").split()) for r in rows]
    out["keyword_count"] = [len(r.get("keywords") or []) for r in rows]

    pos, neg, n_feel, mean_int = [], [], [], []
    for r in rows:
        p, n, count, mean_i = _feeling_stats(r.get("feelings"))
        pos.append(p)
        neg.append(n)
        n_feel.append(count)
        mean_int.append(mean_i)
    out["feel_positive"] = pos
    out["feel_negative"] = neg
    out["feel_count"] = n_feel
    out["feel_intensity"] = mean_int

    out["productivity"] = [
        _productivity_proxy(r.get("content"), r.get("keywords"), r.get("feelings"))
        for r in rows
    ]
    return out[~out.index.isna()]


def _oura_frame(rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(index=_to_index(rows))
    for col in ("sleep_score", "readiness_score", "activity_score",
                "hrv_avg", "resting_hr", "steps"):
        out[col] = [_num(r.get(col)) for r in rows]
    secs = [_num(r.get("total_sleep_seconds")) for r in rows]
    out["sleep_hours"] = [None if s is None else s / 3600.0 for s in secs]
    return out[~out.index.isna()]


def _spotify_frame(rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(index=_to_index(rows))
    for col in ("track_count", "unique_artists", "valence", "energy", "tempo"):
        out[col] = [_num(r.get(col)) for r in rows]
    ms = [_num(r.get("listening_ms")) for r in rows]
    out["listening_minutes"] = [None if m is None else m / 60000.0 for m in ms]
    return out[~out.index.isna()]


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Derived signals ──────────────────────────────────────────────────────────
def _feeling_stats(feelings) -> tuple[Optional[float], Optional[float], int, Optional[float]]:
    """(positive intensity, negative intensity, count, mean intensity).

    Intensity is optional in the stored format — `{"name": "calm",
    "intensity": null}` is a valid entry meaning "felt it, didn't rate it" — so
    an unrated feeling counts at the scale midpoint rather than dropping out.
    """
    if not isinstance(feelings, list) or not feelings:
        return None, None, 0, None
    pos, neg, all_int = [], [], []
    for f in feelings:
        if not isinstance(f, dict):
            continue
        name = (f.get("name") or "").strip().lower()
        intensity = _num(f.get("intensity"))
        if intensity is None:
            intensity = 5.5  # felt, unrated → midpoint of the 1–10 scale
        all_int.append(intensity)
        if name in POSITIVE_FEELINGS:
            pos.append(intensity)
        elif name in NEGATIVE_FEELINGS:
            neg.append(intensity)
    return (
        float(np.mean(pos)) if pos else 0.0,
        float(np.mean(neg)) if neg else 0.0,
        len(all_int),
        float(np.mean(all_int)) if all_int else None,
    )


def _productivity_proxy(content, keywords, feelings) -> Optional[float]:
    """A 1–10 productivity estimate from a reflection. PROXY — see DERIVED_NOTES.

    Two independent signals, averaged over whichever are present:
      • self-reported intensity of "focused" / "energized" (the user's own rating)
      • the balance of productive vs scattered language in the entry

    Returns None when the day carries neither, so a day with no evidence stays
    missing instead of being scored a bland 5.
    """
    signals: list[float] = []

    if isinstance(feelings, list):
        reported = [
            _num(f.get("intensity"))
            for f in feelings
            if isinstance(f, dict)
            and (f.get("name") or "").strip().lower() in ("focused", "energized")
            and _num(f.get("intensity")) is not None
        ]
        if reported:
            signals.append(float(np.mean(reported)))

    haystack = (content or "").lower()
    if keywords:
        haystack += " " + " ".join(str(k).lower() for k in keywords)
    if haystack.strip():
        hits_p = sum(1 for t in PRODUCTIVE_TERMS if t in haystack)
        hits_s = sum(1 for t in SCATTERED_TERMS if t in haystack)
        if hits_p or hits_s:
            balance = (hits_p - hits_s) / (hits_p + hits_s)   # -1 … +1
            signals.append(5.5 + 4.5 * balance)               # → 1 … 10

    return float(np.mean(signals)) if signals else None


# ── Cycle logs (optional table) ──────────────────────────────────────────────
CYCLE_TABLE = "cycle_logs"
DEFAULT_CYCLE_LENGTH = 28
# Phase boundaries. Luteal length is the stable part of a cycle (~14 days), so
# ovulation is anchored backwards from the next expected start and the
# follicular phase absorbs the variation. Menstrual is a flat 1–5.
MENSTRUAL_DAYS = 5
LUTEAL_LENGTH = 14
OVULATORY_WINDOW = 3

PHASE_ORDER = ["Menstrual", "Follicular", "Ovulatory", "Luteal"]
PHASE_COLORS = {
    "Menstrual": "#e05a3a",
    "Follicular": "#3dab7a",
    "Ovulatory": "#d4850a",
    "Luteal": "#5b6fa6",
}


def load_cycle_starts(supabase, user_id: str) -> list[date]:
    """Logged period start dates, oldest first. [] if the table doesn't exist."""
    rows = _rows(supabase, CYCLE_TABLE, user_id)
    out = []
    for r in rows:
        try:
            out.append(datetime.fromisoformat(str(r["entry_date"])[:10]).date())
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(set(out))


def save_cycle_start(supabase, user_id: str, day: date) -> None:
    supabase.table(CYCLE_TABLE).upsert(
        {"user_id": user_id, "entry_date": day.isoformat()},
        on_conflict="user_id,entry_date",
    ).execute()


def delete_cycle_start(supabase, user_id: str, day: date) -> None:
    (supabase.table(CYCLE_TABLE).delete()
     .eq("user_id", user_id).eq("entry_date", day.isoformat()).execute())


def median_cycle_length(starts: list[date]) -> int:
    """Median gap between logged starts, or the 28-day default with <2 logs."""
    if len(starts) < 2:
        return DEFAULT_CYCLE_LENGTH
    gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if 15 <= (b - a).days <= 60]
    if not gaps:
        return DEFAULT_CYCLE_LENGTH
    return int(round(float(np.median(gaps))))


def cycle_day_and_phase(day: date, starts: list[date],
                        cycle_length: int = DEFAULT_CYCLE_LENGTH
                        ) -> tuple[Optional[int], Optional[str]]:
    """(day-in-cycle, phase name) for `day`, or (None, None) if unknowable.

    A day is only labelled when it falls within a plausible cycle length of the
    most recent logged start. Beyond that the log has gone stale and guessing a
    phase would invent data — the whole point of the lens is comparing real
    phases, so an unlabelled day is dropped rather than filled in.
    """
    prior = [s for s in starts if s <= day]
    if not prior:
        return None, None
    start = prior[-1]
    day_in_cycle = (day - start).days + 1
    if day_in_cycle > cycle_length + 10:
        return None, None

    ovulation_day = max(MENSTRUAL_DAYS + 1, cycle_length - LUTEAL_LENGTH)
    if day_in_cycle <= MENSTRUAL_DAYS:
        return day_in_cycle, "Menstrual"
    if day_in_cycle < ovulation_day:
        return day_in_cycle, "Follicular"
    if day_in_cycle < ovulation_day + OVULATORY_WINDOW:
        return day_in_cycle, "Ovulatory"
    return day_in_cycle, "Luteal"


def add_cycle_phase(df: pd.DataFrame, starts: list[date]) -> pd.DataFrame:
    """Add `cycle_day` / `cycle_phase` columns. No-op shape when starts is empty."""
    out = df.copy()
    if not starts:
        out["cycle_day"] = np.nan
        out["cycle_phase"] = None
        return out
    length = median_cycle_length(starts)
    days, phases = [], []
    for ts in out.index:
        d, p = cycle_day_and_phase(ts.date(), starts, length)
        days.append(d if d is not None else np.nan)
        phases.append(p)
    out["cycle_day"] = days
    out["cycle_phase"] = phases
    return out


# ── User priorities (drives the default lens) ────────────────────────────────
# The inquiry stores answers as jsonb on users.inquiry_responses; the closing
# question records `_priorities.top`, the handful of things the user said they
# want to focus on. That is the "features of importance" signal.
PRIORITY_KEYWORDS = {
    "sleep": ("sleep", "rest", "insomnia", "tired"),
    "mood": ("mood", "emotion", "feel", "anxiety", "anxious", "depress", "stress"),
    "activity": ("exercise", "movement", "active", "fitness", "workout", "steps"),
    "productivity": ("work", "productiv", "focus", "career", "study", "creative"),
    "cycle": ("cycle", "hormon", "period", "menstrual", "pms"),
}


def load_priorities(supabase, user_id: str) -> list[str]:
    """The user's stated focus areas, verbatim, or [] if they haven't answered."""
    try:
        res = (supabase.table("users").select("inquiry_responses")
               .eq("id", user_id).limit(1).execute())
    except Exception:
        return []
    rows = res.data or []
    if not rows:
        return []
    responses = rows[0].get("inquiry_responses") or {}
    if isinstance(responses, str):
        try:
            import json
            responses = json.loads(responses)
        except ValueError:
            return []
    top = (responses.get("_priorities") or {}).get("top") or []
    return [str(t) for t in top if str(t).strip()]


def priority_lens_keys(priorities: list[str]) -> list[str]:
    """Map free-text priorities onto lens keys, best match first.

    The inquiry lets people write their own priorities, so this is a keyword
    match, not a lookup — an unmatched priority simply contributes nothing
    rather than forcing a lens the user didn't ask for.
    """
    hits: list[str] = []
    blob = " ".join(priorities).lower()
    for lens_key, needles in PRIORITY_KEYWORDS.items():
        if any(n in blob for n in needles):
            hits.append(lens_key)
    return hits


# ── Windowing ────────────────────────────────────────────────────────────────
WINDOW_OPTIONS = {
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 6 months": 182,
    "All time": None,
}


def apply_window(df: pd.DataFrame, days: Optional[int]) -> pd.DataFrame:
    if df.empty or days is None:
        return df
    cutoff = df.index.max() - pd.Timedelta(days=days - 1)
    return df[df.index >= cutoff]


def coverage(df: pd.DataFrame, column: str) -> int:
    """How many days in `df` actually carry `column`."""
    if df.empty or column not in df.columns:
        return 0
    return int(df[column].notna().sum())
