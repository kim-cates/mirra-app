"""Simples — one plain timeseries per headline metric.

Deliberately the least clever tab in the app: no clustering, no correlation, no
interpretation. Five metrics, one chart each, so you can see the shape of your
own record at a glance.

On the word "cumulative": a running total only means something for a quantity
you accumulate. Sleep is one — 214 hours since June is a real number. Mood,
resting HR, HRV and tempo are rates; summing them produces a number with no
unit and no meaning, so for those "cumulative" is the running (expanding)
average — the answer to "what's my average so far, as of this day". Each chart
says which of the two it is doing.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import insights_data as idata

# key, label, unit, how "cumulative" accumulates, color, source table
METRICS = [
    ("sleep_hours", "Sleep",        "h",   "sum",  "#5b6fa6", "oura_daily"),
    ("mood",        "Mood",         "/10", "mean", "#3dab7a", "reflections"),
    ("resting_hr",  "Resting HR",   "bpm", "mean", "#e05a3a", "oura_daily"),
    ("hrv_avg",     "HRV",          "ms",  "mean", "#1abc9c", "oura_daily"),
    ("tempo",       "Music tempo",  "BPM", "mean", "#d4850a", "spotify_daily"),
]

VIEW_CUMULATIVE = "Cumulative"
VIEW_DAILY = "Daily"
VIEW_ROLLING = "7-day average"
VIEWS = [VIEW_CUMULATIVE, VIEW_DAILY, VIEW_ROLLING]


def render_simples_tab(supabase, user_id: str) -> None:
    st.markdown('<p class="title-text">Simples</p>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">'
        'Your headline numbers over time — sleep, mood, resting heart rate, HRV '
        'and listening tempo. No modelling, just the record.'
        '</div>',
        unsafe_allow_html=True,
    )

    df = idata.load_daily_frame(supabase, user_id)
    if df.empty:
        st.markdown(
            '<div class="min-data-msg">Nothing to chart yet. Write a reflection, '
            'or connect Oura or Spotify from your Profile, and this fills in.</div>',
            unsafe_allow_html=True,
        )
        return

    ctrl_left, ctrl_right = st.columns([1, 1])
    with ctrl_left:
        window_label = st.selectbox("Time range", list(idata.WINDOW_OPTIONS.keys()),
                                    index=1, key="simples_window")
    with ctrl_right:
        view = st.radio("View", VIEWS, index=0, horizontal=True, key="simples_view")

    windowed = idata.apply_window(df, idata.WINDOW_OPTIONS[window_label])
    if windowed.empty:
        st.markdown('<div class="min-data-msg">No data in this range.</div>',
                    unsafe_allow_html=True)
        return

    if view == VIEW_CUMULATIVE:
        st.caption(
            "Cumulative sleep is a running total. Mood, resting HR, HRV and tempo "
            "are rates, so their cumulative view is the running average up to each "
            "day — a total would be meaningless."
        )

    for key, label, unit, accumulate, color, table in METRICS:
        _render_metric(windowed, key, label, unit, accumulate, color, table,
                       view=view, supabase=supabase, user_id=user_id)


# ── One metric ───────────────────────────────────────────────────────────────
def _render_metric(df: pd.DataFrame, key: str, label: str, unit: str,
                   accumulate: str, color: str, table: str, *,
                   view: str, supabase, user_id: str) -> None:
    st.markdown(f'<div class="section-label">{label}</div>', unsafe_allow_html=True)

    n = idata.coverage(df, key)
    if n == 0:
        _render_empty(df, key, label, table, supabase, user_id, view)
        return

    series = df[key]
    plotted, axis_title, headline = _transform(series, view, accumulate, unit)

    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:-0.3rem 0 0.4rem">'
        f'{headline}<span style="color:#bbb"> &middot; {n} day'
        f'{"s" if n != 1 else ""} with data</span></div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(_line_chart(plotted, color, axis_title),
                    width="stretch", key=f"simples_chart_{key}")


def _transform(series: pd.Series, view: str, accumulate: str,
               unit: str) -> tuple[pd.Series, str, str]:
    """(series to plot, y-axis title, headline summary line)."""
    if view == VIEW_DAILY:
        out = series
        return out, unit or "value", _headline("Latest", _last(out), unit)

    if view == VIEW_ROLLING:
        # min_periods=1 so the line starts at the first reading rather than
        # after a week of blank chart.
        out = series.rolling(7, min_periods=1).mean()
        return out, f"7-day mean ({unit})" if unit else "7-day mean", \
            _headline("7-day average", _last(out), unit)

    # Cumulative
    if accumulate == "sum":
        out = series.cumsum()
        return out, f"total ({unit})" if unit else "total", \
            _headline("Total so far", _last(out), unit)

    out = series.expanding().mean()
    return out, f"running mean ({unit})" if unit else "running mean", \
        _headline("Average so far", _last(out), unit)


def _last(series: pd.Series):
    valid = series.dropna()
    return None if valid.empty else float(valid.iloc[-1])


def _headline(prefix: str, value, unit: str) -> str:
    if value is None:
        return f"{prefix} —"
    digits = 0 if abs(value) >= 100 else 1
    return f"{prefix} <strong>{value:,.{digits}f}{unit}</strong>"


def _line_chart(series: pd.Series, color: str, axis_title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values,
        mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=_rgba(color, 0.10),
        # Gaps stay gaps: a day with no reading is not a straight line between
        # its neighbours, and pretending otherwise invents data.
        connectgaps=False,
        hovertemplate="%{x|%b %d, %Y}<br>%{y:.1f}<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=240, margin=dict(l=10, r=10, t=10, b=30),
        xaxis=dict(showgrid=False, color="#999"),
        yaxis=dict(title=axis_title, showgrid=True, gridcolor="#ece9df",
                   zeroline=False, color="#999"),
        hovermode="x unified",
    )
    return fig


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── Empty states ─────────────────────────────────────────────────────────────
def _render_empty(df: pd.DataFrame, key: str, label: str, table: str,
                  supabase, user_id: str, view: str) -> None:
    """Explain *why* a metric is blank — the reasons differ per source."""
    if key == "tempo":
        _render_tempo_empty(df, supabase, user_id, view)
        return

    if not idata.table_available(supabase, table, user_id):
        msg = (f"The <code>{table}</code> table isn't reachable yet, so {label} "
               f"has nowhere to come from.")
    elif table == "oura_daily":
        msg = (f"No {label} readings stored. Connect Oura from your Profile, "
               f"or run a sync from the Connections tab.")
    else:
        msg = f"No {label} recorded in this range."
    st.markdown(f'<div class="min-data-msg">{msg}</div>', unsafe_allow_html=True)


def _render_tempo_empty(df: pd.DataFrame, supabase, user_id: str, view: str) -> None:
    """Tempo is the one metric that is usually blank for a structural reason.

    Spotify restricted /audio-features to apps created before 2024-11-27, so
    `spotify_daily.tempo` stays NULL for a new app no matter how often you sync
    (see providers/spotify.py). Saying "no data" alone would send you hunting a
    sync bug that isn't there, so the reason is stated and listening time —
    which the same table does carry — is offered in its place.
    """
    has_spotify_rows = idata.coverage(df, "listening_minutes") > 0
    if not has_spotify_rows:
        st.markdown(
            '<div class="min-data-msg">No Spotify data in this range. Connect '
            'Spotify from your Profile, then use <strong>Sync last 30 days</strong>.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="min-data-msg">Spotify restricted its audio-features endpoint '
        'to apps registered before 2024-11-27, so tempo comes back empty for '
        'Mirra and there is nothing to plot — this is a Spotify policy limit, not '
        'a sync failure. Listening time, from the same rows, is shown instead.'
        '</div>',
        unsafe_allow_html=True,
    )
    series = df["listening_minutes"]
    plotted, axis_title, headline = _transform(series, view, "sum", " min")
    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.8rem 0 0.4rem">'
        f'Listening time &middot; {headline}</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(_line_chart(plotted, "#d4850a", axis_title),
                    width="stretch", key="simples_chart_listening")
