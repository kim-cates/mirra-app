"""Personalized Insights — clustering lenses over the user's own daily record.

A "lens" is a named feature set: the columns that define what a grouping is
*about*. Cluster on sleep columns and you get sleep archetypes; cluster on mood
columns and you get mood categories. The lens list is the answer to "predefined
clusters based on features of importance", and the user's stated priorities
(users.inquiry_responses._priorities.top) pick which one opens first.

Every lens reports three things:
  • the groups it found, in the units you'd recognize (not z-scores)
  • when each group happened, so you can place it in your own history
  • what ELSE differs across those groups — the columns that were NOT clustered
    on. That last one is where the insight usually is: sleep archetypes that
    also split your mood, cycle phases that also split your HRV.

Honesty rules this file follows:
  • k is chosen by silhouette, and the score is shown. A weak score is labelled
    weak rather than dressed up.
  • Groups found in 30 days of one person's data are patterns, not findings.
    The sample size is always on screen.
  • `productivity` is a derived proxy (see insights_data.DERIVED_NOTES) and is
    labelled as one everywhere it appears.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import insights_data as idata

# ── Palette ──────────────────────────────────────────────────────────────────
# Fixed order, never cycled — cluster 1 is always rust, cluster 2 always sage.
# Validated for colorblind separation against this app's #faf9f5 surface
# (lightness band, chroma floor, CVD ΔE and normal-vision ΔE all pass over all
# pairs). The two below-3:1 contrast slots are relieved by the cluster cards and
# the table view, which name every group in text rather than by color alone.
CLUSTER_COLORS = ["#c2503a", "#3dab7a", "#c99a12", "#4b6bd6", "#a3479b"]
MAX_CLUSTERS = len(CLUSTER_COLORS)

# Diverging ramp for the z-score heatmap: two hues, neutral midpoint, no rainbow.
DIVERGING = [[0.0, "#4b6bd6"], [0.5, "#ece9df"], [1.0, "#c2503a"]]

MIN_DAYS_FOR_CLUSTERING = 12
MIN_DAYS_PER_GROUP = 3


# ── Column display metadata ──────────────────────────────────────────────────
FEATURE_META: dict[str, tuple[str, str, int]] = {
    # column: (label, unit suffix, decimal places)
    "sleep_score":       ("Sleep score", "", 0),
    "sleep_hours":       ("Sleep", "h", 1),
    "hrv_avg":           ("HRV", "ms", 0),
    "resting_hr":        ("Resting HR", "bpm", 0),
    "readiness_score":   ("Readiness", "", 0),
    "activity_score":    ("Activity score", "", 0),
    "steps":             ("Steps", "", 0),
    "mood":              ("Mood", "/10", 1),
    "feel_positive":     ("Positive feelings", "", 1),
    "feel_negative":     ("Hard feelings", "", 1),
    "feel_intensity":    ("Feeling intensity", "", 1),
    "feel_count":        ("Feelings named", "", 1),
    "productivity":      ("Productivity (proxy)", "/10", 1),
    "word_count":        ("Words written", "", 0),
    "keyword_count":     ("Themes tagged", "", 1),
    "tempo":             ("Music tempo", " BPM", 0),
    "listening_minutes": ("Listening", " min", 0),
    "track_count":       ("Tracks played", "", 0),
    "unique_artists":    ("Artists", "", 0),
    "valence":           ("Music positivity", "", 2),
    "energy":            ("Music energy", "", 2),
    "cycle_day":         ("Day of cycle", "", 0),
}

# Everything a lens can report as "what else differs", in display order.
CONTEXT_COLUMNS = [
    "mood", "feel_positive", "feel_negative", "productivity",
    "sleep_score", "sleep_hours", "hrv_avg", "resting_hr",
    "readiness_score", "activity_score", "steps",
    "listening_minutes", "track_count", "tempo", "valence", "energy",
    "word_count",
]


def label_of(col: str) -> str:
    return FEATURE_META.get(col, (col.replace("_", " ").title(), "", 1))[0]


def fmt(col: str, value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    _, unit, digits = FEATURE_META.get(col, (col, "", 1))
    return f"{value:,.{digits}f}{unit}"


# ── Lenses ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Lens:
    key: str
    label: str
    blurb: str
    features: tuple[str, ...]
    method: str = "kmeans"          # "kmeans" | "cycle"
    caveat: str = ""


LENSES: list[Lens] = [
    Lens(
        key="sleep",
        label="Sleep quality",
        blurb="Groups your nights by how you actually slept — score, duration, "
              "HRV and resting heart rate together, rather than one number at a time.",
        features=("sleep_score", "sleep_hours", "hrv_avg", "resting_hr"),
    ),
    Lens(
        key="mood",
        label="Mood categories",
        blurb="Groups your days by your rating and the feelings you named, so "
              "\"a 6\" splits into the different kinds of 6 you actually have.",
        features=("mood", "feel_positive", "feel_negative", "feel_intensity"),
    ),
    Lens(
        key="activity",
        label="Activity level",
        blurb="Groups your days by movement — Oura's activity score alongside "
              "raw step count.",
        features=("activity_score", "steps"),
    ),
    Lens(
        key="productivity",
        label="Productivity level",
        blurb="Groups your days by a productivity estimate built from your own "
              "words and your self-reported focus.",
        features=("productivity", "mood", "word_count"),
        caveat="Mirra stores no productivity metric, so this lens clusters a "
               "PROXY: the intensity you gave \"focused\" or \"energized\", plus "
               "the balance of productive and scattered language in your "
               "reflections. It reflects how you wrote about your day, which is "
               "not the same as what you got done.",
    ),
    Lens(
        key="cycle",
        label="Hormonal cycle",
        blurb="Uses cycle phase as the category and asks what the rest of your "
              "data does inside each phase.",
        features=(),
        method="cycle",
    ),
]

LENS_BY_KEY = {lens.key: lens for lens in LENSES}


# ── Entry point ──────────────────────────────────────────────────────────────
def render_personalized_insights_tab(supabase, user_id: str) -> None:
    st.markdown('<p class="title-text">Personalized Insights</p>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">'
        'Clustering models over your own record. Each lens groups your days by a '
        'different set of features, then shows what else those groups have in common.'
        '</div>',
        unsafe_allow_html=True,
    )

    df = idata.load_daily_frame(supabase, user_id)
    if df.empty:
        st.markdown(
            '<div class="min-data-msg">No data to model yet. Reflections, Oura and '
            'Spotify all feed these lenses — start with a few reflections.</div>',
            unsafe_allow_html=True,
        )
        return

    priorities = idata.load_priorities(supabase, user_id)
    default_key = _default_lens_key(priorities)
    _render_priority_banner(priorities, default_key)

    keys = [lens.key for lens in LENSES]
    chosen = st.selectbox(
        "Cluster by",
        options=keys,
        index=keys.index(default_key),
        format_func=lambda k: LENS_BY_KEY[k].label,
        key="pi_lens",
    )
    lens = LENS_BY_KEY[chosen]

    window_label = st.selectbox("Time range", list(idata.WINDOW_OPTIONS.keys()),
                                index=3, key="pi_window")
    windowed = idata.apply_window(df, idata.WINDOW_OPTIONS[window_label])

    st.markdown(f'<div class="insight-card">{lens.blurb}</div>', unsafe_allow_html=True)
    if lens.caveat:
        st.warning(lens.caveat)

    if lens.method == "cycle":
        _render_cycle_lens(supabase, user_id, windowed)
    else:
        _render_kmeans_lens(lens, windowed)


def _default_lens_key(priorities: list[str]) -> str:
    """Open on the lens matching what the user said they care about."""
    matched = idata.priority_lens_keys(priorities)
    for key in matched:
        if key in LENS_BY_KEY:
            return key
    return "sleep"


def _render_priority_banner(priorities: list[str], default_key: str) -> None:
    if not priorities:
        st.caption(
            "Answer the insight questions in your Profile and these lenses will "
            "open on what you said you're focusing on."
        )
        return
    chips = " · ".join(priorities)
    st.markdown(
        f'<div style="background:#f0f8f4; border:1px solid #c9e4d6; border-radius:8px;'
        f'padding:0.65rem 1rem; font-size:0.9rem; color:#1e6b45; margin-bottom:0.9rem">'
        f'<strong>Your focus:</strong> {chips} — opening on '
        f'<strong>{LENS_BY_KEY[default_key].label}</strong>.</div>',
        unsafe_allow_html=True,
    )


# ── K-means lenses ───────────────────────────────────────────────────────────
def _render_kmeans_lens(lens: Lens, df: pd.DataFrame) -> None:
    available = [c for c in lens.features if c in df.columns]
    missing = [c for c in lens.features if c not in df.columns]
    if not available:
        st.markdown(
            f'<div class="min-data-msg">None of this lens\'s inputs '
            f'({", ".join(label_of(c) for c in lens.features)}) exist in your data '
            f'yet.</div>',
            unsafe_allow_html=True,
        )
        return

    # Clustering needs complete rows — a day missing one feature can't be placed.
    matrix = df[available].dropna()
    if len(matrix) < MIN_DAYS_FOR_CLUSTERING:
        st.markdown(
            f'<div class="min-data-msg">This lens needs at least '
            f'<strong>{MIN_DAYS_FOR_CLUSTERING} days</strong> where '
            f'{", ".join(label_of(c) for c in available)} were all recorded. '
            f'You have <strong>{len(matrix)}</strong>.</div>',
            unsafe_allow_html=True,
        )
        return

    if missing:
        st.caption(f"Not available in your data, so left out: "
                   f"{', '.join(label_of(c) for c in missing)}.")

    result = _fit_clusters(matrix)
    if result is None:
        st.markdown(
            '<div class="min-data-msg">Your days in this range are too similar to '
            'split into meaningful groups — which is itself an answer.</div>',
            unsafe_allow_html=True,
        )
        return
    labels, k, silhouette, z_profiles = result

    assigned = df.loc[matrix.index].copy()
    assigned["_cluster"] = labels
    names = _name_clusters(z_profiles, available)

    _render_quality_line(k, len(matrix), silhouette)
    _render_cluster_cards(assigned, available, names)
    _render_z_heatmap(z_profiles, available, names)
    _render_timeline(assigned, names)
    _render_contrast_table(assigned, available, names)


def _fit_clusters(matrix: pd.DataFrame):
    """Standardize, sweep k by silhouette, fit. None if nothing separates."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    X = StandardScaler().fit_transform(matrix.values)
    if np.allclose(X.std(axis=0), 0):
        return None

    max_k = min(MAX_CLUSTERS, len(matrix) // MIN_DAYS_PER_GROUP)
    if max_k < 2:
        return None

    best = None
    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(X)
        if len(set(labels)) < k:
            continue
        score = silhouette_score(X, labels)
        if best is None or score > best[2]:
            best = (labels, k, score)
    if best is None:
        return None

    labels, k, score = best
    # Report profiles in standard deviations so features on different scales are
    # comparable; the cards alongside show the same thing in real units.
    z = pd.DataFrame(X, index=matrix.index, columns=matrix.columns)
    z["_cluster"] = labels
    z_profiles = z.groupby("_cluster").mean()
    return labels, k, score, z_profiles


def _name_clusters(z_profiles: pd.DataFrame, features: list[str]) -> dict[int, str]:
    """Name each group after the one or two features that most define it."""
    names: dict[int, str] = {}
    for cluster_id, row in z_profiles.iterrows():
        ranked = sorted(features, key=lambda c: -abs(row[c]))
        parts = []
        for col in ranked[:2]:
            if abs(row[col]) < 0.4:      # not distinctive enough to name
                continue
            parts.append(f"{'high' if row[col] > 0 else 'low'} {label_of(col).lower()}")
        if not parts:
            names[cluster_id] = "Typical days"
        else:
            phrase = ", ".join(parts)
            names[cluster_id] = phrase[0].upper() + phrase[1:]
    # Two groups can round to the same phrase; keep them distinguishable.
    seen: dict[str, int] = {}
    for cluster_id, name in list(names.items()):
        if name in seen:
            seen[name] += 1
            names[cluster_id] = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
    return names


def _render_quality_line(k: int, n_days: int, silhouette: float) -> None:
    if silhouette >= 0.5:
        verdict, tone = "well separated", "#2a8a5e"
    elif silhouette >= 0.25:
        verdict, tone = "moderately separated", "#d4850a"
    else:
        verdict, tone = "weakly separated — treat as suggestive only", "#e05a3a"
    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.2rem 0 1rem">'
        f'<strong>{k} groups</strong> across <strong>{n_days} days</strong> · '
        f'silhouette {silhouette:.2f} — <span style="color:{tone}">{verdict}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_cluster_cards(assigned: pd.DataFrame, features: list[str],
                          names: dict[int, str]) -> None:
    st.markdown('<div class="section-label">The groups</div>', unsafe_allow_html=True)
    total = len(assigned)
    ids = sorted(names.keys())
    for row_start in range(0, len(ids), 2):
        cols = st.columns(2)
        for col, cluster_id in zip(cols, ids[row_start:row_start + 2]):
            member = assigned[assigned["_cluster"] == cluster_id]
            color = CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)]
            stats = "".join(
                f'<div style="display:flex; justify-content:space-between; '
                f'font-size:0.88rem; padding:2px 0">'
                f'<span style="color:#666">{label_of(f)}</span>'
                f'<span style="color:#1a1a1a; font-weight:500">'
                f'{fmt(f, member[f].mean())}</span></div>'
                for f in features
            )
            with col:
                st.markdown(
                    f'<div style="background:white; border:1px solid #ece9df; '
                    f'border-left:3px solid {color}; border-radius:12px; '
                    f'padding:1rem 1.1rem; margin-bottom:0.7rem; height:100%">'
                    f'<div style="font-family:\'Lora\',serif; font-size:1.05rem; '
                    f'font-weight:600; color:#1a1a1a; margin-bottom:0.2rem">'
                    f'{names[cluster_id]}</div>'
                    f'<div style="font-size:0.8rem; color:#aaa; margin-bottom:0.7rem">'
                    f'{len(member)} days · {100 * len(member) / total:.0f}% of the range</div>'
                    f'{stats}</div>',
                    unsafe_allow_html=True,
                )


def _render_z_heatmap(z_profiles: pd.DataFrame, features: list[str],
                      names: dict[int, str]) -> None:
    """Each group's fingerprint in standard deviations from your own average."""
    st.markdown('<div class="section-label">Group fingerprints</div>',
                unsafe_allow_html=True)
    z = z_profiles[features]
    limit = float(np.abs(z.values).max()) or 1.0
    fig = go.Figure(go.Heatmap(
        z=z.values,
        x=[label_of(c) for c in features],
        y=[names[i] for i in z.index],
        colorscale=DIVERGING,
        zmid=0, zmin=-limit, zmax=limit,
        xgap=2, ygap=2,
        colorbar=dict(title=dict(text="SD from<br>your average", font=dict(size=11)),
                      thickness=12, len=0.9),
        hovertemplate="%{y}<br>%{x}: %{z:+.2f} SD<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a", size=12),
        height=90 + 44 * len(z), margin=dict(l=10, r=10, t=10, b=40),
        # automargin on both axes: cluster names are generated from feature
        # labels ("High sleep score, low resting HR") and will otherwise clip.
        xaxis=dict(side="bottom", color="#666", automargin=True),
        yaxis=dict(color="#666", autorange="reversed", automargin=True),
    )
    st.plotly_chart(fig, width="stretch", key="pi_heatmap")
    st.caption("Warm = above your own average for that feature, cool = below. "
               "Measured in standard deviations, so features on different scales "
               "can sit side by side.")


def _render_timeline(assigned: pd.DataFrame, names: dict[int, str]) -> None:
    st.markdown('<div class="section-label">When each group happened</div>',
                unsafe_allow_html=True)
    fig = go.Figure()
    for cluster_id in sorted(names.keys()):
        member = assigned[assigned["_cluster"] == cluster_id]
        fig.add_trace(go.Scatter(
            x=member.index, y=[names[cluster_id]] * len(member),
            mode="markers",
            name=names[cluster_id],
            marker=dict(size=9, color=CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)],
                        line=dict(width=1.5, color="#faf9f5")),
            hovertemplate="%{x|%b %d, %Y}<br>" + names[cluster_id] + "<extra></extra>",
        ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=90 + 42 * len(names), margin=dict(l=10, r=10, t=10, b=30),
        xaxis=dict(showgrid=True, gridcolor="#ece9df", color="#999"),
        yaxis=dict(showgrid=False, color="#666", automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"),
        showlegend=True,
    )
    st.plotly_chart(fig, width="stretch", key="pi_timeline")


def _render_contrast_table(assigned: pd.DataFrame, features: list[str],
                           names: dict[int, str]) -> None:
    """The payoff: what differs across groups among columns NOT clustered on."""
    others = [c for c in CONTEXT_COLUMNS
              if c not in features and c in assigned.columns
              and assigned[c].notna().sum() >= MIN_DAYS_FOR_CLUSTERING]
    if not others:
        return

    st.markdown('<div class="section-label">What else differs</div>',
                unsafe_allow_html=True)
    st.caption("These columns were not used to build the groups — so a real gap "
               "here is the grouping telling you something.")

    rows = []
    for col in others:
        means = assigned.groupby("_cluster")[col].mean()
        spread = _spread_in_sd(assigned[col], means)
        row = {"Metric": label_of(col)}
        for cluster_id in sorted(names.keys()):
            row[names[cluster_id]] = fmt(col, means.get(cluster_id))
        row["Spread"] = "—" if spread is None else f"{spread:.1f} SD"
        row["_sort"] = -1.0 if spread is None else -spread
        rows.append(row)

    table = pd.DataFrame(rows).sort_values("_sort").drop(columns=["_sort"])
    st.dataframe(table, hide_index=True, width="stretch")

    top = table.iloc[0]
    if top["Spread"] != "—" and float(top["Spread"].split()[0]) >= 0.8:
        st.markdown(
            f'<div class="insight-card"><strong>{top["Metric"]}</strong> separates '
            f'these groups most sharply, and it was never part of the model. '
            f'That is the pattern worth looking at.</div>',
            unsafe_allow_html=True,
        )


def _spread_in_sd(series: pd.Series, group_means: pd.Series) -> Optional[float]:
    """Range of group means, in standard deviations of the whole column."""
    sd = series.std()
    if not sd or np.isnan(sd) or group_means.isna().all():
        return None
    return float((group_means.max() - group_means.min()) / sd)


# ── Cycle lens ───────────────────────────────────────────────────────────────
def _render_cycle_lens(supabase, user_id: str, df: pd.DataFrame) -> None:
    """Cycle phase as the category, then what the rest of the data does inside it.

    Nothing in Mirra's schema records a menstrual cycle — not the profile, not
    Oura's stored columns — so this lens runs on a table the user fills in
    themselves. Until they do, it says so plainly instead of inventing a phase.
    """
    starts = idata.load_cycle_starts(supabase, user_id)
    _render_cycle_logger(supabase, user_id, starts)
    if not starts:
        return

    length = idata.median_cycle_length(starts)
    phased = idata.add_cycle_phase(df, starts)
    labelled = phased[phased["cycle_phase"].notna()]
    if labelled.empty:
        st.markdown(
            '<div class="min-data-msg">None of the days in this range fall inside '
            'a logged cycle. Add a more recent period start, or widen the time '
            'range.</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.2rem 0 1rem">'
        f'<strong>{len(starts)} cycles logged</strong> · median length '
        f'<strong>{length} days</strong> · {len(labelled)} days placed in a phase'
        f'</div>',
        unsafe_allow_html=True,
    )

    present = [p for p in idata.PHASE_ORDER if (labelled["cycle_phase"] == p).any()]
    _render_phase_table(labelled, present)
    _render_phase_chart(labelled, present)
    _render_cluster_vs_phase(labelled, present)

    st.caption(
        "Phases are estimated from your logged start dates using a standard "
        "model (menstrual days 1–5, ovulation anchored 14 days before the next "
        "expected start). It is an approximation for spotting patterns in your "
        "own data — not a medical calculation, and not contraception."
    )


def _render_cycle_logger(supabase, user_id: str, starts: list[date]) -> None:
    """Log period start dates. The only input this lens has."""
    with st.expander(f"Cycle log — {len(starts)} start date"
                     f"{'s' if len(starts) != 1 else ''} recorded",
                     expanded=not starts):
        if not starts:
            st.markdown(
                "Mirra doesn't hold any cycle data — no table in the schema "
                "records one, and Oura's cycle features aren't among the fields "
                "Mirra syncs. Log the first day of a period below and this lens "
                "starts working; two or three cycles make it useful."
            )
        col_input, col_button = st.columns([2, 1])
        with col_input:
            new_day = st.date_input("First day of a period", value=None,
                                    max_value=date.today(), key="cycle_new_start",
                                    format="YYYY-MM-DD")
        with col_button:
            st.markdown('<div style="height:1.75rem"></div>', unsafe_allow_html=True)
            if st.button("Log start date", width="stretch",
                         key="cycle_add", disabled=new_day is None):
                try:
                    idata.save_cycle_start(supabase, user_id, new_day)
                except Exception as e:
                    _render_cycle_migration_help(e)
                else:
                    st.cache_data.clear()
                    st.rerun()

        if starts:
            st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
            for start in reversed(starts[-12:]):
                row_label, row_action = st.columns([3, 1])
                with row_label:
                    st.markdown(
                        f'<div style="padding-top:0.45rem; font-size:0.92rem">'
                        f'{start.isoformat()}</div>',
                        unsafe_allow_html=True,
                    )
                with row_action:
                    if st.button("Remove", key=f"cycle_del_{start.isoformat()}",
                                 width="stretch"):
                        idata.delete_cycle_start(supabase, user_id, start)
                        st.cache_data.clear()
                        st.rerun()


def _render_cycle_migration_help(error: Exception) -> None:
    st.error(
        f"Couldn't save that date: {error}\n\n"
        f"The `{idata.CYCLE_TABLE}` table is new — it ships in "
        f"`docs/migrations/cycle_logs.sql` and has to be run in the Supabase SQL "
        f"editor before this lens can store anything."
    )


def _render_phase_table(labelled: pd.DataFrame, present: list[str]) -> None:
    st.markdown('<div class="section-label">Your data by cycle phase</div>',
                unsafe_allow_html=True)
    cols = [c for c in CONTEXT_COLUMNS
            if c in labelled.columns and labelled[c].notna().sum() >= 5]
    if not cols:
        st.markdown('<div class="min-data-msg">No metrics with enough coverage to '
                    'compare across phases yet.</div>', unsafe_allow_html=True)
        return

    rows = []
    for col in cols:
        means = labelled.groupby("cycle_phase")[col].mean()
        spread = _spread_in_sd(labelled[col], means.reindex(present))
        row = {"Metric": label_of(col)}
        for phase in present:
            row[phase] = fmt(col, means.get(phase))
        row["Spread"] = "—" if spread is None else f"{spread:.1f} SD"
        row["_sort"] = -1.0 if spread is None else -spread
        rows.append(row)

    table = pd.DataFrame(rows).sort_values("_sort").drop(columns=["_sort"])
    st.dataframe(table, hide_index=True, width="stretch")
    counts = " · ".join(f"{p}: {(labelled['cycle_phase'] == p).sum()}d" for p in present)
    st.caption(f"Days per phase — {counts}. Sorted by how far apart the phases sit.")


def _render_phase_chart(labelled: pd.DataFrame, present: list[str]) -> None:
    """One metric across phases, picked by the user."""
    options = [c for c in CONTEXT_COLUMNS
               if c in labelled.columns and labelled[c].notna().sum() >= 5]
    if not options:
        return
    metric = st.selectbox("Chart a metric across phases", options,
                          format_func=label_of, key="pi_cycle_metric")

    fig = go.Figure()
    for phase in present:
        values = labelled.loc[labelled["cycle_phase"] == phase, metric].dropna()
        if values.empty:
            continue
        fig.add_trace(go.Box(
            y=values, name=phase,
            marker=dict(color=idata.PHASE_COLORS.get(phase, "#888"), size=7),
            line=dict(color=idata.PHASE_COLORS.get(phase, "#888"), width=2),
            fillcolor="rgba(0,0,0,0)",
            boxpoints="all", jitter=0.35, pointpos=0,
            hovertemplate=f"{phase}<br>%{{y:.1f}}<extra></extra>",
            showlegend=False,
        ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=340, margin=dict(l=10, r=10, t=10, b=30),
        xaxis=dict(showgrid=False, color="#666"),
        yaxis=dict(title=label_of(metric), showgrid=True, gridcolor="#ece9df",
                   zeroline=False, color="#999"),
    )
    st.plotly_chart(fig, width="stretch", key="pi_cycle_box")


def _render_cluster_vs_phase(labelled: pd.DataFrame, present: list[str]) -> None:
    """Do the groups your data falls into line up with your cycle?

    This is the "clustering model that captures other data sources based on your
    cycle" part: cluster on everything EXCEPT cycle columns, then cross-tab the
    result against phase. Alignment means the phase is visible in the rest of
    your data; no alignment is an equally real answer.
    """
    feature_cols = [c for c in ("sleep_score", "sleep_hours", "hrv_avg", "resting_hr",
                               "mood", "activity_score")
                    if c in labelled.columns]
    matrix = labelled[feature_cols].dropna() if feature_cols else pd.DataFrame()
    if len(matrix) < MIN_DAYS_FOR_CLUSTERING:
        st.caption(
            f"Cross-checking your cycle against discovered clusters needs "
            f"{MIN_DAYS_FOR_CLUSTERING} days with sleep, mood and activity all "
            f"recorded — you have {len(matrix)}."
        )
        return

    result = _fit_clusters(matrix)
    if result is None:
        return
    labels, k, silhouette, z_profiles = result
    names = _name_clusters(z_profiles, feature_cols)

    cross = pd.DataFrame({
        "phase": labelled.loc[matrix.index, "cycle_phase"],
        "cluster": labels,
    })
    counts = pd.crosstab(cross["phase"], cross["cluster"])
    counts = counts.reindex([p for p in present if p in counts.index])
    if counts.empty:
        return
    shares = counts.div(counts.sum(axis=1), axis=0) * 100

    st.markdown('<div class="section-label">Do your clusters follow your cycle?</div>',
                unsafe_allow_html=True)
    fig = go.Figure()
    for cluster_id in counts.columns:
        fig.add_trace(go.Bar(
            x=counts.index.tolist(), y=shares[cluster_id].values,
            name=names[cluster_id],
            marker=dict(color=CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)],
                        line=dict(width=2, color="#faf9f5")),
            hovertemplate="%{x}<br>" + names[cluster_id] +
                          ": %{y:.0f}% of days<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack",
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=320, margin=dict(l=10, r=10, t=10, b=30),
        xaxis=dict(showgrid=False, color="#666"),
        yaxis=dict(title="% of days in phase", showgrid=True, gridcolor="#ece9df",
                   zeroline=False, color="#999", range=[0, 100]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, width="stretch", key="pi_cycle_cross")

    dominant = shares.max(axis=1)
    peak_phase = dominant.idxmax()
    st.caption(
        f"Clusters built from sleep, mood and activity — cycle was not an input. "
        f"If the bars looked the same in every phase, your cycle isn't visible in "
        f"these metrics. Here the clearest lean is **{peak_phase}**, where "
        f"{dominant.max():.0f}% of days fall into one group. With "
        f"{len(matrix)} days and a silhouette of {silhouette:.2f}, treat it as a "
        f"hypothesis to watch, not a result."
    )
