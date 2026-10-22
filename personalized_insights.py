"""Personalized Insights — clustering lenses over the user's own daily record.

A "lens" is a named feature set: the columns that define what a grouping is
*about*. Cluster on sleep columns and you get sleep archetypes; cluster on mood
columns and you get mood categories. The lens list is the answer to "predefined
clusters based on features of importance", and the user's focus areas
(focus_areas.py, falling back to the inquiry priorities) pick which one opens
first.

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

The user's insight style (insight_style.py, switchable from the toggle at the
top right) decides the presentation, never the method — always k-means on
standardized inputs:
  • Data-driven     — a map of every day coloured by group (PCA of the inputs),
                      quick insights beside it, the silhouette for each k, mean
                      and median per group for the inputs and for every other
                      measure, a stacked histogram of any other measure, and a
                      timeline. The only layout with a parameter: auto k or a
                      fixed k.
  • Hybrid          — a plain statement of the model and its k, one simple
                      chart of how the days split, descriptive insights beside
                      it, and the whole data-driven layout in "Dive deeper".
  • Insight-focused — the groups named by quality for the lens (good vs poor
                      sleep, calmer vs more strained days…) with share of days,
                      key stats and timing; what else moves with them ("mood
                      averages 1.8 points higher on good-sleep days"); basic
                      charts; a research button per finding (greyed out until
                      the literature reviews exist); and "Dive deeper".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import focus_areas
import insight_style
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
    "rem_sleep_min":     ("REM sleep", " min", 0),
    "deep_sleep_min":    ("Deep sleep", " min", 0),
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
    "sleep_score", "sleep_hours", "rem_sleep_min", "deep_sleep_min",
    "hrv_avg", "resting_hr", "readiness_score", "activity_score", "steps",
    "listening_minutes", "track_count", "tempo", "valence", "energy",
    "word_count",
]

# Which way is "better" for a feature: +1 higher, -1 lower. Used only to rank a
# lens's groups from best to worst for the plain-language names; features with
# no good direction (intensity, word count) are left out of that ranking.
FEATURE_DIRECTION = {
    "sleep_score": 1, "sleep_hours": 1, "rem_sleep_min": 1, "deep_sleep_min": 1,
    "hrv_avg": 1, "resting_hr": -1, "readiness_score": 1,
    "activity_score": 1, "steps": 1,
    "mood": 1, "feel_positive": 1, "feel_negative": -1, "productivity": 1,
}


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
    # Plain names for the best / worst / in-between groups, and what a "day"
    # is called in sentences ("3 kinds of sleep day").
    good: str = "Better days"
    bad: str = "Harder days"
    middle: str = "In-between days"
    noun: str = "day"


LENSES: list[Lens] = [
    Lens(
        key="sleep",
        label="Sleep quality",
        blurb="Groups your nights by how you actually slept — score, duration, "
              "REM and deep sleep, HRV and resting heart rate together, rather "
              "than one number at a time.",
        features=("sleep_score", "sleep_hours", "rem_sleep_min", "deep_sleep_min",
                  "hrv_avg", "resting_hr"),
        good="Good-sleep days", bad="Poor-sleep days", middle="Middling-sleep days",
        noun="sleep",
    ),
    Lens(
        key="stress",
        label="Stress signals",
        blurb="Groups your days by the signals that move with stress — HRV, "
              "resting heart rate, and how strongly you logged hard feelings.",
        features=("hrv_avg", "resting_hr", "feel_negative"),
        caveat="Mirra doesn't measure stress directly. These groups are built "
               "from HRV, resting heart rate and the hard feelings (stressed, "
               "anxious, overwhelmed…) you logged — signals that tend to move "
               "with stress, not a stress score.",
        good="Calmer days", bad="More strained days", middle="In-between days",
        noun="stress",
    ),
    Lens(
        key="mood",
        label="Mood categories",
        blurb="Groups your days by your rating and the feelings you named, so "
              "\"a 6\" splits into the different kinds of 6 you actually have.",
        features=("mood", "feel_positive", "feel_negative", "feel_intensity"),
        good="Brighter days", bad="Heavier days", middle="In-between days",
        noun="mood",
    ),
    Lens(
        key="activity",
        label="Activity level",
        blurb="Groups your days by movement — Oura's activity score alongside "
              "raw step count.",
        features=("activity_score", "steps"),
        good="More active days", bad="Less active days",
        middle="Moderately active days", noun="activity",
    ),
    Lens(
        key="productivity",
        label="Productivity level",
        blurb="Groups your days by a productivity estimate built from your own "
              "words and your self-reported focus.",
        features=("productivity", "mood", "word_count"),
        good="More productive days", bad="Less productive days",
        middle="In-between days", noun="productivity",
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
    title_col, toggle_col = st.columns([3, 2], vertical_alignment="bottom")
    with title_col:
        st.markdown('<p class="title-text">Personalized Insights</p>',
                    unsafe_allow_html=True)
    with toggle_col:
        style = insight_style.render_style_toggle(supabase, user_id, where="pi")
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
    areas = focus_areas.load_focus_areas(supabase, user_id, priorities, df)
    default_key = _default_lens_key(areas, priorities)
    _render_focus_banner(areas, default_key)

    keys = [lens.key for lens in LENSES]
    chosen = st.selectbox(
        "Cluster by",
        options=keys,
        index=keys.index(default_key),
        format_func=lambda k: LENS_BY_KEY[k].label,
        key="pi_lens",
    )
    lens = LENS_BY_KEY[chosen]

    windows = list(idata.WINDOW_OPTIONS.keys())
    window_label = st.selectbox("Time range", windows,
                                index=windows.index("All time"), key="pi_window")
    windowed = idata.apply_window(df, idata.WINDOW_OPTIONS[window_label])

    st.markdown(f'<div class="insight-card">{lens.blurb}</div>', unsafe_allow_html=True)
    if lens.caveat:
        st.warning(lens.caveat)

    if lens.method == "cycle":
        _render_cycle_lens(supabase, user_id, windowed, style)
    else:
        _render_kmeans_lens(lens, windowed, style)


# Focus areas (focus_areas.py) → the lens that clusters on them.
AREA_LENS = {focus_areas.SLEEP: "sleep", focus_areas.STRESS: "stress",
             focus_areas.MOOD: "mood"}


def _default_lens_key(areas: list[str], priorities: list[str]) -> str:
    """Open on the lens for the user's first focus area, else their priorities."""
    for area in areas:
        if AREA_LENS.get(area) in LENS_BY_KEY:
            return AREA_LENS[area]
    for key in idata.priority_lens_keys(priorities):
        if key in LENS_BY_KEY:
            return key
    return "sleep"


def _render_focus_banner(areas: list[str], default_key: str) -> None:
    chips = " · ".join(focus_areas.label(a) for a in areas)
    st.markdown(
        f'<div style="background:#f0f8f4; border:1px solid #c9e4d6; border-radius:8px;'
        f'padding:0.65rem 1rem; font-size:0.9rem; color:#1e6b45; margin-bottom:0.9rem">'
        f'<strong>Your focus:</strong> {chips} — opening on '
        f'<strong>{LENS_BY_KEY[default_key].label}</strong>. Change it in Profile → '
        f'Personalization.</div>',
        unsafe_allow_html=True,
    )


# ── K-means lenses ───────────────────────────────────────────────────────────
@dataclass
class ClusterModel:
    """One fitted lens, plus everything the three layouts read from it."""
    assigned: pd.DataFrame          # the clustered days, with a "_cluster" column
    features: list[str]
    X: np.ndarray                   # standardized feature matrix, row-aligned
    k: int
    silhouette: float
    sweep: dict[int, float]         # silhouette for every k that was tried
    auto_k: bool
    z_profiles: pd.DataFrame
    order: list[int]                # cluster ids, best → worst for this lens
    names: dict[int, str]           # what the layouts call each group


def _render_kmeans_lens(lens: Lens, df: pd.DataFrame,
                        style: str = insight_style.DEFAULT_STYLE) -> None:
    features, left_out = _usable_features(lens, df)
    if not features:
        st.markdown(
            f'<div class="min-data-msg">None of this lens\'s inputs '
            f'({", ".join(label_of(c) for c in lens.features)}) exist in your data '
            f'yet.</div>',
            unsafe_allow_html=True,
        )
        return

    # Clustering needs complete rows — a day missing one feature can't be placed.
    matrix = df[features].dropna()
    if len(matrix) < MIN_DAYS_FOR_CLUSTERING:
        st.markdown(
            f'<div class="min-data-msg">This lens needs at least '
            f'<strong>{MIN_DAYS_FOR_CLUSTERING} days</strong> where '
            f'{", ".join(label_of(c) for c in features)} were all recorded. '
            f'You have <strong>{len(matrix)}</strong>.</div>',
            unsafe_allow_html=True,
        )
        return
    if left_out:
        st.caption("Left out because they're missing on too many days: "
                   + ", ".join(label_of(c) for c in left_out) + ".")

    # The model's parameters are a data-driven control; the other two layouts
    # always let the silhouette sweep choose.
    requested_k = _render_k_control(len(matrix)) if style == insight_style.DATA_DRIVEN else None

    model = _build_model(lens, df, matrix, requested_k,
                         quality_names=style != insight_style.DATA_DRIVEN)
    if model is None:
        st.markdown(
            '<div class="min-data-msg">Your days in this range are too similar to '
            'split into meaningful groups — which is itself an answer.</div>',
            unsafe_allow_html=True,
        )
        return

    if style == insight_style.DATA_DRIVEN:
        _render_data_driven(model, prefix="dd")
    elif style == insight_style.HYBRID:
        _render_hybrid(model, lens)
    else:
        _render_insight_focused(model, lens)


def _usable_features(lens: Lens, df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Lens inputs worth clustering on, and the ones dropped for thin coverage.

    REM and deep sleep only exist on days Oura reported a detailed sleep period,
    so requiring them everywhere would throw away most of the record. A feature
    is kept when it's present on at least half as many days as the best-covered
    input.
    """
    present = {c: idata.coverage(df, c) for c in lens.features if c in df.columns}
    present = {c: n for c, n in present.items() if n > 0}
    if not present:
        return [], []
    floor = max(present.values()) * 0.5
    keep = [c for c in lens.features if present.get(c, 0) >= floor and c in present]
    dropped = [c for c in lens.features if c in present and c not in keep]
    return keep, dropped


def _render_k_control(n_days: int) -> Optional[int]:
    """Auto (silhouette) or a fixed number of groups."""
    max_k = min(MAX_CLUSTERS, n_days // MIN_DAYS_PER_GROUP)
    options = ["Auto"] + [str(k) for k in range(2, max_k + 1)]
    choice = st.radio(
        "Number of groups", options, index=0, horizontal=True, key="pi_k",
        help="Auto tries every group count and keeps the one whose groups are "
             "most distinct (highest silhouette). Pick a number to force it.",
    )
    return None if choice == "Auto" else int(choice)


def _build_model(lens: Lens, df: pd.DataFrame, matrix: pd.DataFrame,
                 requested_k: Optional[int], quality_names: bool) -> Optional[ClusterModel]:
    result = _fit_clusters(matrix, requested_k)
    if result is None:
        return None
    labels, k, silhouette, z_profiles, X, sweep = result
    assigned = df.loc[matrix.index].copy()
    assigned["_cluster"] = labels
    features = list(matrix.columns)
    order = _quality_order(z_profiles, features, assigned)
    names = (_quality_names(lens, order) if quality_names
             else _name_clusters(z_profiles, features))
    return ClusterModel(assigned=assigned, features=features, X=X, k=k,
                        silhouette=silhouette, sweep=sweep,
                        auto_k=requested_k is None, z_profiles=z_profiles,
                        order=order, names=names)


def _fit_clusters(matrix: pd.DataFrame, requested_k: Optional[int] = None):
    """Standardize, sweep k by silhouette, fit. None if nothing separates.

    With requested_k the sweep still runs (data-driven shows it) but that k is
    used, clamped to what the data can support.
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    X = StandardScaler().fit_transform(matrix.values)
    if np.allclose(X.std(axis=0), 0):
        return None

    max_k = min(MAX_CLUSTERS, len(matrix) // MIN_DAYS_PER_GROUP)
    if max_k < 2:
        return None

    fits: dict[int, tuple[np.ndarray, float]] = {}
    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(X)
        if len(set(labels)) < k:
            continue
        fits[k] = (labels, float(silhouette_score(X, labels)))
    if not fits:
        return None

    if requested_k is not None and requested_k in fits:
        k = requested_k
    else:
        k = max(fits, key=lambda kk: fits[kk][1])
    labels, score = fits[k]
    # Report profiles in standard deviations so features on different scales are
    # comparable; the cards alongside show the same thing in real units.
    z = pd.DataFrame(X, index=matrix.index, columns=matrix.columns)
    z["_cluster"] = labels
    z_profiles = z.groupby("_cluster").mean()
    return labels, k, score, z_profiles, X, {kk: s for kk, (_, s) in fits.items()}


# ── Naming and ranking the groups ────────────────────────────────────────────
def _quality_order(z_profiles: pd.DataFrame, features: list[str],
                   assigned: pd.DataFrame) -> list[int]:
    """Cluster ids from best to worst for the lens, by its directional features.

    "Best" = highest average of each feature's z-score, signed so that higher is
    better (resting HR and hard feelings count downward). With no directional
    feature, groups are ordered by size instead.
    """
    directional = [c for c in features if FEATURE_DIRECTION.get(c)]
    if not directional:
        counts = assigned["_cluster"].value_counts()
        return [int(c) for c in counts.index]
    score = {
        int(cid): float(np.mean([FEATURE_DIRECTION[c] * row[c] for c in directional]))
        for cid, row in z_profiles.iterrows()
    }
    return sorted(score, key=lambda cid: -score[cid])


def _quality_names(lens: Lens, order: list[int]) -> dict[int, str]:
    """Plain names: the lens's good / middle / bad labels along the ranking."""
    names: dict[int, str] = {}
    for rank, cid in enumerate(order):
        if rank == 0:
            names[cid] = lens.good
        elif rank == len(order) - 1:
            names[cid] = lens.bad
        else:
            middle_rank = rank if len(order) > 3 else 0
            names[cid] = lens.middle + (f" ({middle_rank})" if middle_rank else "")
    return names


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


def _color(cluster_id: int) -> str:
    return CLUSTER_COLORS[cluster_id % len(CLUSTER_COLORS)]


# ── Shared statistics ────────────────────────────────────────────────────────
def _verdict(silhouette: float) -> tuple[str, str]:
    if silhouette >= 0.5:
        return "well separated", "#2a8a5e"
    if silhouette >= 0.25:
        return "moderately separated", "#d4850a"
    return "weakly separated — treat as suggestive only", "#e05a3a"


def _other_columns(model: ClusterModel) -> list[str]:
    """Measures NOT clustered on, with enough days to compare."""
    return [c for c in CONTEXT_COLUMNS
            if c not in model.features and c in model.assigned.columns
            and model.assigned[c].notna().sum() >= MIN_DAYS_FOR_CLUSTERING]


def _contrast_stats(model: ClusterModel) -> list[tuple[str, pd.Series, pd.Series, Optional[float]]]:
    """(column, per-group means, per-group medians, spread in SD) for the
    columns NOT clustered on, widest spread first."""
    stats = []
    grouped = model.assigned.groupby("_cluster")
    for col in _other_columns(model):
        means = grouped[col].mean().reindex(model.order)
        medians = grouped[col].median().reindex(model.order)
        stats.append((col, means, medians, _spread_in_sd(model.assigned[col], means)))
    return sorted(stats, key=lambda t: -1.0 if t[3] is None else -t[3])


def _spread_in_sd(series: pd.Series, group_means: pd.Series) -> Optional[float]:
    """Range of group means, in standard deviations of the whole column."""
    sd = series.std()
    if not sd or np.isnan(sd) or group_means.isna().all():
        return None
    return float((group_means.max() - group_means.min()) / sd)


def _shares(model: ClusterModel) -> dict[int, float]:
    counts = model.assigned["_cluster"].value_counts()
    return {cid: 100 * counts.get(cid, 0) / len(model.assigned) for cid in model.order}


def _timing_note(model: ClusterModel, cluster_id: int) -> Optional[str]:
    """When a group tends to happen: lately vs earlier, weekends vs weekdays."""
    days = model.assigned
    member = days["_cluster"] == cluster_id
    notes = []

    midpoint = days.index[len(days) // 2]
    recent, earlier = days.index >= midpoint, days.index < midpoint
    if recent.sum() and earlier.sum():
        now_share = member[recent].mean() * 100
        then_share = member[earlier].mean() * 100
        if now_share - then_share >= 15:
            notes.append(f"more common lately ({now_share:.0f}% of recent days vs "
                         f"{then_share:.0f}% earlier)")
        elif then_share - now_share >= 15:
            notes.append(f"less common lately ({now_share:.0f}% of recent days vs "
                         f"{then_share:.0f}% earlier)")

    weekend = days.index.dayofweek >= 5
    if member.sum() and weekend.any() and (~weekend).any():
        lean = weekend[member.values].mean() - weekend.mean()
        if lean >= 0.2:
            notes.append("leans toward weekends")
        elif lean <= -0.2:
            notes.append("mostly on weekdays")
    return "; ".join(notes) if notes else None


def _delta_text(col: str, diff: float) -> str:
    """A difference in natural units: scores and ratings as points."""
    _, unit, digits = FEATURE_META.get(col, (col, "", 1))
    if unit in ("", "/10"):
        return f"{abs(diff):.{digits}f} points"
    return fmt(col, abs(diff))


def _linked_characteristics(model: ClusterModel, limit: int = 3) -> list[dict]:
    """How measures outside the model differ between the best and worst group."""
    if len(model.order) < 2:
        return []
    best, worst = model.order[0], model.order[-1]
    out = []
    for col, means, _, _ in _contrast_stats(model):
        sd = model.assigned[col].std()
        if not sd or np.isnan(sd) or pd.isna(means[best]) or pd.isna(means[worst]):
            continue
        diff = float(means[best] - means[worst])
        if abs(diff) / sd < 0.3:
            continue
        out.append({"col": col, "best": float(means[best]), "worst": float(means[worst]),
                    "diff": diff, "size": abs(diff) / sd})
    return sorted(out, key=lambda d: -d["size"])[:limit]


def _linked_sentence(model: ClusterModel, link: dict) -> str:
    best, worst = model.names[model.order[0]], model.names[model.order[-1]]
    direction = "higher" if link["diff"] > 0 else "lower"
    return (f"{label_of(link['col'])} averages "
            f"<strong>{_delta_text(link['col'], link['diff'])} {direction}</strong> "
            f"on {best.lower()} than on {worst.lower()} "
            f"({fmt(link['col'], link['best'])} vs {fmt(link['col'], link['worst'])}).")


def _key_stats(model: ClusterModel, cluster_id: int, limit: int = 3) -> str:
    """The inputs that most set this group apart, in real units."""
    row = model.z_profiles.loc[cluster_id]
    member = model.assigned[model.assigned["_cluster"] == cluster_id]
    ranked = sorted(model.features, key=lambda c: -abs(row[c]))[:limit]
    return " · ".join(f"{label_of(c)} {fmt(c, member[c].mean())}" for c in ranked)


def _render_bullets(lines: list[str], header: Optional[str] = None) -> None:
    items = "".join(f'<li style="margin-bottom:0.45rem">{t}</li>' for t in lines)
    head = f'<div class="insight-header">{header}</div>' if header else ""
    st.markdown(
        f'<div class="insight-card">{head}<ul style="margin:0; padding-left:1.1rem">'
        f'{items}</ul></div>',
        unsafe_allow_html=True,
    )


def _render_research_button(key: str) -> None:
    # Literature reviews are still being written; same placeholder as Simples.
    st.button("Research — coming soon", key=f"pi_research_{key}", disabled=True)


# ── Data-driven ──────────────────────────────────────────────────────────────
def _render_data_driven(model: ClusterModel, prefix: str) -> None:
    _render_quality_line(model)
    visual, notes = st.columns([3, 2])
    with visual:
        _render_cluster_map(model, prefix)
    with notes:
        _render_bullets(_quick_insights(model), header="Quick insights")
        if len(model.sweep) > 1:
            _render_sweep(model, prefix)
    _render_cluster_cards(model)
    _render_z_heatmap(model, prefix)
    _render_other_measures(model)
    _render_stacked_histogram(model, prefix)
    _render_timeline(model, prefix)


def _render_quality_line(model: ClusterModel) -> None:
    verdict, tone = _verdict(model.silhouette)
    how = "chosen automatically" if model.auto_k else "set by you"
    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.2rem 0 1rem">'
        f'K-means · <strong>{model.k} groups</strong> ({how}) across '
        f'<strong>{len(model.assigned)} days</strong> · silhouette '
        f'{model.silhouette:.2f} — <span style="color:{tone}">{verdict}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _quick_insights(model: ClusterModel) -> list[str]:
    """Terse, numbers-first notes for the data-driven layout."""
    shares = _shares(model)
    biggest = max(shares, key=shares.get)
    lines = [f"Largest group: <strong>{model.names[biggest]}</strong>, "
             f"{shares[biggest]:.0f}% of days."]
    contrasts = [c for c in _contrast_stats(model) if c[3] is not None]
    for col, means, _, spread in contrasts[:2]:
        if spread < 0.5:
            break
        hi, lo = means.idxmax(), means.idxmin()
        lines.append(f"{label_of(col)} (not a model input) spans {spread:.1f} SD: "
                     f"{fmt(col, means[hi])} in {model.names[hi]} vs "
                     f"{fmt(col, means[lo])} in {model.names[lo]}.")
    if model.sweep:
        best_k = max(model.sweep, key=model.sweep.get)
        if not model.auto_k and best_k != model.k:
            lines.append(f"Silhouette is highest at k = {best_k} "
                         f"({model.sweep[best_k]:.2f}); you're viewing k = {model.k}.")
    return lines


def _render_cluster_map(model: ClusterModel, prefix: str) -> None:
    """Every day as a dot, placed by the model's inputs (PCA to two axes)."""
    st.markdown('<div class="section-label" style="margin-top:0">Your days, grouped</div>',
                unsafe_allow_html=True)
    if model.X.shape[1] < 2:
        st.caption("One input only, so there's no map to draw — see the cards below.")
        return
    from sklearn.decomposition import PCA

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(model.X)

    def _axis_title(i: int) -> str:
        loadings = pca.components_[i]
        top = np.argsort(-np.abs(loadings))[:2]
        share = pca.explained_variance_ratio_[i] * 100
        return (f"Axis {i + 1}: mostly "
                f"{' & '.join(label_of(model.features[j]) for j in top)} ({share:.0f}%)")

    labels = model.assigned["_cluster"].values
    fig = go.Figure()
    for cid in model.order:
        mask = labels == cid
        fig.add_trace(go.Scatter(
            x=coords[mask, 0], y=coords[mask, 1], mode="markers",
            name=model.names[cid],
            marker=dict(size=9, color=_color(cid), line=dict(width=1, color="#faf9f5")),
            customdata=[d.strftime("%b %d, %Y") for d in model.assigned.index[mask]],
            hovertemplate="%{customdata}<br>" + model.names[cid] + "<extra></extra>",
        ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a", size=11),
        height=360, margin=dict(l=10, r=10, t=10, b=40),
        xaxis=dict(title=_axis_title(0), showgrid=True, gridcolor="#ece9df",
                   zeroline=False, showticklabels=False, color="#888"),
        yaxis=dict(title=_axis_title(1), showgrid=True, gridcolor="#ece9df",
                   zeroline=False, showticklabels=False, color="#888"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, width="stretch", key=f"pi_map_{prefix}")
    st.caption("Days close together had similar readings across all of this lens's "
               "inputs. The axes are blends of those inputs, so they have no units.")


def _render_sweep(model: ClusterModel, prefix: str) -> None:
    ks = sorted(model.sweep)
    fig = go.Figure(go.Bar(
        x=[str(k) for k in ks], y=[model.sweep[k] for k in ks],
        marker=dict(color=["#3dab7a" if k == model.k else "#d9d6cc" for k in ks]),
        hovertemplate="k = %{x}<br>silhouette %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a", size=11),
        height=170, margin=dict(l=10, r=10, t=24, b=30),
        title=dict(text="Silhouette by number of groups", font=dict(size=12), x=0),
        xaxis=dict(title="k", color="#888"),
        yaxis=dict(showgrid=True, gridcolor="#ece9df", zeroline=False, color="#888"),
    )
    st.plotly_chart(fig, width="stretch", key=f"pi_sweep_{prefix}",
                    config={"displayModeBar": False})


def _render_cluster_cards(model: ClusterModel) -> None:
    """Central tendency of the model's inputs, per group: mean and median."""
    st.markdown('<div class="section-label">The groups</div>', unsafe_allow_html=True)
    shares = _shares(model)
    for row_start in range(0, len(model.order), 2):
        cols = st.columns(2)
        for col, cid in zip(cols, model.order[row_start:row_start + 2]):
            member = model.assigned[model.assigned["_cluster"] == cid]
            stats = "".join(
                f'<div style="display:flex; justify-content:space-between; '
                f'font-size:0.88rem; padding:2px 0">'
                f'<span style="color:#666">{label_of(f)}</span>'
                f'<span style="color:#1a1a1a; font-weight:500">'
                f'{fmt(f, member[f].mean())} '
                f'<span style="color:#aaa; font-weight:400">· {fmt(f, member[f].median())}'
                f'</span></span></div>'
                for f in model.features
            )
            with col:
                st.markdown(
                    f'<div style="background:white; border:1px solid #ece9df; '
                    f'border-left:3px solid {_color(cid)}; border-radius:12px; '
                    f'padding:1rem 1.1rem; margin-bottom:0.7rem; height:100%">'
                    f'<div style="font-family:\'Lora\',serif; font-size:1.05rem; '
                    f'font-weight:600; color:#1a1a1a; margin-bottom:0.2rem">'
                    f'{model.names[cid]}</div>'
                    f'<div style="font-size:0.8rem; color:#aaa; margin-bottom:0.7rem">'
                    f'{(model.assigned["_cluster"] == cid).sum()} days · '
                    f'{shares[cid]:.0f}% of the range · mean · median</div>'
                    f'{stats}</div>',
                    unsafe_allow_html=True,
                )


def _render_z_heatmap(model: ClusterModel, prefix: str) -> None:
    """Each group's fingerprint in standard deviations from your own average."""
    st.markdown('<div class="section-label">Group fingerprints</div>',
                unsafe_allow_html=True)
    z = model.z_profiles.loc[model.order, model.features]
    limit = float(np.abs(z.values).max()) or 1.0
    fig = go.Figure(go.Heatmap(
        z=z.values,
        x=[label_of(c) for c in model.features],
        y=[model.names[i] for i in z.index],
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
    st.plotly_chart(fig, width="stretch", key=f"pi_heatmap_{prefix}")
    st.caption("Warm = above your own average for that feature, cool = below. "
               "Measured in standard deviations, so features on different scales "
               "can sit side by side.")


def _render_other_measures(model: ClusterModel) -> None:
    """Central tendency of the measures NOT clustered on — where the insight is."""
    contrasts = _contrast_stats(model)
    if not contrasts:
        return
    st.markdown('<div class="section-label">Other measures by group</div>',
                unsafe_allow_html=True)
    st.caption("Mean (median) per group. None of these were used to build the "
               "groups, so a real gap here is the grouping telling you something.")
    rows = []
    for col, means, medians, spread in contrasts:
        row = {"Measure": label_of(col)}
        for cid in model.order:
            row[model.names[cid]] = f"{fmt(col, means.get(cid))} ({fmt(col, medians.get(cid))})"
        row["Spread"] = "—" if spread is None else f"{spread:.1f} SD"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_stacked_histogram(model: ClusterModel, prefix: str) -> None:
    """One other measure's distribution, stacked by group."""
    options = _other_columns(model)
    if not options:
        return
    st.markdown('<div class="section-label">Distribution by group</div>',
                unsafe_allow_html=True)
    default = options.index("resting_hr") if "resting_hr" in options else 0
    col = st.selectbox("Measure", options, index=default, format_func=label_of,
                       key=f"pi_hist_{prefix}")
    fig = go.Figure()
    for cid in model.order:
        values = model.assigned.loc[model.assigned["_cluster"] == cid, col].dropna()
        fig.add_trace(go.Histogram(
            x=values, name=model.names[cid], nbinsx=15,
            marker=dict(color=_color(cid), line=dict(width=1, color="#faf9f5")),
            hovertemplate=model.names[cid] + "<br>%{x}: %{y} days<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack",
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=300, margin=dict(l=10, r=10, t=10, b=30),
        xaxis=dict(title=label_of(col), showgrid=False, color="#888"),
        yaxis=dict(title="days", showgrid=True, gridcolor="#ece9df",
                   zeroline=False, color="#888"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, width="stretch", key=f"pi_histogram_{prefix}")


def _render_timeline(model: ClusterModel, prefix: str) -> None:
    st.markdown('<div class="section-label">When each group happened</div>',
                unsafe_allow_html=True)
    fig = go.Figure()
    for cid in model.order:
        member = model.assigned[model.assigned["_cluster"] == cid]
        fig.add_trace(go.Scatter(
            x=member.index, y=[model.names[cid]] * len(member),
            mode="markers",
            name=model.names[cid],
            marker=dict(size=9, color=_color(cid), line=dict(width=1.5, color="#faf9f5")),
            hovertemplate="%{x|%b %d, %Y}<br>" + model.names[cid] + "<extra></extra>",
        ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=90 + 42 * len(model.order), margin=dict(l=10, r=10, t=10, b=30),
        xaxis=dict(showgrid=True, gridcolor="#ece9df", color="#999"),
        yaxis=dict(showgrid=False, color="#666", automargin=True,
                   categoryorder="array",
                   categoryarray=[model.names[c] for c in reversed(model.order)]),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch", key=f"pi_timeline_{prefix}")


# ── Hybrid ───────────────────────────────────────────────────────────────────
def _render_hybrid(model: ClusterModel, lens: Lens) -> None:
    verdict, tone = _verdict(model.silhouette)
    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.2rem 0 1rem">'
        f'K-means found <strong>{model.k} kinds of {lens.noun} day</strong> in '
        f'{len(model.assigned)} days — {model.k} was the best-separated group count '
        f'(silhouette {model.silhouette:.2f}, <span style="color:{tone}">{verdict}</span>).'
        f'</div>',
        unsafe_allow_html=True,
    )
    visual, notes = st.columns([3, 2])
    with visual:
        _render_share_bars(model, "hy")
    with notes:
        _render_bullets(_descriptive_insights(model), header="What this suggests")
    with st.expander("Dive deeper — see the full data"):
        _render_data_driven(model, prefix="hy_full")


def _render_share_bars(model: ClusterModel, prefix: str) -> None:
    """The simplest honest summary: how your days split, and what defines each."""
    shares = _shares(model)
    names = [model.names[c] for c in model.order]
    fig = go.Figure(go.Bar(
        y=names, x=[shares[c] for c in model.order], orientation="h",
        marker=dict(color=[_color(c) for c in model.order]),
        text=[f"{shares[c]:.0f}%" for c in model.order], textposition="outside",
        customdata=[_key_stats(model, c) for c in model.order],
        hovertemplate="%{y}: %{x:.0f}% of days<br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=80 + 50 * len(names), margin=dict(l=10, r=40, t=10, b=30),
        xaxis=dict(title="% of days", showgrid=False, color="#999",
                   range=[0, max(shares.values()) * 1.25]),
        yaxis=dict(autorange="reversed", color="#444", automargin=True),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch", key=f"pi_shares_{prefix}",
                    config={"displayModeBar": False})
    for cid in model.order:
        st.caption(f"**{model.names[cid]}** — {_key_stats(model, cid)}")


def _descriptive_insights(model: ClusterModel) -> list[str]:
    shares = _shares(model)
    best, worst = model.order[0], model.order[-1]
    lines = [f"<strong>{model.names[best]}</strong> make up {shares[best]:.0f}% of "
             f"your days; <strong>{model.names[worst].lower()}</strong> "
             f"{shares[worst]:.0f}%."]
    lines += [_linked_sentence(model, link) for link in _linked_characteristics(model, 2)]
    for cid in (best, worst):
        note = _timing_note(model, cid)
        if note:
            lines.append(f"{model.names[cid]} are {note}.")
    if model.silhouette < 0.25:
        lines.append("The groups overlap a lot, so read these as hunches to watch, "
                     "not conclusions.")
    return lines


# ── Insight-focused ──────────────────────────────────────────────────────────
def _render_insight_focused(model: ClusterModel, lens: Lens) -> None:
    links = _linked_characteristics(model)
    _render_bullets(_insight_summary(model, lens, links), header="In short")

    st.markdown('<div class="section-label">Your groups</div>', unsafe_allow_html=True)
    shares = _shares(model)
    cols = st.columns(min(len(model.order), 3))
    for i, cid in enumerate(model.order):
        timing = _timing_note(model, cid)
        with cols[i % len(cols)]:
            st.markdown(
                f'<div style="background:white; border:1px solid #ece9df; '
                f'border-top:3px solid {_color(cid)}; border-radius:12px; '
                f'padding:0.9rem 1rem; margin-bottom:0.7rem">'
                f'<div style="font-size:0.66rem; font-weight:600; color:#999; '
                f'letter-spacing:0.14em; text-transform:uppercase">{model.names[cid]}</div>'
                f'<div style="font-family:\'Lora\',serif; font-size:1.6rem; '
                f'font-weight:600; color:#1a1a1a; line-height:1.1">{shares[cid]:.0f}%'
                f'<span style="font-size:0.8rem; color:#aaa; font-family:\'DM Sans\'">'
                f' of days</span></div>'
                f'<div style="font-size:0.84rem; color:#555; margin-top:0.4rem">'
                f'{_key_stats(model, cid)}</div>'
                + (f'<div style="font-size:0.78rem; color:#888; margin-top:0.35rem">'
                   f'{timing[0].upper() + timing[1:]}</div>' if timing else "")
                + '</div>',
                unsafe_allow_html=True,
            )

    donut, bars = st.columns(2)
    with donut:
        _render_share_donut(model)
    with bars:
        if links:
            _render_linked_bars(model, links)

    if links:
        st.markdown('<div class="section-label">What goes with it</div>',
                    unsafe_allow_html=True)
        for i, link in enumerate(links):
            text_col, button_col = st.columns([4, 1], vertical_alignment="center")
            with text_col:
                st.markdown(_linked_sentence(model, link), unsafe_allow_html=True)
            with button_col:
                _render_research_button(f"{link['col']}_{i}")

    with st.expander("Dive deeper"):
        _render_data_driven(model, prefix="if_full")


def _insight_summary(model: ClusterModel, lens: Lens, links: list[dict]) -> list[str]:
    shares = _shares(model)
    best, worst = model.order[0], model.order[-1]
    lines = [f"Your days fall into {model.k} kinds of {lens.noun} day. "
             f"<strong>{model.names[best]}</strong> happen {shares[best]:.0f}% of the "
             f"time, <strong>{model.names[worst].lower()}</strong> {shares[worst]:.0f}%."]
    if links:
        lines.append(_linked_sentence(model, links[0]))
    best_timing = _timing_note(model, best)
    if best_timing:
        lines.append(f"{model.names[best]} are {best_timing}.")
    if model.silhouette < 0.25:
        lines.append("These groups blur into each other, so treat this as a first "
                     "look rather than a firm pattern.")
    return lines


def _render_share_donut(model: ClusterModel) -> None:
    fig = go.Figure(go.Pie(
        labels=[model.names[c] for c in model.order],
        values=[(model.assigned["_cluster"] == c).sum() for c in model.order],
        marker=dict(colors=[_color(c) for c in model.order],
                    line=dict(color="#faf9f5", width=2)),
        hole=0.6, sort=False, textinfo="percent",
        hovertemplate="%{label}: %{value} days<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", font=dict(family="DM Sans", color="#2a2a2a"),
        height=260, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", y=-0.05),
    )
    st.plotly_chart(fig, width="stretch", key="pi_donut",
                    config={"displayModeBar": False})


def _render_linked_bars(model: ClusterModel, links: list[dict]) -> None:
    """The strongest linked measure, best group vs worst group."""
    link = links[0]
    best, worst = model.order[0], model.order[-1]
    fig = go.Figure(go.Bar(
        x=[model.names[best], model.names[worst]], y=[link["best"], link["worst"]],
        marker=dict(color=[_color(best), _color(worst)]),
        text=[fmt(link["col"], link["best"]), fmt(link["col"], link["worst"])],
        textposition="outside",
        hovertemplate="%{x}: %{text}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=260, margin=dict(l=10, r=10, t=30, b=30),
        title=dict(text=f"Average {label_of(link['col']).lower()}",
                   font=dict(size=12), x=0),
        yaxis=dict(visible=False,
                   range=[0, max(link["best"], link["worst"], 1e-9) * 1.25]),
        xaxis=dict(color="#666"),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch", key="pi_linked",
                    config={"displayModeBar": False})


# ── Shared by the cycle lens ─────────────────────────────────────────────────
def _evidence_container(style: str):
    """Where the charts and tables go: inline, or folded away for users who
    asked to lead with what it means."""
    if style == insight_style.INSIGHT_FOCUSED:
        return st.expander("See the data behind this")
    return st.container()


def _render_takeaways(takeaways: list[str]) -> None:
    if takeaways:
        _render_bullets(takeaways, header="What this suggests")


# ── Cycle lens ───────────────────────────────────────────────────────────────
def _render_cycle_lens(supabase, user_id: str, df: pd.DataFrame,
                       style: str = insight_style.DEFAULT_STYLE) -> None:
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
    if style != insight_style.DATA_DRIVEN:
        _render_takeaways(_phase_takeaways(labelled, present))
    with _evidence_container(style):
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


def _phase_takeaways(labelled: pd.DataFrame, present: list[str]) -> list[str]:
    """The metrics that move most across phases, in words."""
    ranked = []
    for col in CONTEXT_COLUMNS:
        if col not in labelled.columns or labelled[col].notna().sum() < 5:
            continue
        means = labelled.groupby("cycle_phase")[col].mean().reindex(present)
        spread = _spread_in_sd(labelled[col], means)
        if spread is not None and spread >= 0.5:
            ranked.append((spread, col, means))
    ranked.sort(key=lambda t: -t[0])

    out = []
    for _, col, means in ranked[:2]:
        hi, lo = means.idxmax(), means.idxmin()
        out.append(f"Your {label_of(col).lower()} shifts most with your cycle: "
                   f"highest in <strong>{hi}</strong> ({fmt(col, means[hi])}), "
                   f"lowest in <strong>{lo}</strong> ({fmt(col, means[lo])}).")
    if not out:
        out.append("So far your other data looks much the same in every phase — "
                   "your cycle isn't clearly visible in it yet.")
    return out


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
    labels, k, silhouette, z_profiles, _, _ = result
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
