"""Simples — the user's headline numbers over time, shaped to how they like insights.

Deliberately the least clever tab in the app: no clustering, no correlation.
What it shows is the user's focus areas (focus_areas.py: sleep, stress, mood),
and HOW it shows them follows their insight style (insight_style.py), switchable
from the toggle in the top right:

  • Data-driven     — full timeseries for each focus metric, with a time range
                      and a 7-day average / Daily view, then a few terse
                      descriptive findings at the bottom.
  • Hybrid          — the descriptive findings first, then abstracted trend
                      lines (smoothed, no axis values: the shape, not the
                      data). The full data-driven charts and the raw numbers are
                      one click away, not shown by default.
  • Insight-focused — a short plain-language summary and before/now cards like
                      Weekly Insights', with "Dive deeper" for the full charts
                      and a research link per finding (a placeholder until the
                      literature reviews exist; see RESEARCH_LINKS).

Every finding compares the selected range against the same length of time just
before it ("All time" splits the record in half), and is built only from the
numbers being charted.

The full charts offer two views: the 7-day average (the default) and the raw
daily values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import focus_areas
import insight_style
import insights_data as idata


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    color: str
    table: str                       # source table, for empty-state messages
    higher_is_better: Optional[bool]  # None: no good direction (music tempo)
    digits: int
    noun: str                        # how a sentence refers to it


METRICS = [
    Metric("sleep_hours",   "Sleep",             " h",   "#5b6fa6", "oura_daily",    True,  1, "your sleep"),
    Metric("sleep_score",   "Sleep score",       "",     "#7d8fc4", "oura_daily",    True,  0, "your sleep score"),
    Metric("hrv_avg",       "HRV",               " ms",  "#1abc9c", "oura_daily",    True,  0, "your HRV"),
    Metric("resting_hr",    "Resting HR",        " bpm", "#e05a3a", "oura_daily",    False, 0, "your resting heart rate"),
    Metric("feel_negative", "Hard feelings",     "/10",  "#a3479b", "reflections",   False, 1, "the hard feelings you logged"),
    Metric("mood",          "Mood",              "/10",  "#3dab7a", "reflections",   True,  1, "your mood"),
    Metric("feel_positive", "Positive feelings", "/10",  "#8cc9a8", "reflections",   True,  1, "the positive feelings you logged"),
    Metric("tempo",         "Music tempo",       " BPM", "#d4850a", "spotify_daily", None,  0, "your music tempo"),
]
METRIC_BY_KEY = {m.key: m for m in METRICS}

# Research behind each finding, by metric key. Empty until the literature
# reviews are written; a finding with no entry shows a disabled "coming soon".
RESEARCH_LINKS: dict[str, str] = {}

VIEW_ROLLING = "7-day average"
VIEW_DAILY = "Daily"
VIEWS = [VIEW_ROLLING, VIEW_DAILY]   # first is the default

MIN_READINGS = 3     # per period, before a comparison is worth stating
FLAT_FRACTION = 0.03  # a change under 3% of the earlier average reads as steady


# ── Entry point ──────────────────────────────────────────────────────────────
def render_simples_tab(supabase, user_id: str) -> None:
    title_col, toggle_col = st.columns([3, 2], vertical_alignment="bottom")
    with title_col:
        st.markdown('<p class="title-text">Simples</p>', unsafe_allow_html=True)
    with toggle_col:
        style = insight_style.render_style_toggle(supabase, user_id)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">'
        f'Your headline numbers over time. {insight_style.DESCRIPTIONS[style]}'
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

    areas = focus_areas.load_focus_areas(
        supabase, user_id, idata.load_priorities(supabase, user_id), df)
    focus = [METRIC_BY_KEY[c] for c in focus_areas.columns_for(areas)
             if c in METRIC_BY_KEY]
    others = [m for m in METRICS if m not in focus]
    _render_focus_line(areas)

    windows = list(idata.WINDOW_OPTIONS.keys())
    window_label = st.selectbox("Time range", windows, index=0, key="simples_window")
    days = idata.WINDOW_OPTIONS[window_label]
    windowed = idata.apply_window(df, days)
    if windowed.empty:
        st.markdown('<div class="min-data-msg">No data in this range.</div>',
                    unsafe_allow_html=True)
        return

    findings = [f for f in (compare_periods(df, days, m) for m in focus) if f]

    if style == insight_style.DATA_DRIVEN:
        _render_data_driven(windowed, focus, others, findings, supabase, user_id)
    elif style == insight_style.HYBRID:
        _render_hybrid(windowed, focus, others, findings, supabase, user_id)
    else:
        _render_insight_focused(windowed, focus, others, findings, supabase, user_id)


def _render_focus_line(areas: list[str]) -> None:
    chips = " · ".join(focus_areas.label(a) for a in areas)
    st.markdown(
        f'<div style="background:#f0f8f4; border:1px solid #c9e4d6; border-radius:8px;'
        f'padding:0.65rem 1rem; font-size:0.9rem; color:#1e6b45; margin-bottom:0.9rem">'
        f'<strong>Your focus:</strong> {chips} — change it in Profile → '
        f'Personalization.</div>',
        unsafe_allow_html=True,
    )
    if focus_areas.STRESS in areas:
        st.caption(focus_areas.AREA_NOTES[focus_areas.STRESS])


# ── The three layouts ────────────────────────────────────────────────────────
def _render_data_driven(df, focus, others, findings, supabase, user_id) -> None:
    view = _render_full_charts(df, focus, supabase, user_id, prefix="dd")
    if others:
        with st.expander("Other metrics"):
            _render_metric_list(df, others, view, supabase, user_id, prefix="dd_other")
    st.markdown('<div class="section-label">Quick insights</div>', unsafe_allow_html=True)
    _render_bullets([describe(f, insight_style.DATA_DRIVEN) for f in findings])


def _render_hybrid(df, focus, others, findings, supabase, user_id) -> None:
    st.markdown('<div class="section-label">What changed</div>', unsafe_allow_html=True)
    _render_bullets([describe(f, insight_style.HYBRID) for f in findings])

    st.markdown('<div class="section-label">Trends</div>', unsafe_allow_html=True)
    st.caption("Smoothed over 7 days to show direction — the exact values are in "
               "the full data below.")
    by_key = {f["metric"].key: f for f in findings}
    plotted = [m for m in focus if idata.coverage(df, m.key) > 0]
    for row_start in range(0, len(plotted), 2):
        cols = st.columns(2)
        for col, metric in zip(cols, plotted[row_start:row_start + 2]):
            with col:
                _render_trend_chart(df, metric, by_key.get(metric.key))

    with st.expander("See the full data"):
        _render_full_charts(df, focus + others, supabase, user_id, prefix="hy")
        _render_raw_table(df, focus)


def _render_insight_focused(df, focus, others, findings, supabase, user_id) -> None:
    if findings:
        items = "".join(f'<li style="margin-bottom:0.45rem">'
                        f'{describe(f, insight_style.INSIGHT_FOCUSED)}</li>'
                        for f in findings)
        st.markdown(
            f'<div class="insight-card"><div class="insight-header">In short</div>'
            f'<ul style="margin:0; padding-left:1.1rem">{items}</ul></div>',
            unsafe_allow_html=True,
        )
    else:
        _render_bullets([])

    for row_start in range(0, len(findings), 3):
        cols = st.columns(3)
        for col, finding in zip(cols, findings[row_start:row_start + 3]):
            with col:
                _render_change_card(finding)

    with st.expander("Dive deeper"):
        _render_full_charts(df, focus + others, supabase, user_id, prefix="if")


# ── Findings ─────────────────────────────────────────────────────────────────
def compare_periods(df: pd.DataFrame, days: Optional[int], metric: Metric) -> Optional[dict]:
    """The selected range vs the same length of time just before it.

    For "All time" there is no before, so the record is split in half. None when
    the current range has too few readings to say anything.
    """
    if metric.key not in df.columns:
        return None
    series = df[metric.key]
    if days is None:
        valid = series.dropna()
        if len(valid) < 2 * MIN_READINGS:
            return None
        mid = valid.index[len(valid) // 2]
        current, previous = valid[valid.index >= mid], valid[valid.index < mid]
        baseline = "the first half of your record"
    else:
        start = df.index.max() - pd.Timedelta(days=days - 1)
        current = series[series.index >= start].dropna()
        previous = series[(series.index < start)
                          & (series.index >= start - pd.Timedelta(days=days))].dropna()
        baseline = f"the {days} days before"
    if len(current) < MIN_READINGS:
        return None

    now = float(current.mean())
    before = float(previous.mean()) if len(previous) >= MIN_READINGS else None
    change = None if before is None else now - before
    if change is None:
        direction = None
    elif abs(change) < max(abs(before) * FLAT_FRACTION, 10 ** -metric.digits):
        direction = "steady"
    else:
        direction = "up" if change > 0 else "down"
    favorable = None
    if direction in ("up", "down") and metric.higher_is_better is not None:
        favorable = (direction == "up") == metric.higher_is_better

    return {
        "metric": metric, "now": now, "before": before, "change": change,
        "direction": direction, "favorable": favorable, "baseline": baseline,
        "n_now": len(current), "n_before": len(previous),
        "low": float(current.min()), "high": float(current.max()),
        "low_day": current.idxmin(), "high_day": current.idxmax(),
    }


def fmt_value(metric: Metric, value: float, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:,.{metric.digits}f}{metric.unit}"


def _amount(metric: Metric, change: float) -> str:
    """A change in words-friendly units: sleep in minutes, the rest as-is."""
    if metric.key == "sleep_hours":
        return f"{abs(change) * 60:.0f} minutes"
    return fmt_value(metric, abs(change))


def describe(f: dict, style: str) -> str:
    """One finding, worded for the style."""
    m = f["metric"]
    now = fmt_value(m, f["now"])

    if style == insight_style.DATA_DRIVEN:
        text = f"<strong>{m.label}</strong>: mean {now} (n={f['n_now']})"
        if f["before"] is not None:
            pct = f["change"] / f["before"] * 100 if f["before"] else 0.0
            text += (f" vs {fmt_value(m, f['before'])} (n={f['n_before']}) in "
                     f"{f['baseline']} — {fmt_value(m, f['change'], signed=True)} "
                     f"({pct:+.0f}%)")
        return (text + f". Range {fmt_value(m, f['low'])} "
                f"({f['low_day']:%b %d}) to {fmt_value(m, f['high'])} "
                f"({f['high_day']:%b %d}).")

    if style == insight_style.HYBRID:
        if f["direction"] is None:
            return f"<strong>{m.label}</strong> averaged {now} in this range."
        if f["direction"] == "steady":
            return (f"<strong>{m.label}</strong> held steady at {now}, about the "
                    f"same as {f['baseline']}.")
        word = "up" if f["direction"] == "up" else "down"
        return (f"<strong>{m.label}</strong> is {word}: {now} on average, "
                f"{fmt_value(m, f['change'], signed=True)} vs {f['baseline']}.")

    # Insight-focused: what it means first, one number at most.
    noun = m.noun[0].upper() + m.noun[1:]
    if f["direction"] is None:
        return f"{noun} averaged about {now} over this stretch."
    if f["direction"] == "steady":
        return f"{noun} has held steady, at about {now}."
    more_less = "more" if f["direction"] == "up" else "less"
    if m.key == "sleep_hours":
        change = f"{_amount(m, f['change'])} {more_less} a night than {f['baseline']}"
    else:
        word = "up" if f["direction"] == "up" else "down"
        change = f"{word} {_amount(m, f['change'])} from {f['baseline']}"
    if f["favorable"] is True:
        lead = f"{noun} is moving in a good direction"
    elif f["favorable"] is False:
        lead = f"{noun} has slipped a little"
    else:
        lead = f"{noun} has shifted"
    return f"{lead} — {change}."


def _render_bullets(lines: list[str]) -> None:
    if not lines:
        st.markdown(
            f'<div class="min-data-msg">Not enough readings in this range to '
            f'describe yet — each finding needs at least {MIN_READINGS} days of '
            f'data in your focus areas.</div>',
            unsafe_allow_html=True,
        )
        return
    items = "".join(f'<li style="margin-bottom:0.4rem">{line}</li>' for line in lines)
    st.markdown(
        f'<ul style="font-size:0.92rem; color:#2a2a2a; padding-left:1.1rem; '
        f'margin:0.2rem 0 1rem">{items}</ul>',
        unsafe_allow_html=True,
    )


# ── Insight-focused cards ────────────────────────────────────────────────────
def _arrow(f: dict) -> tuple[str, str]:
    if f["direction"] in (None, "steady"):
        return "&rarr;", "#999"
    arrow = "&uarr;" if f["direction"] == "up" else "&darr;"
    if f["favorable"] is None:
        return arrow, "#999"
    return arrow, "#3dab7a" if f["favorable"] else "#c25540"


def _render_change_card(f: dict) -> None:
    """Weekly Insights-style card, plus a two-bar before/now chart."""
    m = f["metric"]
    arrow, color = _arrow(f)
    if f["change"] is None:
        sub = "nothing earlier to compare with"
    else:
        sub = (f"<span style='color:{color}; font-weight:600'>{arrow} "
               f"{fmt_value(m, f['change'], signed=True)}</span> vs {f['baseline']}")
    st.markdown(
        f'<div style="background:white; border:1px solid #ece9df; border-radius:12px;'
        f'padding:0.85rem 1rem 0.9rem;">'
        f'<div style="display:flex; align-items:center; gap:7px; margin-bottom:6px;">'
        f'<span style="display:inline-block; width:6px; height:6px; border-radius:999px;'
        f'background:{m.color};"></span>'
        f'<span style="font-size:0.66rem; font-weight:600; color:#999; letter-spacing:0.14em;'
        f'text-transform:uppercase;">{m.label}</span></div>'
        f'<div style="font-family:\'Lora\',serif; font-size:1.6rem; font-weight:600;'
        f'color:#1a1a1a; line-height:1.05;">{fmt_value(m, f["now"])}</div>'
        f'<div style="font-size:0.76rem; color:#888; margin-top:4px">{sub}</div></div>',
        unsafe_allow_html=True,
    )
    if f["before"] is not None:
        fig = go.Figure(go.Bar(
            x=["Before", "Now"], y=[f["before"], f["now"]],
            marker=dict(color=["#d9d6cc", m.color]),
            hovertemplate="%{x}: %{y:.1f}<extra></extra>",
        ))
        fig.update_layout(
            paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
            font=dict(family="DM Sans", color="#2a2a2a", size=11),
            height=130, margin=dict(l=4, r=4, t=8, b=24), showlegend=False,
            xaxis=dict(showgrid=False, color="#999"),
            yaxis=dict(visible=False),
        )
        st.plotly_chart(fig, width="stretch", key=f"simples_card_{m.key}",
                        config={"displayModeBar": False})
    _render_research_link(m)


def _render_research_link(metric: Metric) -> None:
    url = RESEARCH_LINKS.get(metric.key)
    if url:
        st.link_button("Read the research", url, width="stretch")
    else:
        st.button("Research — coming soon", key=f"simples_research_{metric.key}",
                  disabled=True, width="stretch")


# ── Hybrid trend charts ──────────────────────────────────────────────────────
def _render_trend_chart(df: pd.DataFrame, metric: Metric, finding: Optional[dict]) -> None:
    """The shape of the line, not the data: 7-day smoothed, no y values."""
    trend = df[metric.key].rolling(7, min_periods=1).mean()
    word = {"up": "trending up", "down": "trending down",
            "steady": "holding steady"}.get((finding or {}).get("direction"), "")
    st.markdown(
        f'<div style="font-size:0.85rem; color:#666; margin-bottom:-0.4rem">'
        f'<strong style="color:#1a1a1a">{metric.label}</strong>'
        f'{" · " + word if word else ""}</div>',
        unsafe_allow_html=True,
    )
    fig = go.Figure(go.Scatter(
        x=trend.index, y=trend.values, mode="lines",
        line=dict(color=metric.color, width=3, shape="spline"),
        connectgaps=False, hoverinfo="skip", showlegend=False,
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=150, margin=dict(l=4, r=4, t=12, b=24),
        xaxis=dict(showgrid=False, color="#bbb", tickformat="%b %d", nticks=4),
        yaxis=dict(visible=False),
    )
    st.plotly_chart(fig, width="stretch", key=f"simples_trend_{metric.key}",
                    config={"displayModeBar": False})


def _render_raw_table(df: pd.DataFrame, metrics: list[Metric]) -> None:
    cols = [m.key for m in metrics if m.key in df.columns]
    table = df[cols].dropna(how="all")
    if table.empty:
        return
    st.markdown('<div class="section-label">Raw data</div>', unsafe_allow_html=True)
    table = table.rename(columns={m.key: m.label + (f" ({m.unit.strip()})" if m.unit.strip() else "")
                                  for m in metrics})
    table.index = table.index.strftime("%Y-%m-%d")
    st.dataframe(table.sort_index(ascending=False).round(1), width="stretch")


# ── Full (data-driven) charts ────────────────────────────────────────────────
def _render_full_charts(df: pd.DataFrame, metrics: list[Metric], supabase,
                        user_id: str, *, prefix: str) -> str:
    """View selector + one chart per metric. Returns the chosen view."""
    view = st.radio("View", VIEWS, index=0, horizontal=True, key=f"simples_view_{prefix}")
    _render_metric_list(df, metrics, view, supabase, user_id, prefix=prefix)
    return view


def _render_metric_list(df, metrics, view, supabase, user_id, *, prefix: str) -> None:
    for metric in metrics:
        _render_metric(df, metric, view=view, supabase=supabase, user_id=user_id,
                       prefix=prefix)


def _render_metric(df: pd.DataFrame, metric: Metric, *, view: str, supabase,
                   user_id: str, prefix: str) -> None:
    st.markdown(f'<div class="section-label">{metric.label}</div>', unsafe_allow_html=True)

    n = idata.coverage(df, metric.key)
    if n == 0:
        _render_empty(df, metric, supabase, user_id, view, prefix)
        return

    plotted, axis_title, headline = _transform(df[metric.key], view,
                                               metric.unit.strip())
    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:-0.3rem 0 0.4rem">'
        f'{headline}<span style="color:#bbb"> &middot; {n} day'
        f'{"s" if n != 1 else ""} with data</span></div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(_line_chart(plotted, metric.color, axis_title),
                    width="stretch", key=f"simples_chart_{prefix}_{metric.key}")


def _transform(series: pd.Series, view: str,
               unit: str) -> tuple[pd.Series, str, str]:
    """(series to plot, y-axis title, headline summary line)."""
    if view == VIEW_DAILY:
        out = series
        return out, unit or "value", _headline("Latest", _last(out), unit)

    # 7-day average. min_periods=1 so the line starts at the first reading
    # rather than after a week of blank chart.
    out = series.rolling(7, min_periods=1).mean()
    return out, f"7-day mean ({unit})" if unit else "7-day mean", \
        _headline("7-day average", _last(out), unit)


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
def _render_empty(df: pd.DataFrame, metric: Metric, supabase, user_id: str,
                  view: str, prefix: str) -> None:
    """Explain *why* a metric is blank — the reasons differ per source."""
    if metric.key == "tempo":
        _render_tempo_empty(df, supabase, user_id, view, prefix)
        return

    if not idata.table_available(supabase, metric.table, user_id):
        msg = (f"The <code>{metric.table}</code> table isn't reachable yet, so "
               f"{metric.label} has nowhere to come from.")
    elif metric.table == "oura_daily":
        msg = (f"No {metric.label} readings stored. Connect Oura from your Profile, "
               f"or run a sync from the Connections tab.")
    elif metric.key.startswith("feel_"):
        msg = (f"No {metric.label.lower()} logged in this range — they come from "
               f"the feelings you tag on a reflection.")
    else:
        msg = f"No {metric.label} recorded in this range."
    st.markdown(f'<div class="min-data-msg">{msg}</div>', unsafe_allow_html=True)


def _render_tempo_empty(df: pd.DataFrame, supabase, user_id: str, view: str,
                        prefix: str) -> None:
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
    plotted, axis_title, headline = _transform(series, view, " min")
    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.8rem 0 0.4rem">'
        f'Listening time &middot; {headline}</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(_line_chart(plotted, "#d4850a", axis_title),
                    width="stretch", key=f"simples_chart_{prefix}_listening")
