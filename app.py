import streamlit as st
import anthropic
import base64
import hashlib
from supabase import create_client
from datetime import date, datetime, timedelta
import json
import numpy as np
import plotly.graph_objects as go

import oura
import oura_ui
from oura import user_today
from intro_page import render_intro_page, user_has_seen_intro


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mirra", layout="centered")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; background-color: #faf9f5; color: #2a2a2a; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.6rem 2rem 4rem 2rem; max-width: 1180px; }

/* Tab styling — slimmer, lower-contrast, more typographic */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px; background: transparent; border-bottom: 1px solid #ece9df;
    border-radius: 0; padding: 0 0 0 4px; margin-bottom: 1rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 0; padding: 10px 18px; font-size: 0.86rem;
    font-weight: 500; color: #999; background: transparent; border: none;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
    transition: color 0.15s ease, border-color 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover { color: #555; }
.stTabs [aria-selected="true"] {
    background: transparent !important; color: #1a1a1a !important;
    font-weight: 600; box-shadow: none !important;
    border-bottom: 2px solid #3dab7a !important;
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.4rem; }

/* Headings + labels */
.date-label { font-size: 0.82rem; color: #999; margin-bottom: 0.15rem; letter-spacing: 0.02em; }
.title-text { font-family: 'Lora', serif; font-size: 1.8rem; font-weight: 600; color: #1a1a1a; margin: 0; letter-spacing: -0.01em; }
.streak-badge {
    background: transparent; border: 1px solid #3dab7a; color: #2a8a5e;
    padding: 0.3rem 0.9rem; border-radius: 999px;
    font-size: 0.82rem; font-weight: 500; letter-spacing: 0.01em;
}
.section-label {
    font-size: 0.72rem; font-weight: 600; color: #888;
    letter-spacing: 0.14em; text-transform: uppercase;
    margin-bottom: 0.7rem; margin-top: 1.8rem;
}

/* Inputs */
textarea {
    background-color: #ffffff !important; border: 1px solid #ece9df !important;
    border-radius: 10px !important; font-family: 'DM Sans', sans-serif !important;
    font-size: 0.98rem !important; color: #2a2a2a !important;
    transition: border-color 0.15s ease !important;
}
textarea:focus { border-color: #3dab7a !important; box-shadow: 0 0 0 3px rgba(61,171,122,0.08) !important; }

.stSlider > div > div > div > div { background-color: #3dab7a !important; }
[data-testid="stSlider"] [role="slider"] {
    background-color: #3dab7a !important; border: 2px solid white !important;
    box-shadow: 0 1px 4px rgba(61,171,122,0.35) !important;
}
.mood-value { font-family: 'Lora', serif; font-size: 1.6rem; font-weight: 600; color: #3dab7a; letter-spacing: -0.01em; }

/* Keyword chips */
.keywords-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 0.3rem; }
.kw-chip {
    display: inline-block; padding: 4px 12px; border-radius: 999px;
    font-size: 0.82rem; font-weight: 500;
    background: #e8f5f0; border: 1px solid #c9e4d6; color: #2a7a55;
}
.kw-chip-neutral { background: #f5f4ee; border: 1px solid #e5e2d6; color: #666; }
.kw-header { display: flex; justify-content: space-between; align-items: center; }
.kw-ai-label { font-size: 0.74rem; color: #aaa; letter-spacing: 0.04em; }
.divider { border: none; border-top: 1px solid #ece9df; margin: 1.8rem 0; }

/* Feelings */
.feeling-name { font-size: 0.95rem; font-weight: 500; color: #2a2a2a; padding-top: 8px; }
.feeling-hint { color: #888; font-size: 0.86rem; margin: 0.3rem 0 0.8rem; line-height: 1.55; }
.feeling-skip { color: #aaa; font-size: 0.85rem; font-style: italic; margin-top: 0.4rem; }

/* Stat cards — cleaner white-on-cream */
.stat-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 0.4rem; }
.stat-card {
    background: white; border: 1px solid #ece9df;
    border-radius: 12px; padding: 1rem 1.2rem 0.9rem;
}
.stat-card-label {
    font-size: 0.68rem; font-weight: 600; letter-spacing: 0.12em;
    color: #999; text-transform: uppercase; margin-bottom: 6px;
}
.stat-card-value { font-family: 'Lora', serif; font-size: 1.9rem; font-weight: 600; color: #1a1a1a; line-height: 1.05; letter-spacing: -0.01em; }
.stat-card-sub { font-size: 0.78rem; color: #aaa; margin-top: 4px; }

.save-msg {
    background: #f0f8f4; border: 1px solid #c9e4d6;
    border-radius: 8px; padding: 0.65rem 1rem; color: #1e6b45;
    font-weight: 500; margin-top: 0.8rem; font-size: 0.92rem;
}

/* Login page */
.login-wrap { max-width: 400px; margin: 0 auto; padding-top: 1rem; }
.login-logo { text-align: center; margin-bottom: 1.4rem; }
.login-title { font-family: 'Lora', serif; font-size: 2rem; font-weight: 600; color: #1a1a1a; text-align: center; margin-bottom: 0.3rem; letter-spacing: -0.01em; }
.login-sub { color: #999; font-size: 0.74rem; text-align: center; letter-spacing: 0.18em; text-transform: uppercase; margin-bottom: 1.8rem; font-weight: 500; }
.logout-btn { position: fixed; top: 14px; right: 18px; z-index: 999; }
.login-card > div:first-child:empty { display: none; }
.block-container > div:first-child { padding-top: 0 !important; }

/* Insight + data cards */
.insight-card {
    background: white; border: 1px solid #ece9df;
    border-radius: 12px; padding: 1.3rem 1.5rem; margin-bottom: 1rem;
    line-height: 1.7; color: #2a2a2a; font-size: 0.96rem;
}
.insight-header { font-family: 'Lora', serif; font-size: 1.25rem; font-weight: 600; color: #1a1a1a; margin-bottom: 0.9rem; letter-spacing: -0.005em; }
.min-data-msg {
    background: white; border: 1px solid #ece9df; border-left: 3px solid #d4a843;
    border-radius: 8px; padding: 0.9rem 1.2rem; color: #6a5520; font-size: 0.92rem; margin-top: 1rem;
}
</style>
""", unsafe_allow_html=True)


# ── Clients ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

@st.cache_resource
def get_anthropic():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

supabase  = get_supabase()
ai_client = get_anthropic()


# ── NLP helpers (lazy-loaded to avoid slow startup) ───────────────────────────
@st.cache_resource(show_spinner="Loading NLP models…")
def load_nlp_models():
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return embedder


def extract_keywords(text: str) -> list[str]:
    """Extract keywords using CountVectorizer."""
    from sklearn.feature_extraction.text import CountVectorizer
    try:
        vec = CountVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            max_features=20,
            token_pattern=r"[a-zA-Z]{3,}"
        )
        X = vec.fit_transform([text])
        counts = X.sum(axis=0).A1
        phrases = vec.get_feature_names_out()
        ranked = sorted(zip(phrases, counts), key=lambda x: x[1], reverse=True)
        return [p for p, _ in ranked[:8]]
    except Exception:
        return []


def get_embeddings(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384))
    embedder = load_nlp_models()  # no longer a tuple
    return embedder.encode(texts, show_progress_bar=False)


# Preset feelings shown in the multiselect on the daily reflection page.
# Users can also type custom feelings (accept_new_options=True) — this is just
# a starting palette covering common positive/neutral/negative affect words.
PRESET_FEELINGS = [
    "anxious", "stressed", "overwhelmed", "depressed", "sad", "frustrated", "angry",
    "tired", "neutral", "present", "calm", "relaxed", "content", "happy",
    "grateful", "energized", "focused", "excited",
]


# ── Supabase helpers ──────────────────────────────────────────────────────────
# Requires `reflections` to have a `feelings` JSONB column (nullable). Add via:
#   alter table reflections add column feelings jsonb;
# Stored shape: [{"name": "anxious", "intensity": 7}, {"name": "calm", "intensity": null}, ...]
def save_reflection(content: str, mood: float, keywords: list[str],
                    user_id: str, feelings: list[dict] | None = None):
    today = user_today().isoformat()
    supabase.table("reflections").upsert({
        "entry_date": today,
        "content": content,
        "mood": mood,
        "keywords": keywords,
        "feelings": feelings or [],
        "user_id": user_id,
        "updated_at": datetime.utcnow().isoformat(),
    }, on_conflict="user_id,entry_date").execute()


@st.cache_data(ttl=60)
def load_all_entries(user_id: str) -> list[dict]:
    res = supabase.table("reflections").select("*").eq("user_id", user_id).order("entry_date", desc=True).execute()
    return res.data or []


def load_stats(rows):
    total = len(rows)
    cutoff_30 = (user_today() - timedelta(days=30)).isoformat()
    recent = [r for r in rows if r["entry_date"] >= cutoff_30]
    avg_mood = round(sum(r["mood"] for r in recent) / len(recent), 1) if recent else 0.0
    cutoff_7 = (user_today() - timedelta(days=7)).isoformat()
    week_rows = [r for r in rows if r["entry_date"] >= cutoff_7]
    kw_count: dict[str, int] = {}
    for r in week_rows:
        for kw in (r.get("keywords") or []):
            kw_count[kw.lower()] = kw_count.get(kw.lower(), 0) + 1
    top_topic = max(kw_count, key=kw_count.get) if kw_count else "—"
    dated = sorted({r["entry_date"] for r in rows}, reverse=True)
    streak, check = 0, user_today()
    for d in dated:
        if d == check.isoformat():
            streak += 1; check -= timedelta(days=1)
        else:
            break
    today_rows = [r for r in rows if r["entry_date"] == user_today().isoformat()]
    return total, avg_mood, top_topic, streak, (today_rows[0] if today_rows else None)


# ── Topic Map: UMAP + HDBSCAN (no BERTopic dependency) ───────────────────────
@st.cache_data(ttl=300)
def run_topic_map(texts: tuple, moods: tuple = None):
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import TfidfVectorizer

    embedder = load_nlp_models()
    text_list = [t for t in texts if t and t.strip()]
    if len(text_list) < 5:
        raise ValueError(f"Need at least 5 entries, got {len(text_list)}.")

    embeddings = embedder.encode(text_list, show_progress_bar=False)

    # Factor in mood scores if provided
    if moods and len(moods) == len(text_list):
        # Normalize mood (1-10 scale) to a standard range for blending
        mood_array = np.array(moods, dtype=float)
        mood_normalized = (mood_array - 5.5) / 4.5  # Centers around 0, range -1 to 1
        
        # Replicate mood value across 10 dimensions to give it meaningful influence
        mood_features = np.tile(mood_normalized.reshape(-1, 1), (1, 10))
        
        # Concatenate mood features with text embeddings
        embeddings = np.hstack([embeddings, mood_features])

    n = len(text_list)
    reduced = UMAP(
        n_components=2, n_neighbors=min(5, n - 1),
        min_dist=0.1, random_state=42
    ).fit_transform(embeddings)

    labels = HDBSCAN(
        min_cluster_size=max(2, n // 10),
        min_samples=1,
        cluster_selection_epsilon=0.5
    ).fit_predict(embeddings)

    # Reassign noise points (-1) to their nearest non-noise cluster
    noise_mask = labels == -1
    if noise_mask.any():
        noise_indices = np.where(noise_mask)[0]
        non_noise_indices = np.where(labels != -1)[0]
        
        if len(non_noise_indices) > 0:
            # Compute distances from noise points to all non-noise points
            from scipy.spatial.distance import cdist
            noise_embeddings = embeddings[noise_indices]
            non_noise_embeddings = embeddings[non_noise_indices]
            distances = cdist(noise_embeddings, non_noise_embeddings, metric="cosine")
            
            # For each noise point, find the nearest non-noise point and assign to its cluster
            for i, noise_idx in enumerate(noise_indices):
                nearest_non_noise_idx = non_noise_indices[np.argmin(distances[i])]
                labels[noise_idx] = labels[nearest_non_noise_idx]

    # Label each cluster with top TF-IDF terms from its texts
    cluster_ids = sorted(set(labels))
    cluster_labels = {}
    tfidf = TfidfVectorizer(max_features=500, stop_words="english", ngram_range=(1, 2))
    try:
        tfidf.fit(text_list)
        terms = tfidf.get_feature_names_out()
        tfidf_matrix = tfidf.transform(text_list).toarray()
        for cid in cluster_ids:
            if cid == -1:
                cluster_labels[cid] = "Noise"
                continue
            idxs = [i for i, l in enumerate(labels) if l == cid]
            mean_vec = tfidf_matrix[idxs].mean(axis=0)
            top_terms = [terms[i] for i in mean_vec.argsort()[::-1][:3]]
            cluster_labels[cid] = " · ".join(top_terms)
    except Exception:
        for cid in cluster_ids:
            cluster_labels[cid] = "Noise" if cid == -1 else f"Cluster {cid}"

    return reduced, labels.tolist(), cluster_labels, text_list


TOPIC_COLORS = [
    "#e05a3a", "#3dab7a", "#d4850a", "#5b6fa6", "#9b59b6",
    "#1abc9c", "#e74c3c", "#2980b9", "#f39c12", "#27ae60",
]


def render_bertopic_tab(rows):
    st.markdown('<p class="title-text">Topic Map</p>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">sentence-transformers + UMAP + HDBSCAN + TF-IDF labels</div>', unsafe_allow_html=True)

    MIN_ENTRIES = 10
    if len(rows) < MIN_ENTRIES:
        st.markdown(f'<div class="min-data-msg">Topic modeling needs at least <strong>{MIN_ENTRIES} entries</strong>. You have <strong>{len(rows)}</strong> so far &mdash; keep journaling.</div>', unsafe_allow_html=True)
        return

    texts = [r["content"] for r in rows]
    dates = [r["entry_date"] for r in rows]
    moods = [r["mood"] for r in rows]

    if not st.button("▶ Run Topic Model", type="primary", key="run_topic_map"):
        st.markdown('<div style="color:#aaa; font-size:0.92rem; margin-top:0.5rem">Click to cluster your entries with UMAP + HDBSCAN. Takes ~20 sec on first run.</div>', unsafe_allow_html=True)
        return

    status = st.status("Building topic map…", expanded=True)
    with status:
        st.write("Loading NLP models…")
        load_nlp_models()
        st.write("Embedding and clustering…")
        try:
            reduced, topics, topic_labels, text_list = run_topic_map(tuple(texts), tuple(moods))
        except Exception as e:
            st.error(f"Topic map failed: {e}")
            return
        st.write("Done.")
    status.update(label="Topic map ready", state="complete", expanded=False)

    # Align dates/moods to text_list (filtered) by matching content
    content_to_meta = {r["content"]: (r["entry_date"], r["mood"]) for r in rows}
    aligned_dates = [content_to_meta.get(t, ("?", 0))[0] for t in text_list]
    aligned_moods = [content_to_meta.get(t, ("?", 0))[1] for t in text_list]

    unique_topics = sorted(set(topics))
    color_map = {}
    ci = 0
    for t in unique_topics:
        color_map[t] = "#cccccc" if t == -1 else TOPIC_COLORS[ci % len(TOPIC_COLORS)]
        if t != -1: ci += 1

    fig = go.Figure()
    for tid in unique_topics:
        mask = [i for i, t in enumerate(topics) if t == tid]
        label = topic_labels.get(tid, f"Cluster {tid}")
        hover = [f"<b>{aligned_dates[i]}</b><br>Mood: {aligned_moods[i]}<br>{text_list[i][:80]}…" for i in mask]
        fig.add_trace(go.Scatter(
            x=[reduced[i, 0] for i in mask],
            y=[reduced[i, 1] for i in mask],
            mode="markers",
            name=("Noise" if tid == -1 else f"Cluster {tid} — {label}"),
            marker=dict(size=10, color=color_map[tid], opacity=0.85,
                        line=dict(width=1, color="white")),
            text=hover, hoverinfo="text",
        ))

    fig.update_layout(
        paper_bgcolor="#f7f6f2", plot_bgcolor="#f7f6f2",
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(title="UMAP dimension 1", showgrid=False, zeroline=False, color="#aaa"),
        yaxis=dict(title="UMAP dimension 2", showgrid=False, zeroline=False, color="#aaa"),
        showlegend=False,
        font=dict(family="DM Sans"),
        height=480,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Build and display legend with topic keywords
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Topics discovered</div>', unsafe_allow_html=True)
    
    legend_html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 0.8rem;">'
    for tid in [t for t in unique_topics if t != -1]:
        color = color_map[tid]
        label = topic_labels.get(tid, "")
        count = sum(1 for t in topics if t == tid)
        idxs = [i for i, t in enumerate(topics) if t == tid]
        avg_m = round(float(np.mean([aligned_moods[i] for i in idxs])), 1)
        
        legend_html += f"""
        <div style="display:flex; align-items:flex-start; gap:12px; padding:12px 14px; background:#f0efe8; border-radius:12px; border-left:4px solid {color};">
            <div style="width:10px;height:10px;border-radius:50%;background:{color};flex-shrink:0;margin-top:3px"></div>
            <div style="flex:1">
                <div style="font-weight:600; color:#1a1a1a; margin-bottom:4px">Cluster {tid}</div>
                <div style="font-size:0.88rem; color:#555; line-height:1.4; margin-bottom:6px">{label}</div>
                <div style="font-size:0.78rem; color:#888">
                    <span style="margin-right:14px">{count} entries</span>
                    <span>avg mood {avg_m}</span>
                </div>
            </div>
        </div>"""
    
    legend_html += '</div>'
    st.markdown(legend_html, unsafe_allow_html=True)


# ── Dendrogram viz ────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def run_dendrogram(phrases_tuple: tuple):
    """Run HAC on a tuple of pre-filtered phrases. Returns (phrases, Z, cluster_ids)."""
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist
    from hdbscan import HDBSCAN

    phrases = list(phrases_tuple)
    if len(phrases) < 4:
        return None, None, None

    embeddings = get_embeddings(phrases)
    if embeddings.shape[0] == 0:
        return None, None, None

    # Use HDBSCAN for semantic clustering instead of fixed-cluster hierarchical
    clusterer = HDBSCAN(
        min_cluster_size=max(2, len(phrases) // 8),
        min_samples=1,
        cluster_selection_epsilon=0.3
    )
    cluster_ids = clusterer.fit_predict(embeddings)
    
    # For dendrogram visualization, still compute linkage on normalized embeddings
    norms  = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / np.where(norms == 0, 1, norms)
    dist   = pdist(normed, metric="cosine")
    Z      = linkage(dist, method="ward")
    
    return phrases, Z, cluster_ids


def _draw_dendrogram(phrases, Z, cluster_ids):
    """Render a Plotly dendrogram figure from pre-computed linkage data."""
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

    # Estimate longest label width in axis units so labels don't clip
    max_label_len = max(len(name) for name in leaf_names) if leaf_names else 10
    x_right = max_label_len * 0.018   # ~0.018 units per character at this scale

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


DENDRO_COLORS = [
    "#e05a3a", "#3dab7a", "#d4850a", "#5b6fa6", "#9b59b6",
    "#1abc9c", "#e74c3c", "#2980b9", "#f39c12", "#27ae60",
    "#c0392b", "#8e44ad", "#16a085", "#c9302c"
]
DENDRO_LABELS = ["work stress", "gratitude", "self-care", "social", "growth"]


def extract_noun_phrase_clusters(rows: list[dict], top_n: int = 60) -> list[str]:
    """Extract top-N commonly occurring multi-word phrases (2-4 words) using CountVectorizer, ranked by frequency."""
    from sklearn.feature_extraction.text import CountVectorizer
    
    docs = [r["content"] for r in rows if r.get("content", "").strip()]
    
    if len(docs) < 4:
        return []
    
    texts = [str(t).strip() for t in docs if t and str(t).strip()]
    
    if not texts:
        return []
    
    vectorizer = CountVectorizer(
        ngram_range=(2, 4),       # 2 to 4 word phrases
        stop_words="english",     # remove common words like "i", "the", "it"
        min_df=1,                 # include phrases appearing 1+ times
        max_features=500,         # cap total phrases considered
        token_pattern=r"[a-zA-Z]{2,}"  # letters only, min 2 chars per word
    )
    
    try:
        X = vectorizer.fit_transform(texts)
    except ValueError:
        return []
    
    # Sum counts across all documents
    phrase_counts = X.sum(axis=0).A1
    phrases = vectorizer.get_feature_names_out()
    
    # Sort by frequency and return top N
    phrase_freq = list(zip(phrases, phrase_counts))
    phrase_freq.sort(key=lambda x: x[1], reverse=True)
    
    # Filter out duplicate substrings (keep longer phrases, remove shorter substrings)
    filtered_phrases = []
    for phrase, count in phrase_freq[:top_n * 2]:  # Look at more to account for filtering
        # Check if this phrase is a substring of any already-selected phrase
        is_substring = False
        for existing in filtered_phrases:
            if phrase in existing and phrase != existing:
                is_substring = True
                break
        
        if not is_substring:
            # Also check if any existing phrases are substrings of this one
            # If so, remove the shorter ones
            filtered_phrases = [p for p in filtered_phrases if phrase not in p or p == phrase]
            filtered_phrases.append(phrase)
    
    return filtered_phrases[:top_n]




def get_top_similar_phrases(query: str, phrases: list[str], top_n: int = 25) -> list[str]:
    """Return the top_n phrases most semantically similar to the query string."""
    from sklearn.metrics.pairwise import cosine_similarity

    if not phrases:
        return []

    all_texts = [query] + phrases
    embeddings = get_embeddings(all_texts)

    query_vec = embeddings[0].reshape(1, -1)
    phrase_vecs = embeddings[1:]

    # Compute cosine similarities using sklearn (returns similarity scores 0-1)
    similarities_matrix = cosine_similarity(query_vec, phrase_vecs)[0]
    
    # Pair each phrase with its similarity score
    similarities = [(phrases[i], float(similarities_matrix[i])) for i in range(len(phrases))]
    
    # Sort by similarity in descending order
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    return [p for p, _ in similarities[:top_n]]


def render_dendrogram_tab(rows):
    st.markdown('<p class="title-text">Phrase Dendrogram</p>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem"> noun phrases (3–5 words) · sentence-transformers embeddings · HDBSCAN clustering</div>', unsafe_allow_html=True)

    MIN_ENTRIES = 8
    if len(rows) < MIN_ENTRIES:
        st.markdown(f'<div class="min-data-msg">The dendrogram needs at least <strong>{MIN_ENTRIES} entries</strong>. You have <strong>{len(rows)}</strong> so far.</div>', unsafe_allow_html=True)
        return

    # ── Extract meaningful noun phrases (syntactic approach) ──────────────────
    unique_phrases = extract_noun_phrase_clusters(rows, top_n=60)

    if len(unique_phrases) < 4:
        st.markdown('<div class="min-data-msg">Not enough recurring 3&ndash;5 word noun phrases yet. Keep logging.</div>', unsafe_allow_html=True)
        return

    # ── Semantic query input ───────────────────────────────────────────────────
    st.markdown("""
    <div style="background:white; border:1px solid #ece9df; border-radius:12px; padding:1.1rem 1.3rem 0.8rem; margin-bottom:1rem;">
      <div style="font-size:0.72rem; font-weight:600; letter-spacing:0.14em; color:#888; text-transform:uppercase; margin-bottom:0.6rem;">
        Explore a theme
      </div>
      <div style="font-size:0.92rem; color:#555; margin-bottom:0.7rem; line-height:1.55;">
        Enter a concept or feeling and the dendrogram will show the <strong>top 25 phrases from your reflections</strong>
        most semantically related to it &mdash; revealing hidden thought patterns and contextual themes around that topic.
      </div>
    </div>
    """, unsafe_allow_html=True)

    query_examples = "e.g., flow state, creative projects, time off, overwhelmed by tasking"
    query = st.text_input(
        "What theme or concept would you like to explore?",
        placeholder=query_examples,
        key="dendro_query",
        label_visibility="visible",
    )

    # Detect if the query changed so we can auto-clear stale results
    prev_query = st.session_state.get("dendro_last_query", None)
    if query != prev_query:
        st.session_state.pop("dendro_results", None)
        st.session_state["dendro_last_query"] = query

    # ── Mode label ────────────────────────────────────────────────────────────
    if query.strip():
        mode_label = f'Top 25 phrases most similar to <em>"{query.strip()}"</em>'
    else:
        mode_label = f'{len(unique_phrases)} unique key phrases found — showing all'
    st.markdown(f'<div style="color:#aaa; font-size:0.85rem; margin:0.3rem 0 0.8rem">{mode_label}</div>', unsafe_allow_html=True)

    # ── Run button — stores results in session_state so selectbox reruns don't wipe them ──
    run_clicked = st.button("Run Dendrogram", type="primary", key="run_dendro")

    if run_clicked:
        status = st.status("Building dendrogram…", expanded=True)
        with status:
            st.write("Loading NLP models…")
            load_nlp_models()

            # Apply semantic filter if a query was entered
            if query.strip():
                st.write(f"Finding top 25 phrases related to '{query.strip()}'…")
                phrases_to_cluster = get_top_similar_phrases(query.strip(), unique_phrases, top_n=25)
                if len(phrases_to_cluster) < 4:
                    st.error("Not enough matching phrases for the query. Try a broader theme.")
                    # Show top similar phrases for debugging
                    all_sims = get_top_similar_phrases(query.strip(), unique_phrases, top_n=min(15, len(unique_phrases)))
                    st.warning(f"**Top phrases found similar to '{query.strip()}':**\n" + "\n".join([f"- {p}" for p in all_sims]))
                    return
            else:
                phrases_to_cluster = unique_phrases

            st.write("Embedding phrases with sentence-transformers…")
            st.write("Clustering semantically similar phrases…")
            try:
                phrases, Z, cluster_ids = run_dendrogram(tuple(phrases_to_cluster))
            except Exception as e:
                st.error(f"Dendrogram failed: {e}")
                return
            if phrases is None:
                st.info("Not enough unique phrases yet.")
                return
            st.write("Done.")
        status.update(label="Dendrogram ready", state="complete", expanded=False)

        # Build cluster metadata and store everything in session_state
        cluster_to_phrases: dict = {}
        for phrase, cid in zip(phrases, cluster_ids):
            cluster_to_phrases.setdefault(int(cid), []).append(phrase)
        cluster_names = {cid: " / ".join(ps[:2]) for cid, ps in cluster_to_phrases.items()}

        st.session_state["dendro_results"] = {
            "phrases": phrases,
            "Z": Z,
            "cluster_ids": cluster_ids,
            "cluster_to_phrases": cluster_to_phrases,
            "cluster_names": cluster_names,
            "query": query.strip(),
        }

    # ── Nothing computed yet ──────────────────────────────────────────────────
    if "dendro_results" not in st.session_state:
        return

    # ── Restore from session_state ────────────────────────────────────────────
    res              = st.session_state["dendro_results"]
    phrases          = res["phrases"]
    Z                = res["Z"]
    cluster_ids      = res["cluster_ids"]
    cluster_to_phrases = res["cluster_to_phrases"]
    cluster_names    = res["cluster_names"]
    active_query     = res.get("query", "")
    sorted_clusters  = sorted(cluster_to_phrases.keys())

    # ── Query badge (if active) ───────────────────────────────────────────────
    if active_query:
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:8px;background:transparent;border:1px solid #3dab7a;'
            f'border-radius:999px;padding:4px 14px;font-size:0.83rem;color:#2a7a55;margin-bottom:0.8rem;">'
            f'<span>Showing phrases related to <strong>{active_query}</strong></span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Topic filter selectbox ────────────────────────────────────────────────
    filter_options = ["All clusters"] + [
        f"Cluster {cid} \u2014 {cluster_names[cid]}" for cid in sorted_clusters
    ]
    col_sel, col_count = st.columns([3, 1])
    with col_sel:
        selected = st.selectbox("Filter by cluster", filter_options, key="dendro_filter")
    with col_count:
        st.markdown(f'<div style="padding-top:28px; color:#aaa; font-size:0.85rem">{len(phrases)} phrases</div>', unsafe_allow_html=True)

    # ── Build view (all or filtered cluster) ─────────────────────────────────
    if selected == "All clusters":
        view_phrases, view_Z, view_cluster_ids = phrases, Z, cluster_ids
    else:
        selected_cid = int(selected.split()[1])
        keep = [p for p, cid in zip(phrases, cluster_ids) if cid == selected_cid]
        if len(keep) < 2:
            st.info("This cluster has fewer than 2 phrases \u2014 nothing to show.")
            return
        try:
            view_phrases, view_Z, view_cluster_ids = run_dendrogram(tuple(keep))
        except Exception as e:
            st.error(f"Cluster filter failed: {e}")
            return
        if view_phrases is None:
            st.info("Not enough phrases in this cluster.")
            return

    fig = _draw_dendrogram(view_phrases, view_Z, view_cluster_ids)
    st.plotly_chart(fig, use_container_width=True)

    # ── Cluster legend (all-clusters view only) ───────────────────────────────
    if selected == "All clusters":
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        legend_html = '<div style="display:flex; flex-wrap:wrap; gap:10px; font-size:0.84rem;">'
        legend_html += '<span style="color:#aaa; align-self:center; margin-right:4px">clusters:</span>'
        for cid in sorted_clusters:
            color = DENDRO_COLORS[(cid - 1) % len(DENDRO_COLORS)]
            lbl   = cluster_names[cid]
            count = len(cluster_to_phrases[cid])
            legend_html += (
                f'<span style="display:flex;align-items:center;gap:5px;background:#f0efe8;padding:4px 10px;border-radius:999px;">' +
                f'<span style="width:9px;height:9px;border-radius:50%;background:{color};display:inline-block;flex-shrink:0"></span>' +
                f'<span style="color:#2a2a2a">{lbl}</span>' +
                f'<span style="color:#aaa">({count})</span></span>'
            )
        legend_html += '</div>'
        st.markdown(legend_html, unsafe_allow_html=True)




# ── Auth helpers ──────────────────────────────────────────────────────────────
def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def render_login_page():
    import base64 as b64mod
    with open("logo.png", "rb") as f:
        logo_b64 = b64mod.b64encode(f.read()).decode()

    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="login-logo"><img src="data:image/png;base64,{logo_b64}" width="320"/></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="login-title">mirra</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">Where patterns become awareness</div>', unsafe_allow_html=True)

    mode = st.radio("", ["Sign in", "Create account"], horizontal=True, label_visibility="collapsed", key="auth_mode")

    with st.container(border=True):
        username = st.text_input("Username", key="auth_user", placeholder="your username")
        password = st.text_input("Password", type="password", key="auth_pass", placeholder="••••••••")

        if mode == "Sign in":
            if st.button("Sign in", type="primary", use_container_width=True):
                if not username or not password:
                    st.error("Please enter both username and password.")
                else:
                    res = supabase.table("users").select("id,username,password_hash").eq("username", username.strip().lower()).execute()
                    if not res.data:
                        st.error("Username not found.")
                    elif res.data[0]["password_hash"] != hash_pw(password):
                        st.error("Incorrect password.")
                    else:
                        st.session_state["user_id"]   = res.data[0]["id"]
                        st.session_state["username"]  = res.data[0]["username"]
                        st.session_state["logged_in"] = True
                        st.rerun()
        else:
            if st.button("Create account", type="primary", use_container_width=True):
                if not username or not password:
                    st.error("Please fill in all fields.")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    clean = username.strip().lower()
                    existing = supabase.table("users").select("id").eq("username", clean).execute()
                    if existing.data:
                        st.error("Username already taken.")
                    else:
                        new_user = supabase.table("users").insert({
                            "username": clean,
                            "password_hash": hash_pw(password),
                        }).execute()
                        uid = new_user.data[0]["id"]
                        st.session_state["user_id"]   = uid
                        st.session_state["username"]  = clean
                        st.session_state["logged_in"] = True
                        st.rerun()



# ── Main ──────────────────────────────────────────────────────────────────────
if not st.session_state.get("logged_in"):
    render_login_page()
    st.stop()

# Show the welcome intro page once per user. After they dismiss it (button on
# the intro page calls `mark_intro_seen`), `has_seen_intro` is True and this
# gate falls through.
if not user_has_seen_intro(supabase, st.session_state["user_id"]):
    render_intro_page(supabase, st.session_state["user_id"])
    st.stop()

# Logout button
with st.container():
    col_space, col_logout = st.columns([5, 1])
    with col_logout:
        if st.button("Sign out", key="logout"):
            for k in ["logged_in", "user_id", "username", "keywords",
                      "save_success", "dendro_results", "insight_report",
                      "has_seen_intro"]:
                st.session_state.pop(k, None)
            st.cache_data.clear()
            st.rerun()




# ── Insights agent ────────────────────────────────────────────────────────────
def render_weekly_insights_tab(rows, oura_by_date):
    """Rolling last-7-days Oura summary + mood histogram (this-week vs all-time
    with KDE overlays) + top weekly keywords/feelings."""
    st.markdown('<p class="title-text">Weekly insights</p>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.6rem">'
        'Your last 7 days &middot; Oura averages, mood distribution, recurring themes'
        '</div>',
        unsafe_allow_html=True,
    )

    today = user_today()
    week_start = today - timedelta(days=6)  # rolling 7 days inclusive
    week_iso_set = {(week_start + timedelta(days=i)).isoformat() for i in range(7)}

    week_rows = [r for r in rows if r["entry_date"] in week_iso_set]
    if not week_rows and not any(d in oura_by_date for d in week_iso_set):
        st.markdown(
            '<div class="min-data-msg">No reflections or Oura data in the last 7 days yet.</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Oura summary for the week ─────────────────────────────────────────────
    st.markdown('<div class="section-label">Oura, this week</div>', unsafe_allow_html=True)

    def _week_values(field: str) -> list[tuple[str, float]]:
        """Return [(iso_date, value)] for this metric across the rolling week,
        sorted oldest → newest, skipping null days."""
        out: list[tuple[str, float]] = []
        for i in range(7):
            d = (week_start + timedelta(days=i)).isoformat()
            v = (oura_by_date.get(d) or {}).get(field)
            if v is not None:
                out.append((d, float(v)))
        return out

    def _week_avg(field: str) -> float | None:
        vs = [v for _, v in _week_values(field)]
        return round(sum(vs) / len(vs), 1) if vs else None

    def _most_recent(field: str) -> tuple[str, float] | None:
        """Most recent non-null value this week (date, value). Sleep score
        and readiness usually post in the morning so for those this is
        normally today; activity/resting HR lag a day, so for those it's
        usually yesterday. We don't hardcode the offset — just walk back
        from today through the week and take the first hit."""
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            if d not in week_iso_set:
                continue
            v = (oura_by_date.get(d) or {}).get(field)
            if v is not None:
                return d, float(v)
        return None

    # `lower_is_better` flips the "trending well" coloring for resting HR —
    # for that metric a value BELOW the week average is the favorable signal.
    metric_specs = [
        # (label,      field,            accent,    unit,    lower_is_better)
        ("Sleep",      "sleep_score",     "#3dab7a", "",      False),
        ("Readiness",  "readiness_score", "#3dab7a", "",      False),
        ("Activity",   "activity_score",  "#d4850a", "",      False),
        ("Resting HR", "resting_hr",      "#5b6fa6", " bpm",  True),
    ]

    def _recent_label(d: str) -> str:
        """Human-readable tag for how recent the most-recent value is."""
        today_iso = today.isoformat()
        if d == today_iso:
            return "today"
        if d == (today - timedelta(days=1)).isoformat():
            return "yesterday"
        delta_days = (today - date.fromisoformat(d)).days
        return f"{delta_days}d ago"

    cards_html = '<div style="display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:0.3rem 0 1rem">'
    for label, field, accent, unit, lower_is_better in metric_specs:
        recent = _most_recent(field)
        avg = _week_avg(field)
        # Headline value = the most recent reading. Subtitle = week average,
        # plus an inline up/down arrow showing direction vs avg.
        if recent is None:
            headline = "&mdash;"
            recent_tag = "no data this week"
            sub_str = ""
        else:
            r_date, r_val = recent
            headline = f"{r_val:.0f}{unit}"
            recent_tag = _recent_label(r_date)
            if avg is not None:
                diff = r_val - avg
                # Favorable direction depends on metric (resting HR lower-is-better).
                favorable = (diff < 0) if lower_is_better else (diff > 0)
                # Don't color tiny noise — call it flat if |diff| is small
                # relative to the average (under 3% of the avg).
                noise_threshold = max(0.5, abs(avg) * 0.03)
                if abs(diff) < noise_threshold:
                    arrow, arrow_color = "&rarr;", "#999"
                elif favorable:
                    arrow = "&uarr;" if diff > 0 else "&darr;"
                    arrow_color = "#3dab7a"
                else:
                    arrow = "&uarr;" if diff > 0 else "&darr;"
                    arrow_color = "#c25540"
                sub_str = (
                    f"avg {avg:g}{unit} "
                    f"<span style='color:{arrow_color}; font-weight:600'>{arrow} {diff:+.1f}</span>"
                )
            else:
                sub_str = ""
        cards_html += f"""
        <div style="background:white; border:1px solid #ece9df; border-radius:12px; padding:0.85rem 1rem 0.9rem;">
          <div style="display:flex; align-items:center; gap:7px; margin-bottom:6px;">
            <span style="display:inline-block; width:6px; height:6px; border-radius:999px; background:{accent};"></span>
            <span style="font-size:0.66rem; font-weight:600; color:#999; letter-spacing:0.14em; text-transform:uppercase;">{label}</span>
          </div>
          <div style="font-family:'Lora',serif; font-size:1.6rem; font-weight:600; color:#1a1a1a; line-height:1.05; letter-spacing:-0.01em;">{headline}</div>
          <div style="font-size:0.72rem; color:#aaa; margin-top:2px">{recent_tag}</div>
          <div style="font-size:0.76rem; color:#888; margin-top:4px">{sub_str}</div>
        </div>"""
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)

    # ── Mini dot-plots: this week's distribution per metric ───────────────────
    # Sample size is only ~7, so a traditional histogram or KDE would be misleading.
    # A 1D dot plot shows each day as its own point and lets us visually compare
    # the most recent reading (large filled dot) to the rest of the week
    # (small grey dots) and the average (vertical sage line).
    mini_cols = st.columns(4)
    for (label, field, accent, unit, lower_is_better), col in zip(metric_specs, mini_cols):
        pts = _week_values(field)
        recent = _most_recent(field)
        avg = _week_avg(field)
        with col:
            if not pts or recent is None:
                # Empty placeholder keeps the row aligned visually.
                st.markdown(
                    '<div style="height:90px; display:flex; align-items:center; justify-content:center; color:#bbb; font-size:0.78rem; background:white; border:1px solid #ece9df; border-radius:12px;">no data</div>',
                    unsafe_allow_html=True,
                )
                continue
            recent_date, recent_val = recent
            values = [v for _, v in pts]
            # Stretch x-range a bit so the dots aren't pinned to the edges.
            v_min, v_max = min(values), max(values)
            pad = max(1.0, (v_max - v_min) * 0.15)
            x_range = [v_min - pad, v_max + pad]

            fig_mini = go.Figure()
            # Non-recent points — small grey dots at y=0.
            other_vals = [v for d, v in pts if d != recent_date]
            if other_vals:
                fig_mini.add_trace(go.Scatter(
                    x=other_vals, y=[0] * len(other_vals),
                    mode="markers",
                    marker=dict(size=7, color="#cbc8bd", line=dict(width=0)),
                    hovertemplate=f"{label}: %{{x:.0f}}{unit}<extra></extra>",
                    showlegend=False,
                ))
            # Week-average vertical line so the user sees the recent dot's
            # position relative to the central tendency, not just to other dots.
            if avg is not None:
                fig_mini.add_vline(
                    x=avg, line=dict(color="#aaa", width=1, dash="dot"),
                )
            # Most recent point — larger, colored, ringed in white so it pops
            # against the grey week-mates.
            fig_mini.add_trace(go.Scatter(
                x=[recent_val], y=[0],
                mode="markers",
                marker=dict(size=14, color=accent, line=dict(width=2, color="white")),
                hovertemplate=f"{_recent_label(recent_date)}: %{{x:.0f}}{unit}<extra></extra>",
                showlegend=False,
            ))
            fig_mini.update_layout(
                height=90,
                margin=dict(l=8, r=8, t=8, b=22),
                paper_bgcolor="white", plot_bgcolor="white",
                font=dict(family="DM Sans", color="#888", size=10),
                xaxis=dict(
                    range=x_range,
                    showgrid=False, zeroline=False,
                    tickmode="array",
                    tickvals=[v_min, v_max],
                    ticktext=[f"{v_min:g}", f"{v_max:g}"],
                ),
                yaxis=dict(
                    range=[-0.6, 0.6],
                    showticklabels=False, showgrid=False, zeroline=False,
                    visible=False,
                ),
                showlegend=False,
            )
            st.plotly_chart(fig_mini, use_container_width=True, config={"displayModeBar": False})

    # ── Mood histogram: this week vs all-time, with KDE overlays ──────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Mood distribution</div>', unsafe_allow_html=True)

    week_moods = [float(r["mood"]) for r in week_rows]
    all_moods  = [float(r["mood"]) for r in rows]

    # Gate: need a couple of weekly entries to plot anything meaningful. The
    # all-time KDE needs slightly more (>=3 distinct values) before the kernel
    # bandwidth is stable.
    if len(week_moods) < 2 or len(all_moods) < 3:
        st.markdown(
            '<div class="min-data-msg">Add a few more reflections this week and overall to see the mood distribution.</div>',
            unsafe_allow_html=True,
        )
    else:
        fig_hist = go.Figure()

        # All-time distribution underneath (faint, normalized to density so the
        # two histograms are comparable despite different sample sizes).
        fig_hist.add_trace(go.Histogram(
            x=all_moods, name="All time",
            xbins=dict(start=1, end=10, size=0.5),
            marker=dict(color="rgba(91,111,166,0.25)", line=dict(color="rgba(91,111,166,0.5)", width=1)),
            histnorm="probability density",
            hovertemplate="Mood %{x}<br>Density %{y:.2f}<extra>All time</extra>",
        ))
        # This week on top (sage).
        fig_hist.add_trace(go.Histogram(
            x=week_moods, name="This week",
            xbins=dict(start=1, end=10, size=0.5),
            marker=dict(color="rgba(61,171,122,0.55)", line=dict(color="#3dab7a", width=1)),
            histnorm="probability density",
            hovertemplate="Mood %{x}<br>Density %{y:.2f}<extra>This week</extra>",
        ))

        # KDE curves — a smoothed density estimate overlaid on each histogram.
        # Done by hand with a Gaussian kernel so we don't pull in scipy just
        # for this; bandwidth follows Silverman's rule of thumb.
        def _kde(values: list[float], grid: np.ndarray) -> np.ndarray:
            arr = np.asarray(values, dtype=float)
            n = arr.size
            if n < 2:
                return np.zeros_like(grid)
            std = float(np.std(arr, ddof=1)) or 1e-6
            # Silverman's rule of thumb for univariate Gaussian KDE bandwidth.
            bw = 1.06 * std * (n ** (-1 / 5))
            # Vectorized Gaussian kernel sum across all sample points.
            diffs = (grid[:, None] - arr[None, :]) / bw
            kernels = np.exp(-0.5 * diffs ** 2) / (np.sqrt(2 * np.pi))
            return kernels.sum(axis=1) / (n * bw)

        x_grid = np.linspace(1, 10, 200)
        kde_all  = _kde(all_moods,  x_grid)
        kde_week = _kde(week_moods, x_grid)

        fig_hist.add_trace(go.Scatter(
            x=x_grid, y=kde_all, mode="lines", name="All-time trend",
            line=dict(color="#5b6fa6", width=2), hoverinfo="skip",
        ))
        fig_hist.add_trace(go.Scatter(
            x=x_grid, y=kde_week, mode="lines", name="This-week trend",
            line=dict(color="#3dab7a", width=2.5), hoverinfo="skip",
        ))

        fig_hist.update_layout(
            barmode="overlay",
            paper_bgcolor="#faf9f5", plot_bgcolor="#faf9f5",
            font=dict(family="DM Sans", color="#2a2a2a"),
            height=340, margin=dict(l=20, r=20, t=20, b=40),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                bgcolor="rgba(255,255,255,0)", bordercolor="rgba(0,0,0,0)",
            ),
            xaxis=dict(title="Mood (1–10)", range=[1, 10], showgrid=False, color="#666"),
            yaxis=dict(title="Density", showgrid=True, gridcolor="#ece9df", color="#666"),
        )
        st.plotly_chart(fig_hist, use_container_width=True)

        # Quick comparison line
        week_avg = round(float(np.mean(week_moods)), 1)
        all_avg  = round(float(np.mean(all_moods)), 1)
        delta = week_avg - all_avg
        delta_label = (
            f"<span style='color:#3dab7a'>+{delta:.1f}</span>" if delta >= 0.3 else
            f"<span style='color:#c25540'>{delta:+.1f}</span>" if delta <= -0.3 else
            f"<span style='color:#888'>{delta:+.1f}</span>"
        )
        st.markdown(
            f"<div style='color:#666; font-size:0.88rem; margin-top:-0.6rem'>"
            f"This week averages <strong>{week_avg}</strong> &middot; "
            f"All-time averages <strong>{all_avg}</strong> &middot; "
            f"Delta {delta_label}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Weekly trends: keywords + feelings ────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    col_kw, col_feel = st.columns(2)

    # Top keywords this week
    week_kws: dict[str, int] = {}
    for r in week_rows:
        for k in (r.get("keywords") or []):
            week_kws[k.lower()] = week_kws.get(k.lower(), 0) + 1
    top_week_kws = sorted(week_kws.items(), key=lambda kv: kv[1], reverse=True)[:8]

    with col_kw:
        st.markdown('<div class="section-label" style="margin-top:0">Top keywords</div>', unsafe_allow_html=True)
        if top_week_kws:
            chips = '<div class="keywords-row">'
            for kw, ct in top_week_kws:
                chips += f'<span class="kw-chip">{kw} &middot; {ct}</span>'
            chips += '</div>'
            st.markdown(chips, unsafe_allow_html=True)
        else:
            st.markdown('<div style="color:#aaa; font-size:0.88rem">No keywords yet this week.</div>', unsafe_allow_html=True)

    # Top feelings this week — count occurrences and surface average intensity
    # where rated. Skip-rated feelings count toward frequency but not avg intensity.
    week_feel_count: dict[str, int] = {}
    week_feel_sum: dict[str, float] = {}
    week_feel_rated: dict[str, int] = {}
    for r in week_rows:
        for f in (r.get("feelings") or []):
            name = (f.get("name") or "").lower().strip()
            if not name:
                continue
            week_feel_count[name] = week_feel_count.get(name, 0) + 1
            intensity = f.get("intensity")
            if intensity is not None:
                week_feel_sum[name] = week_feel_sum.get(name, 0.0) + float(intensity)
                week_feel_rated[name] = week_feel_rated.get(name, 0) + 1
    top_week_feel = sorted(week_feel_count.items(), key=lambda kv: kv[1], reverse=True)[:8]

    with col_feel:
        st.markdown('<div class="section-label" style="margin-top:0">Top feelings</div>', unsafe_allow_html=True)
        if top_week_feel:
            chips = '<div class="keywords-row">'
            for name, ct in top_week_feel:
                if week_feel_rated.get(name):
                    avg_int = week_feel_sum[name] / week_feel_rated[name]
                    chips += f'<span class="kw-chip">{name} &middot; {ct} ({avg_int:.1f}/10)</span>'
                else:
                    chips += f'<span class="kw-chip kw-chip-neutral">{name} &middot; {ct}</span>'
            chips += '</div>'
            st.markdown(chips, unsafe_allow_html=True)
        else:
            st.markdown('<div style="color:#aaa; font-size:0.88rem">No feelings logged this week yet.</div>', unsafe_allow_html=True)


def render_reflection_trends_tab(rows, oura_by_date):
    st.markdown('<p class="title-text">Reflection trends</p>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888; font-size:0.92rem; margin-bottom:1.6rem">Long-horizon analytics &middot; mood trends &middot; biometric correlations &middot; AI-generated report</div>', unsafe_allow_html=True)

    MIN_ENTRIES = 7
    if len(rows) < MIN_ENTRIES:
        st.markdown(f'<div class="min-data-msg">Reflection trends need at least <strong>{MIN_ENTRIES} entries</strong> to surface patterns. You have <strong>{len(rows)}</strong> so far.</div>', unsafe_allow_html=True)
        return

    # ── Mood vs biometric scatter (user picks sleep / readiness / HRV / RHR / REM)
    oura_ui.render_mood_vs_biometric_chart(rows, oura_by_date)
    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    # Build structured summary for Claude
    recent = rows[:30]
    summary_lines = []
    for r in recent:
        kws = ", ".join(r.get("keywords") or [])
        # Pair each reflection with that day's Oura metrics (if available) so
        # Claude can spot correlations like "low HRV days have anxious keywords".
        oura_row = oura_by_date.get(r["entry_date"]) or {}
        oura_bits = []
        if oura_row.get("sleep_score") is not None:
            oura_bits.append(f"sleep {int(oura_row['sleep_score'])}")
        if oura_row.get("readiness_score") is not None:
            oura_bits.append(f"readiness {int(oura_row['readiness_score'])}")
        if oura_row.get("hrv_avg") is not None:
            oura_bits.append(f"hrv {int(oura_row['hrv_avg'])}ms")
        if oura_row.get("resting_hr") is not None:
            oura_bits.append(f"rhr {int(oura_row['resting_hr'])}")
        oura_str = f" | {' · '.join(oura_bits)}" if oura_bits else ""
        summary_lines.append(
            f"- {r['entry_date']} | mood: {r['mood']}{oura_str} | "
            f"keywords: {kws} | excerpt: {r['content'][:100]}"
        )
    summary_text = "\n".join(summary_lines)

    moods = [r["mood"] for r in recent]
    avg_m = round(sum(moods) / len(moods), 1)
    trend = moods[0] - moods[-1]  # newest - oldest (rows are desc)

    # Aggregate Oura stats + lightweight mood↔biometric correlations.
    # Doing the arithmetic in Python (rather than in the prompt) keeps Claude
    # from having to compute Pearson r on numbers it can easily get wrong.
    def _aligned(field: str) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for r in recent:
            v = (oura_by_date.get(r["entry_date"]) or {}).get(field)
            if v is not None:
                xs.append(float(v))
                ys.append(float(r["mood"]))
        return xs, ys

    def _corr(xs: list[float], ys: list[float]) -> str | None:
        if len(xs) < 5:
            return None
        try:
            r = float(np.corrcoef(xs, ys)[0, 1])
        except Exception:
            return None
        if np.isnan(r):
            return None
        if r > 0.4:
            strength = "moderate-to-strong positive"
        elif r > 0.2:
            strength = "weak positive"
        elif r < -0.4:
            strength = "moderate-to-strong negative"
        elif r < -0.2:
            strength = "weak negative"
        else:
            strength = "essentially none"
        return f"{strength} (r={r:.2f}, n={len(xs)})"

    oura_summary_lines = []
    for label, field in [("sleep score", "sleep_score"),
                         ("readiness", "readiness_score"),
                         ("HRV", "hrv_avg"),
                         ("resting HR", "resting_hr")]:
        xs, ys = _aligned(field)
        if not xs:
            continue
        avg = round(sum(xs) / len(xs), 1)
        line = f"- Avg {label}: {avg} (n={len(xs)})"
        c = _corr(xs, ys)
        if c is not None:
            line += f" · mood↔{label} correlation: {c}"
        oura_summary_lines.append(line)
    oura_block = "\n".join(oura_summary_lines) if oura_summary_lines else "- (no Oura data paired with these entries)"

    all_kws: list[str] = []
    for r in recent:
        all_kws.extend([k.lower() for k in (r.get("keywords") or [])])
    kw_freq = {}
    for k in all_kws:
        kw_freq[k] = kw_freq.get(k, 0) + 1
    top_kws = sorted(kw_freq, key=kw_freq.get, reverse=True)[:10]

    if st.button("Generate insight report", type="primary"):
        with st.spinner("Analyzing your reflections…"):
            prompt = f"""You are a thoughtful personal analytics assistant for a journaling app called Mirra.

Here are the user's {len(recent)} most recent reflection entries (newest first). Each line shows the reflection's date, self-reported mood (1–10), and — where available — that day's Oura Ring biometrics: sleep score (0–100), readiness score (0–100), heart-rate variability in milliseconds (higher = better recovery), and resting heart rate in bpm (lower = better recovery).

{summary_text}

Overall stats:
- Average mood (these entries): {avg_m}/10
- Mood trend: {"improving" if trend > 0.5 else "declining" if trend < -0.5 else "stable"}
- Most frequent keywords: {", ".join(top_kws)}

Biometric averages and mood correlations (Pearson r, computed across days where both mood and the metric exist):
{oura_block}

Write a warm, insightful personal trend report with exactly these 4 sections:

1. **Mood patterns** — describe specific mood trends, highs, lows, and what seems to drive them. Where the data supports it, link mood shifts to biometrics (e.g. "your lowest moods cluster on poor-sleep nights" — but only say this if the dates actually show it).
2. **Recurring themes** — what topics and phrases keep showing up, and what they might mean
3. **Notable correlations** — specific connections like "your mood drops when X appears" or "high-HRV days tend to mention Y." Use the correlation numbers above as a guide: only call something a real correlation if r is at least 0.3 in magnitude. If the strongest correlation is weak, say so honestly rather than inventing one.
4. **One thing to watch** — a gentle, actionable observation to carry forward

Be specific and reference actual keywords, dates, and biometric values from the data. Sound like a perceptive friend, not a clinical report. Keep each section to 2-4 sentences. Do not over-claim causation — Oura biometrics and self-reported mood are correlated signals, not proof one causes the other."""

            response = ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1100,
                messages=[{"role": "user", "content": prompt}]
            )
            report = response.content[0].text

        st.session_state["insight_report"] = report

    if "insight_report" in st.session_state:
        st.markdown(f'<div class="insight-card">{st.session_state["insight_report"].replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)

    # ── Reflection Trends Visualizations ──────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Reflection trends</div>', unsafe_allow_html=True)

    # 1. MOOD TIMESERIES
    mood_dates = [r["entry_date"] for r in rows]
    mood_values = [r["mood"] for r in rows]

    # Extract Oura HR + HRV data aligned with mood_dates
    rhr_values = []
    hrv_values = []
    for d in mood_dates:
        oura_row = oura_by_date.get(d)
        rhr_values.append(float(oura_row["resting_hr"]) if oura_row and oura_row.get("resting_hr") is not None else None)
        hrv_values.append(float(oura_row["hrv_avg"])    if oura_row and oura_row.get("hrv_avg")    is not None else None)

    # Z-score helper: standardise a series so all 3 metrics share one y-axis.
    # Hover tooltips still show the original value so the chart stays readable.
    def _zscore(values: list[float | None]) -> tuple[list[float | None], float, float]:
        present = [v for v in values if v is not None]
        if len(present) < 2:
            return [None] * len(values), 0.0, 1.0
        mean = float(np.mean(present))
        std = float(np.std(present)) or 1.0
        return [((v - mean) / std) if v is not None else None for v in values], mean, std

    mood_z, mood_mean, mood_std = _zscore(mood_values)
    rhr_z,  _, _ = _zscore(rhr_values)
    hrv_z,  _, _ = _zscore(hrv_values)

    def _build_mood_vs_metric_fig(
        title: str,
        metric_label: str,
        metric_z: list,
        metric_raw: list,
        metric_color: str,
        hover_unit: str,
    ) -> go.Figure:
        """Build one mood-vs-physiological-metric figure on a shared z-scale.

        Mood (filled area + markers + connector line) and the metric (line+markers)
        share one y-axis. Hover tooltips carry the original raw values so the chart
        is comparable across metrics without making the axis itself meaningless.
        """
        fig = go.Figure()

        # Filled area under mood (z-scored)
        fig.add_trace(go.Scatter(
            x=mood_dates, y=mood_z,
            fill="tozeroy",
            fillcolor="rgba(61, 171, 122, 0.1)",
            line=dict(color="rgba(0,0,0,0)"),
            showlegend=False,
            hoverinfo="skip",
        ))

        # Mood markers — hover shows the original 1–10 value, not the z-score.
        fig.add_trace(go.Scatter(
            x=mood_dates, y=mood_z,
            customdata=mood_values,
            mode="markers",
            name="Mood",
            marker=dict(size=8, color="#3dab7a", opacity=0.85, line=dict(width=1, color="white")),
            hovertemplate="<b>%{x}</b><br>Mood: %{customdata:.1f}<extra></extra>",
        ))

        # Mood trend — dashed green line connecting the actual mood points
        # day-by-day, matching the visual treatment used for Resting HR and HRV.
        # `connectgaps` bridges any missing days so the line stays continuous.
        fig.add_trace(go.Scatter(
            x=mood_dates, y=mood_z,
            mode="lines",
            name="Mood trend",
            line=dict(color="#3dab7a", width=2, dash="dash"),
            connectgaps=True,
            hoverinfo="skip",
        ))

        # Physiological metric — shared axis, hover shows raw units
        metric_with_data = [
            (d, z, raw)
            for d, z, raw in zip(mood_dates, metric_z, metric_raw)
            if z is not None
        ]
        if metric_with_data:
            m_dates, m_zs, m_raws = zip(*metric_with_data)
            fig.add_trace(go.Scatter(
                x=m_dates, y=m_zs,
                customdata=m_raws,
                mode="lines+markers",
                name=metric_label,
                line=dict(color=metric_color, width=2),
                marker=dict(size=5, color=metric_color),
                hovertemplate=f"<b>%{{x}}</b><br>{metric_label}: %{{customdata:.0f}} {hover_unit}<extra></extra>",
            ))

        fig.update_layout(
            title=title,
            xaxis_title="Date",
            paper_bgcolor="#f7f6f2",
            plot_bgcolor="#f7f6f2",
            font=dict(family="DM Sans", color="#2a2a2a"),
            height=280,
            hovermode="x unified",
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(
                x=0.01, y=0.99,
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="rgba(200,200,200,0.5)",
                borderwidth=1,
            ),
        )
        # Hide y-axis ticks — series are on a comparable scale, raw values live
        # in the hover tooltips.
        fig.update_yaxes(
            showticklabels=False, showgrid=True, zeroline=True,
            zerolinecolor="rgba(150,150,150,0.3)", title_text="",
        )
        return fig

    fig_mood_rhr = _build_mood_vs_metric_fig(
        title="Mood & Resting HR (standardised)",
        metric_label="Resting HR",
        metric_z=rhr_z,
        metric_raw=rhr_values,
        metric_color="#e05a3a",
        hover_unit="bpm",
    )
    fig_mood_hrv = _build_mood_vs_metric_fig(
        title="Mood & HRV (standardised)",
        metric_label="HRV",
        metric_z=hrv_z,
        metric_raw=hrv_values,
        metric_color="#5b6fa6",
        hover_unit="ms",
    )

    # ── Mood + sleep stack (4 sleep variables, stacked on shared z-axis) ─────
    # Each sleep series is standardised (z-scored) then shifted so its minimum
    # is 0, which lets us stack the areas. Y-axis ticks are hidden since the
    # numbers no longer carry real-world units; hover tooltips still show the
    # raw values + native units (score, h, min) so the chart stays readable.
    sleep_specs = [
        # (oura field,         legend label,    hover unit,    fill color)
        ("sleep_score",        "Sleep score",   "",            "#5b6fa6"),  # lavender
        ("sleep_hours",        "Sleep hours",   "h",           "#4a8db3"),  # teal-blue
        ("deep_sleep_min",     "Deep sleep",    "min",         "#7c5d99"),  # purple
        ("rem_sleep_min",      "REM sleep",     "min",         "#c89556"),  # warm amber
    ]
    # Extract aligned raw + z-scored series for each sleep variable.
    sleep_series: list[dict] = []
    for field, label, unit, color in sleep_specs:
        raw = [
            float(oura_by_date[d][field])
            if (oura_by_date.get(d) and oura_by_date[d].get(field) is not None)
            else None
            for d in mood_dates
        ]
        z, _, _ = _zscore(raw)
        sleep_series.append({
            "label": label, "unit": unit, "color": color, "raw": raw, "z": z,
        })

    def _fill_and_shift(z_vals: list[float | None]) -> list[float]:
        """Stacked areas need a value at every x; missing days break the stack.
        Forward-fill from the previous day, back-fill at the start. Then shift
        so the minimum sits at 0 (lets the area stack from a baseline of 0
        without negative-value clipping)."""
        filled: list[float] = []
        last: float | None = None
        for v in z_vals:
            if v is not None:
                last = float(v)
            filled.append(last if last is not None else 0.0)
        # Back-fill leading None's with the first non-None value.
        first_real = next((v for v in z_vals if v is not None), None)
        if first_real is not None:
            for i, v in enumerate(z_vals):
                if v is not None:
                    break
                filled[i] = float(first_real)
        # Shift so min is 0. If everything is the same value, leave as-is.
        m = min(filled) if filled else 0.0
        return [x - m for x in filled]

    fig_mood_sleep = go.Figure()
    # Stacked sleep areas. `stackgroup` makes the y-values cumulative; fills
    # are translucent (alpha 0.4) so overlapping series read as layered bands
    # rather than solid blocks.
    def _rgba(hex_color: str, alpha: float) -> str:
        """Convert '#rrggbb' to 'rgba(r,g,b,alpha)' for Plotly fill colors."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    BAND_ALPHA = 0.4

    for s in sleep_series:
        # Skip the trace entirely if this variable has no data at all.
        if all(z is None for z in s["z"]):
            continue
        shifted = _fill_and_shift(s["z"])
        # Build hover text from raw values so users see real units, not z-scores.
        hover_text = []
        for raw in s["raw"]:
            if raw is None:
                hover_text.append(f"{s['label']}: —")
            elif s["unit"]:
                hover_text.append(f"{s['label']}: {raw:.0f} {s['unit']}")
            else:
                hover_text.append(f"{s['label']}: {raw:.0f}")
        fig_mood_sleep.add_trace(go.Scatter(
            x=mood_dates, y=shifted,
            mode="lines", name=s["label"],
            stackgroup="sleep",
            line=dict(width=0.5, color=s["color"], shape="spline", smoothing=0.6),
            fillcolor=_rgba(s["color"], BAND_ALPHA),
            text=hover_text,
            hovertemplate="%{text}<extra></extra>",
        ))

    # Mood on a secondary y-axis so its un-shifted z-scale doesn't get
    # stretched by the stacked sleep total. Filled translucent green area
    # underneath the dashed line — matches the alpha-0.4 treatment of the
    # sleep bands so all five series read as the same visual family.
    fig_mood_sleep.add_trace(go.Scatter(
        x=mood_dates, y=mood_z, customdata=mood_values,
        mode="lines+markers", name="Mood",
        line=dict(color="#3dab7a", width=2.2, dash="dash"),
        marker=dict(size=6, color="#3dab7a", line=dict(width=1, color="white")),
        fill="tozeroy",
        fillcolor=_rgba("#3dab7a", BAND_ALPHA),
        yaxis="y2",
        connectgaps=True,
        hovertemplate="<b>%{x}</b><br>Mood: %{customdata:.1f}<extra></extra>",
    ))

    fig_mood_sleep.update_layout(
        title="Mood & Sleep (standardised, stacked)",
        xaxis_title="Date",
        paper_bgcolor="#f7f6f2", plot_bgcolor="#f7f6f2",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=320,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(
            x=0.01, y=0.99,
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="rgba(200,200,200,0.5)",
            borderwidth=1,
        ),
        # Primary axis = stacked sleep total (hidden ticks, meaningless units).
        yaxis=dict(
            showticklabels=False, showgrid=True, zeroline=True,
            zerolinecolor="rgba(150,150,150,0.3)", title_text="",
        ),
        # Secondary axis = mood z-score, also hidden — keeps the chart focused
        # on shape comparisons rather than numeric reading.
        yaxis2=dict(
            overlaying="y", side="right",
            showticklabels=False, showgrid=False, zeroline=False,
            title_text="",
        ),
    )

    # KEYWORD FREQUENCY BAR CHART
    fig_kw = None
    if top_kws:
        kw_names = [kw.title() for kw in top_kws]
        kw_counts = [kw_freq[kw] for kw in top_kws]
        
        fig_kw = go.Figure()
        fig_kw.add_trace(go.Bar(
            x=kw_names,
            y=kw_counts,
            marker=dict(color="#e05a3a"),
            hovertemplate="<b>%{x}</b><br>Occurrences: %{y}<extra></extra>"
        ))
        fig_kw.update_layout(
            title="Top Keywords This Month",
            xaxis_title="Keyword",
            yaxis_title="Frequency",
            paper_bgcolor="#f7f6f2",
            plot_bgcolor="#f7f6f2",
            font=dict(family="DM Sans", color="#2a2a2a"),
            height=320,
            showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis_tickangle=-45,
        )

    # Display 2-column dashboard. Left column stacks the two single-metric
    # mood charts (RHR, HRV). Right column stacks the multi-series mood+sleep
    # chart on top of the keyword frequency bar. Four charts total.
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(fig_mood_rhr, use_container_width=True)
        st.plotly_chart(fig_mood_hrv, use_container_width=True)
    with col2:
        st.plotly_chart(fig_mood_sleep, use_container_width=True)
        if fig_kw:
            st.plotly_chart(fig_kw, use_container_width=True)

    # ── Mood Distribution with Filters ────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Mood Distribution & Statistics</div>', unsafe_allow_html=True)

    # Build filter options
    # 1. Day of week filter
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    row_dates = [datetime.fromisoformat(r["entry_date"]).date() for r in rows]
    row_dow = [days_of_week[datetime.fromisoformat(r["entry_date"]).weekday()] for r in rows]
    
    # 2. Build keyword list with counts (min count of 2)
    kw_freq_all = {}
    for r in rows:
        for kw in (r.get("keywords") or []):
            kw_lower = kw.lower()
            kw_freq_all[kw_lower] = kw_freq_all.get(kw_lower, 0) + 1
    
    kw_with_min_count = sorted(
        [kw for kw, count in kw_freq_all.items() if count >= 2],
        key=lambda x: kw_freq_all[x],
        reverse=True
    )

    # Create filter UI
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        selected_days = st.multiselect(
            "Filter by day of week",
            days_of_week,
            default=days_of_week,
            key="mood_dist_days"
        )
    with filter_col2:
        selected_kws = st.multiselect(
            "Filter by keywords (min 2 occurrences)",
            kw_with_min_count,
            default=kw_with_min_count[:5] if len(kw_with_min_count) > 5 else kw_with_min_count,
            key="mood_dist_kws"
        )

    # Apply filters to get filtered mood values
    filtered_moods = []
    for i, r in enumerate(rows):
        # Check day filter
        if row_dow[i] not in selected_days:
            continue
        
        # Check keyword filter
        entry_kws = [kw.lower() for kw in (r.get("keywords") or [])]
        if selected_kws:
            if not any(kw in entry_kws for kw in selected_kws):
                continue
        
        filtered_moods.append(r["mood"])

    # Create mood distribution chart with filtered data
    fig_mood_dist = go.Figure()
    fig_mood_dist.add_trace(go.Violin(
        y=filtered_moods if filtered_moods else mood_values,
        name="Mood Distribution",
        marker=dict(color="#d4850a"),
        meanline_visible=True,
        points=False,
    ))
    fig_mood_dist.update_layout(
        title=f"Mood Distribution ({len(filtered_moods)} entries)",
        yaxis_title="Mood (1-10)",
        paper_bgcolor="#f7f6f2",
        plot_bgcolor="#f7f6f2",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=300,
        showlegend=False,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    fig_mood_dist.update_yaxes(range=[0, 15])
    st.plotly_chart(fig_mood_dist, use_container_width=True)

    # Cosine similarity: find most similar past entry to today's
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Similar past entries</div>', unsafe_allow_html=True)
    today_rows = [r for r in rows if r["entry_date"] == user_today().isoformat()]
    if today_rows and len(rows) > 1:
        texts = [r["content"] for r in rows]
        with st.spinner("Computing similarity…"):
            embs = get_embeddings(texts)
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        normed = embs / np.where(norms == 0, 1, norms)
        sims = normed[0] @ normed[1:].T
        top_idx = np.argsort(sims)[::-1][:3]
        for idx in top_idx:
            r = rows[idx + 1]
            score = round(float(sims[idx]), 2)
            kws = " · ".join((r.get("keywords") or [])[:4])
            st.markdown(f"""
            <div style="background:#f0efe8; border-radius:10px; padding:10px 14px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:flex-start; gap:12px">
                <div>
                    <div style="font-size:0.82rem; color:#aaa; margin-bottom:3px">{r['entry_date']} · mood {r['mood']}</div>
                    <div style="font-size:0.92rem; color:#2a2a2a">{r['content'][:100]}…</div>
                    <div style="font-size:0.8rem; color:#3dab7a; margin-top:4px">{kws}</div>
                </div>
                <div style="font-size:0.85rem; font-weight:600; color:#3dab7a; white-space:nowrap">{score} sim</div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div style="color:#bbb; font-size:0.9rem">Save today\'s reflection first to find similar past entries.</div>', unsafe_allow_html=True)


# ── Daily reflection tab ──────────────────────────────────────────────────────
# Per spec: this page is just the writing/mood/feelings inputs — no Oura
# badges, no historical stats grid. Those moved to Weekly Insights / Reflection
# Trends to keep the daily writing space distraction-free.
def render_daily_reflection_tab(rows):
    _, _, _, streak, today_row = load_stats(rows)
    default_content = today_row["content"] if today_row else ""
    # Default to 5.0 (neutral) for a brand-new entry; existing entries keep
    # their saved value. Matches the "skip = stored as 5" convention so the
    # default state of the slider lines up with the no-input state.
    default_mood    = float(today_row["mood"]) if today_row else 5.0
    if today_row and not st.session_state.get("keywords"):
        st.session_state["keywords"] = today_row.get("keywords") or []

    today_str  = user_today().strftime("%A · %B") + f" {user_today().day}, {user_today().year}"
    streak_lbl = f"{streak}-day streak" if streak > 1 else ("Start your streak" if streak == 0 else "Day 1 streak")

    col_title, col_streak = st.columns([3, 1])
    with col_title:
        st.markdown(f'<div class="date-label">{today_str}</div>', unsafe_allow_html=True)
        st.markdown('<p class="title-text">Today\'s reflection</p>', unsafe_allow_html=True)
    with col_streak:
        st.markdown(f'<div style="text-align:right;padding-top:4px"><span class="streak-badge">{streak_lbl}</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">What\'s on your mind?</div>', unsafe_allow_html=True)
    content = st.text_area("reflection", value=default_content,
                           placeholder="Write about your day, what you're feeling, what went well or didn't…",
                           height=140, label_visibility="collapsed")

    st.markdown('<div class="section-label">Mood (1–10)</div>', unsafe_allow_html=True)

    # Skip toggle: when checked, no mood is recorded for the day and the DB
    # stores 5.0 (neutral) so downstream averages/charts still have a value
    # but it's clearly the "no input" sentinel. Slider is disabled in this
    # state to make the absence of a choice visually obvious.
    skip_mood = st.checkbox(
        "Skip mood today (stored as 5)",
        value=False,
        key="skip_mood",
    )

    mood_col, val_col = st.columns([10, 1])
    with mood_col:
        # Continuous scale: step=0.1 so the slider feels smooth rather than
        # snapping to half-points like the old ordinal version.
        mood_slider_value = st.slider(
            "mood", 1.0, 10.0, default_mood,
            step=0.1,
            label_visibility="collapsed",
            disabled=skip_mood,
        )
    mood = 5.0 if skip_mood else float(mood_slider_value)
    with val_col:
        display_mood = "—" if skip_mood else f"{mood:.1f}"
        st.markdown(
            f'<div class="mood-value" style="padding-top:18px">{display_mood}</div>',
            unsafe_allow_html=True,
        )

    # ── Feelings ──
    # Multiselect of common affect words, plus free-text via accept_new_options.
    # Each selected feeling gets a 1–10 slider with a "skip rating" checkbox —
    # skip-checked stores intensity=null so we distinguish "felt it but didn't
    # rate it" from "rated it 5".
    st.markdown('<div class="section-label">Feelings</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="feeling-hint">Pick any that fit. You can type your own. '
        'Rate each one 1&ndash;10, or check &ldquo;skip rating&rdquo; to leave it unrated.</div>',
        unsafe_allow_html=True,
    )

    # Seed defaults from today_row on first render. We write directly into the
    # widget's session_state key rather than using `default=` so Streamlit doesn't
    # warn about having both `default` and `key` on the same widget — once a key
    # is set, the widget reads from it on every rerun.
    if today_row and "feelings_seeded" not in st.session_state:
        stored = today_row.get("feelings") or []
        st.session_state["feelings_selected"] = [
            f["name"] for f in stored if f.get("name")
        ]
        for f in stored:
            name = f.get("name")
            intensity = f.get("intensity")
            if name and intensity is not None:
                st.session_state[f"intensity_{name}"] = float(intensity)
        st.session_state["feelings_seeded"] = True

    selected_feelings = st.multiselect(
        "feelings",
        options=PRESET_FEELINGS,
        accept_new_options=True,
        label_visibility="collapsed",
        placeholder="Add feelings…",
        key="feelings_selected",
    )

    feelings_payload: list[dict] = []
    if selected_feelings:
        for name in selected_feelings:
            skip_key = f"skip_intensity_{name}"
            slider_key = f"intensity_{name}"
            if skip_key not in st.session_state:
                st.session_state[skip_key] = slider_key not in st.session_state
            if slider_key not in st.session_state:
                st.session_state[slider_key] = 5.0

            name_col, skip_col, slider_col = st.columns([2, 2, 6])
            with name_col:
                st.markdown(
                    f'<div class="feeling-name">{name}</div>',
                    unsafe_allow_html=True,
                )
            with skip_col:
                skip_rating = st.checkbox(
                    "Skip rating",
                    key=skip_key,
                )
            with slider_col:
                rating = st.slider(
                    f"rate {name} 1–10",
                    1.0, 10.0,
                    step=0.1,
                    label_visibility="collapsed",
                    disabled=skip_rating,
                    key=slider_key,
                )

            feelings_payload.append({
                "name": name,
                "intensity": None if skip_rating else float(rating),
            })
    else:
        st.markdown(
            '<div class="feeling-skip">No feelings selected.</div>',
            unsafe_allow_html=True,
        )

    st.markdown("""<div class="kw-header">
      <div class="section-label" style="margin-top:1.4rem">Detected keywords</div>
      <div class="kw-ai-label">spaCy &middot; AI-extracted</div>
    </div>""", unsafe_allow_html=True)

    kws = st.session_state.get("keywords", [])
    if kws:
        highlight = {"anxiety","stress","overwhelm","deadline","support","teamwork","grateful","joy","focus","self-care"}
        chips = '<div class="keywords-row">'
        for kw in kws:
            cls = "kw-chip" if kw.lower() in highlight else "kw-chip kw-chip-neutral"
            chips += f'<span class="{cls}">{kw}</span>'
        chips += "</div>"
        st.markdown(chips, unsafe_allow_html=True)
    else:
        st.markdown('<div style="color:#bbb;font-size:0.9rem;margin-top:0.4rem">Keywords will appear after you save your reflection.</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _, btn_clear, btn_save = st.columns([4, 1.2, 1.8])
    with btn_clear:
        if st.button("Clear", use_container_width=True):
            st.session_state["keywords"] = []
            st.session_state["save_success"] = False
            # Wipe feelings state too — multiselect, the one-time seed marker,
            # and any per-feeling intensity / skip toggle values keyed by name.
            for key in list(st.session_state.keys()):
                if (
                    key.startswith("intensity_")
                    or key.startswith("skip_intensity_")
                    or key in ("feelings_selected", "feelings_seeded")
                ):
                    del st.session_state[key]
            st.rerun()
    with btn_save:
        if st.button("Save reflection", type="primary", use_container_width=True):
            if content.strip():
                with st.spinner("Extracting keywords…"):
                    kws = extract_keywords(content)
                st.session_state["keywords"] = kws
                save_reflection(content, mood, kws, st.session_state["user_id"],
                                feelings=feelings_payload)
                st.session_state["save_success"] = True
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("Write something first before saving.")

    if st.session_state.get("save_success"):
        st.markdown('<div class="save-msg">&check; Reflection saved for today.</div>', unsafe_allow_html=True)




# ── App entry point: dispatch tabs ──────────────────────────────────────────
user_id = st.session_state["user_id"]
oura_ui.handle_oauth_callback(supabase, user_id)
rows = load_all_entries(user_id)

# Pull fresh Oura data if today's row is missing/incomplete (throttled to 15 min).
oura.auto_sync_if_stale(
    supabase, user_id,
    client_id=st.secrets.get("OURA_CLIENT_ID"),
    client_secret=st.secrets.get("OURA_CLIENT_SECRET"),
)
oura_by_date = oura.load_oura_for_user(supabase, user_id)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Daily Reflection",
    "Weekly Insights",
    "Reflection Trends",
    "Topic Map",
    "Dendrogram",
    "Settings",
])

with tab1:
    render_daily_reflection_tab(rows)

with tab2:
    render_weekly_insights_tab(rows, oura_by_date)

with tab3:
    render_reflection_trends_tab(rows, oura_by_date)

with tab4:
    render_bertopic_tab(rows)

with tab5:
    render_dendrogram_tab(rows)

with tab6:
    oura_ui.render_settings_tab(supabase, user_id)