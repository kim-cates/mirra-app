"""Visualization utilities and plotting functions."""

import numpy as np
import plotly.graph_objects as go
from config import TOPIC_COLORS, DENDRO_COLORS, FEELING_COLORS


def _avg_or_none(values):
    """Mean of a list treating None as missing."""
    nums = [float(v) for v in values if v is not None]
    return float(np.mean(nums)) if nums else None


def _fmt_metric(v, suffix="", digits=1):
    """Format a metric value or return '—' if None."""
    return "—" if v is None else f"{v:.{digits}f}{suffix}"


def _cluster_top_keywords(texts_in_cluster, all_texts, top_n=5):
    """TF-IDF top distinctive keywords for a cluster."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    if not texts_in_cluster:
        return []
    try:
        vec = TfidfVectorizer(
            ngram_range=(1, 2), stop_words="english",
            max_features=300, token_pattern=r"[a-zA-Z]{3,}", min_df=1,
        )
        vec.fit(all_texts)
        terms = vec.get_feature_names_out()
        cluster_vec = vec.transform(texts_in_cluster).toarray().mean(axis=0)
        corpus_vec = vec.transform(all_texts).toarray().mean(axis=0)
        distinctiveness = cluster_vec - 0.6 * corpus_vec
        top_idx = distinctiveness.argsort()[::-1][:top_n]
        return [terms[i] for i in top_idx if distinctiveness[i] > 0]
    except Exception:
        return []


def _draw_dendrogram(phrases, Z, cluster_ids):
    """Render a Plotly dendrogram figure."""
    from scipy.cluster.hierarchy import dendrogram as scipy_dendro

    ddata       = scipy_dendro(Z, labels=phrases, orientation="left", no_plot=True)
    n           = len(phrases)
    leaf_order  = ddata["leaves"]
    leaf_colors = [DENDRO_COLORS[(cluster_ids[i] - 1) % len(DENDRO_COLORS)] for i in leaf_order]
    leaf_names  = [phrases[i] for i in leaf_order]

    fig    = go.Figure()
    icoord = ddata["icoord"]
    dcoord = ddata["dcoord"]
    max_d  = max(max(d) for d in dcoord) or 1

    for xs, ys in zip(dcoord, icoord):
        xs_norm = [x / max_d for x in xs]
        fig.add_trace(go.Scatter(
            x=[-v for v in xs_norm], y=ys,
            mode="lines", line=dict(color="#cccccc", width=1.5),
            showlegend=False, hoverinfo="skip",
        ))

    y_positions = list(range(5, 10 * n + 5, 10))
    for i, (name, color) in enumerate(zip(leaf_names, leaf_colors)):
        fig.add_trace(go.Scatter(
            x=[0], y=[y_positions[i]],
            mode="markers+text",
            marker=dict(size=9, color=color),
            text=[f"   {name}"], textposition="middle right",
            textfont=dict(size=12, color="#2a2a2a", family="DM Sans"),
            showlegend=False, hoverinfo="skip",
        ))

    max_label_len = max(len(name) for name in leaf_names) if leaf_names else 10
    x_right = max_label_len * 0.018

    fig.update_layout(
        paper_bgcolor="#f7f6f2", plot_bgcolor="#f7f6f2",
        margin=dict(l=20, r=40, t=30, b=40),
        xaxis=dict(
            range=[-1.05, x_right],
            tickvals=[0, -0.25, -0.5, -0.75, -1.0],
            ticktext=["0", "0.25", "0.5", "0.75", "1.0"],
            title="cosine distance", color="#aaa",
            showgrid=True, gridcolor="#e8e8e0", zeroline=False,
        ),
        yaxis=dict(visible=False),
        height=max(420, n * 30),
        font=dict(family="DM Sans"),
    )
    return fig


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert hex color to rgba string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _render_feelings_violin_single(
    feelings_data: dict[str, list[float]],
    feeling_order: list[str],
    title_color: str = "#3dab7a",
) -> go.Figure | None:
    """One violin per feeling."""
    feelings_with_data = [f for f in feeling_order if feelings_data.get(f)]
    if not feelings_with_data:
        return None

    fig = go.Figure()
    for i, name in enumerate(feelings_with_data):
        values = feelings_data[name]
        color = FEELING_COLORS[i % len(FEELING_COLORS)]
        fill_rgba = _hex_to_rgba(color, 0.4)

        fig.add_trace(go.Violin(
            x=[name.title()] * len(values), y=values,
            name=name.title(),
            line_color=color, fillcolor=fill_rgba,
            box_visible=True, meanline_visible=True,
            points="all", pointpos=0, jitter=0.15,
            marker=dict(size=5, color=color, line=dict(width=1, color="white")),
            hoveron="violins+points+kde",
            hovertemplate=f"<b>{name.title()}</b><br>Intensity: %{{y:.1f}}/10<extra></extra>",
            spanmode="hard", span=[1, 10],
            showlegend=False,
        ))

    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=360, margin=dict(l=20, r=20, t=20, b=50),
        xaxis=dict(showgrid=False, color="#666", tickangle=0),
        yaxis=dict(
            title="Intensity (1–10)", range=[0.5, 10.5],
            showgrid=True, gridcolor="#ece9df", color="#666",
            dtick=1,
        ),
        violingap=0.25,
    )
    return fig


def _render_feelings_violin_compare(
    recent_data: dict[str, list[float]],
    alltime_data: dict[str, list[float]],
    feeling_order: list[str],
    recent_label: str = "Last 30 days",
    alltime_label: str = "All time",
) -> go.Figure | None:
    """Two violins per feeling: recent vs all-time."""
    plottable = [
        f for f in feeling_order
        if recent_data.get(f) or alltime_data.get(f)
    ]
    if not plottable:
        return None

    fig = go.Figure()
    alltime_color = "#5b6fa6"
    recent_color = "#3dab7a"

    for name in plottable:
        x_label = name.title()
        if alltime_data.get(name):
            fig.add_trace(go.Violin(
                x=[x_label] * len(alltime_data[name]), y=alltime_data[name],
                side="negative", name=alltime_label,
                line_color=alltime_color, fillcolor=_hex_to_rgba(alltime_color, 0.3),
                box_visible=True, meanline_visible=True,
                points=False,
                hoveron="violins+kde",
                hovertemplate=(
                    f"<b>{x_label}</b><br>"
                    f"{alltime_label}: %{{y:.1f}}/10<extra></extra>"
                ),
                spanmode="hard", span=[1, 10],
                showlegend=(name == plottable[0]),
                legendgroup=alltime_label,
            ))
        if recent_data.get(name):
            fig.add_trace(go.Violin(
                x=[x_label] * len(recent_data[name]), y=recent_data[name],
                side="positive", name=recent_label,
                line_color=recent_color, fillcolor=_hex_to_rgba(recent_color, 0.5),
                box_visible=True, meanline_visible=True,
                points="all", pointpos=0.4, jitter=0.05,
                marker=dict(size=4, color=recent_color, line=dict(width=0)),
                hoveron="violins+points+kde",
                hovertemplate=(
                    f"<b>{x_label}</b><br>"
                    f"{recent_label}: %{{y:.1f}}/10<extra></extra>"
                ),
                spanmode="hard", span=[1, 10],
                showlegend=(name == plottable[0]),
                legendgroup=recent_label,
            ))

    fig.update_layout(
        paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=400, margin=dict(l=20, r=20, t=20, b=50),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            bgcolor="rgba(255,255,255,0)", bordercolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(showgrid=False, color="#666", tickangle=0),
        yaxis=dict(
            title="Intensity (1–10)", range=[0.5, 10.5],
            showgrid=True, gridcolor="#ece9df", color="#666",
            dtick=1,
        ),
        violingap=0.3, violinmode="overlay",
    )
    return fig
