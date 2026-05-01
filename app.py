import streamlit as st
import anthropic
import base64
import hashlib
from supabase import create_client
from datetime import date, datetime, timedelta
import json
import numpy as np
import plotly.graph_objects as go


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mirra", page_icon="🌿", layout="centered")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; background-color: #f7f6f2; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 2rem 2rem 4rem 2rem; max-width: 1200px; }

/* Tab styling */
.stTabs [data-baseweb="tab-list"] { gap: 4px; background: #eeeee8; border-radius: 12px; padding: 4px; }
.stTabs [data-baseweb="tab"] {
    border-radius: 9px; padding: 6px 16px; font-size: 0.88rem;
    font-weight: 500; color: #888; background: transparent; border: none;
}
.stTabs [aria-selected="true"] { background: white !important; color: #1a1a1a !important; font-weight: 600; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.6rem; }

.date-label { font-size: 0.88rem; color: #888; margin-bottom: 0.1rem; }
.title-text { font-family: 'Lora', serif; font-size: 1.75rem; font-weight: 700; color: #1a1a1a; margin: 0; }
.streak-badge { background:#e8f5f0; border:1.5px solid #3dab7a; color:#2a8a5e; padding:0.35rem 0.9rem; border-radius:999px; font-size:0.88rem; font-weight:600; }
.section-label { font-size: 1.05rem; font-weight: 600; color: #1a1a1a; margin-bottom: 0.5rem; margin-top: 1.4rem; }

textarea { background-color: #f0efe8 !important; border: 1.5px solid #ddd !important; border-radius: 12px !important; font-family: 'DM Sans', sans-serif !important; font-size: 1rem !important; color: #2a2a2a !important; }
textarea:focus { border-color: #3dab7a !important; }

.stSlider > div > div > div > div { background-color: #3dab7a !important; }
[data-testid="stSlider"] [role="slider"] { background-color: #3dab7a !important; border: 2px solid white !important; box-shadow: 0 2px 6px rgba(61,171,122,0.4) !important; }
.mood-value { font-size: 1.5rem; font-weight: 700; color: #3dab7a; }

.keywords-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 0.5rem; }
.kw-chip { display:inline-block; padding:5px 14px; border-radius:999px; font-size:0.88rem; font-weight:500; background:#e8f5f0; border:1.5px solid #3dab7a; color:#2a7a55; }
.kw-chip-neutral { background:#f5f5f2; border:1.5px solid #ccc; color:#555; }
.kw-header { display:flex; justify-content:space-between; align-items:center; }
.kw-ai-label { font-size:0.78rem; color:#aaa; }
.divider { border:none; border-top:1px solid #e5e5e0; margin:1.4rem 0; }

.stat-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-top:0.6rem; }
.stat-card { background:#f0efe8; border-radius:14px; padding:1rem 1.1rem 0.9rem; }
.stat-card-label { font-size:0.7rem; font-weight:600; letter-spacing:0.08em; color:#888; text-transform:uppercase; margin-bottom:4px; }
.stat-card-value { font-family:'Lora',serif; font-size:1.85rem; font-weight:700; color:#1a1a1a; line-height:1.1; }
.stat-card-sub { font-size:0.8rem; color:#999; margin-top:3px; }

.save-msg { background:#e8f5f0; border-left:4px solid #3dab7a; border-radius:8px; padding:0.7rem 1rem; color:#1e6b45; font-weight:500; margin-top:0.8rem; }

/* Login page */
.login-wrap { max-width: 420px; margin: 0 auto; padding-top: 0.5rem; }
.login-logo { text-align: center; margin-bottom: 1.2rem; }
.login-title { font-family: 'Lora', serif; font-size: 2rem; font-weight: 700; color: #1a1a1a; text-align: center; margin-bottom: 0.2rem; }
.login-sub { color: #888; font-size: 0.92rem; text-align: center; letter-spacing: 0.04em; margin-bottom: 1.2rem; }
.login-card { background: white; border-radius: 18px; padding: 1.4rem 2rem 2rem; box-shadow: 0 2px 20px rgba(0,0,0,0.07); }
.login-tabs { display: flex; gap: 0; background: #f0efe8; border-radius: 10px; padding: 3px; margin-bottom: 1.4rem; }
.login-tab { flex: 1; text-align: center; padding: 8px; border-radius: 8px; font-size: 0.9rem; font-weight: 500; color: #888; cursor: pointer; }
.login-tab-active { background: white; color: #1a1a1a; font-weight: 600; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.logout-btn { position: fixed; top: 14px; right: 18px; z-index: 999; }
/* Kill phantom empty block above first login input */
.login-card > div:first-child:empty { display: none; }
.block-container > div:first-child { padding-top: 0 !important; }

.insight-card { background:#f0efe8; border-radius:14px; padding:1.2rem 1.4rem; margin-bottom:1rem; line-height:1.7; color:#2a2a2a; font-size:0.97rem; }
.insight-header { font-family:'Lora',serif; font-size:1.3rem; font-weight:700; color:#1a1a1a; margin-bottom:1rem; }
.min-data-msg { background:#fff8e8; border:1.5px solid #f0c040; border-radius:12px; padding:1rem 1.2rem; color:#7a5a10; font-size:0.92rem; margin-top:1rem; }
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
    _, embedder = load_nlp_models()
    return embedder.encode(texts, show_progress_bar=False)


# ── Supabase helpers ──────────────────────────────────────────────────────────
def save_reflection(content: str, mood: float, keywords: list[str], user_id: str):
    today = date.today().isoformat()
    supabase.table("reflections").upsert({
        "entry_date": today,
        "content": content,
        "mood": mood,
        "keywords": keywords,
        "user_id": user_id,
        "updated_at": datetime.utcnow().isoformat(),
    }, on_conflict="user_id,entry_date").execute()


@st.cache_data(ttl=60)
def load_all_entries(user_id: str) -> list[dict]:
    res = supabase.table("reflections").select("*").eq("user_id", user_id).order("entry_date", desc=True).execute()
    return res.data or []


def load_stats(rows):
    total = len(rows)
    cutoff_30 = (date.today() - timedelta(days=30)).isoformat()
    recent = [r for r in rows if r["entry_date"] >= cutoff_30]
    avg_mood = round(sum(r["mood"] for r in recent) / len(recent), 1) if recent else 0.0
    cutoff_7 = (date.today() - timedelta(days=7)).isoformat()
    week_rows = [r for r in rows if r["entry_date"] >= cutoff_7]
    kw_count: dict[str, int] = {}
    for r in week_rows:
        for kw in (r.get("keywords") or []):
            kw_count[kw.lower()] = kw_count.get(kw.lower(), 0) + 1
    top_topic = max(kw_count, key=kw_count.get) if kw_count else "—"
    dated = sorted({r["entry_date"] for r in rows}, reverse=True)
    streak, check = 0, date.today()
    for d in dated:
        if d == check.isoformat():
            streak += 1; check -= timedelta(days=1)
        else:
            break
    today_rows = [r for r in rows if r["entry_date"] == date.today().isoformat()]
    return total, avg_mood, top_topic, streak, (today_rows[0] if today_rows else None)


# ── Topic Map: UMAP + HDBSCAN (no BERTopic dependency) ───────────────────────
@st.cache_data(ttl=300)
def run_topic_map(texts: tuple, moods: tuple = None):
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import TfidfVectorizer

    _, embedder = load_nlp_models()
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
        st.markdown(f'<div class="min-data-msg">⚠️ Topic modeling needs at least <strong>{MIN_ENTRIES} entries</strong>. You have <strong>{len(rows)}</strong> so far — keep journaling!</div>', unsafe_allow_html=True)
        return

    texts = [r["content"] for r in rows]
    dates = [r["entry_date"] for r in rows]
    moods = [r["mood"] for r in rows]

    if not st.button("▶ Run Topic Model", type="primary", key="run_topic_map"):
        st.markdown('<div style="color:#aaa; font-size:0.92rem; margin-top:0.5rem">Click to cluster your entries with UMAP + HDBSCAN. Takes ~20 sec on first run.</div>', unsafe_allow_html=True)
        return

    status = st.status("Building topic map…", expanded=True)
    with status:
        st.write("⏳ Loading NLP models…")
        load_nlp_models()
        st.write("🔢 Embedding + clustering…")
        try:
            reduced, topics, topic_labels, text_list = run_topic_map(tuple(texts), tuple(moods))
        except Exception as e:
            st.error(f"Topic map failed: {e}")
            return
        st.write("✅ Done!")
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
                    <span style="margin-right:12px">📊 {count} entries</span>
                    <span>😊 avg mood {avg_m}</span>
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
        st.markdown(f'<div class="min-data-msg">⚠️ The dendrogram needs at least <strong>{MIN_ENTRIES} entries</strong>. You have <strong>{len(rows)}</strong> so far.</div>', unsafe_allow_html=True)
        return

    # ── Extract meaningful noun phrases (syntactic approach) ──────────────────
    unique_phrases = extract_noun_phrase_clusters(rows, top_n=60)

    if len(unique_phrases) < 4:
        st.markdown('<div class="min-data-msg">⚠️ Not enough recurring 3–5 word noun phrases yet. Keep logging!</div>', unsafe_allow_html=True)
        return

    # ── Semantic query input ───────────────────────────────────────────────────
    st.markdown("""
    <div style="background:#f0efe8; border-radius:14px; padding:1rem 1.2rem 0.6rem; margin-bottom:1rem;">
      <div style="font-size:0.82rem; font-weight:600; letter-spacing:0.06em; color:#888; text-transform:uppercase; margin-bottom:0.5rem;">
        🔍 Explore a theme
      </div>
      <div style="font-size:0.92rem; color:#555; margin-bottom:0.7rem; line-height:1.5;">
        Enter a concept or feeling and the dendrogram will show the <strong>top 25 phrases from your reflections</strong>
        most semantically related to it — revealing hidden thought patterns and contextual themes around that topic.
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
    run_clicked = st.button("\u25b6 Run Dendrogram", type="primary", key="run_dendro")

    if run_clicked:
        status = st.status("Building dendrogram…", expanded=True)
        with status:
            st.write("⏳ Loading NLP models…")
            load_nlp_models()

            # Apply semantic filter if a query was entered
            if query.strip():
                st.write(f"🔎 Finding top 25 phrases related to '{query.strip()}'…")
                phrases_to_cluster = get_top_similar_phrases(query.strip(), unique_phrases, top_n=25)
                if len(phrases_to_cluster) < 4:
                    st.error("Not enough matching phrases for the query. Try a broader theme.")
                    # Show top similar phrases for debugging
                    all_sims = get_top_similar_phrases(query.strip(), unique_phrases, top_n=min(15, len(unique_phrases)))
                    st.warning(f"**Top phrases found similar to '{query.strip()}':**\n" + "\n".join([f"• {p}" for p in all_sims]))
                    return
            else:
                phrases_to_cluster = unique_phrases

            st.write("📝 Embedding phrases with sentence-transformers…")
            st.write("🔗 Clustering semantically similar phrases…")
            try:
                phrases, Z, cluster_ids = run_dendrogram(tuple(phrases_to_cluster))
            except Exception as e:
                st.error(f"Dendrogram failed: {e}")
                return
            if phrases is None:
                st.info("Not enough unique phrases yet.")
                return
            st.write("\u2705 Done!")
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
            f'<div style="display:inline-flex;align-items:center;gap:8px;background:#e8f5f0;border:1.5px solid #3dab7a;'
            f'border-radius:999px;padding:5px 14px;font-size:0.85rem;color:#2a7a55;margin-bottom:0.8rem;">'
            f'<span>🎯</span><span>Showing phrases related to <strong>{active_query}</strong></span>'
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



# ── Insights agent ────────────────────────────────────────────────────────────
def render_insights_tab(rows):
    st.markdown('<p class="title-text">Insights</p>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">Claude analytics agent · mood trends · keyword correlations · reflection analytics</div>', unsafe_allow_html=True)

    MIN_ENTRIES = 7
    if len(rows) < MIN_ENTRIES:
        st.markdown(f'<div class="min-data-msg">⚠️ Insights need at least <strong>{MIN_ENTRIES} entries</strong> to surface patterns. You have <strong>{len(rows)}</strong> so far.</div>', unsafe_allow_html=True)
        return

    # Build structured summary for Claude
    recent = rows[:30]
    summary_lines = []
    for r in recent:
        kws = ", ".join(r.get("keywords") or [])
        summary_lines.append(f"- {r['entry_date']} | mood: {r['mood']} | keywords: {kws} | excerpt: {r['content'][:100]}")
    summary_text = "\n".join(summary_lines)

    moods = [r["mood"] for r in recent]
    avg_m = round(sum(moods) / len(moods), 1)
    trend = moods[0] - moods[-1]  # newest - oldest (rows are desc)

    all_kws: list[str] = []
    for r in recent:
        all_kws.extend([k.lower() for k in (r.get("keywords") or [])])
    kw_freq = {}
    for k in all_kws:
        kw_freq[k] = kw_freq.get(k, 0) + 1
    top_kws = sorted(kw_freq, key=kw_freq.get, reverse=True)[:10]

    if st.button("✨ Generate insight report", type="primary"):
        with st.spinner("Analyzing your reflections…"):
            prompt = f"""You are a thoughtful personal analytics assistant for a journaling app called Mirra.

Here are the user's {len(recent)} most recent reflection entries (newest first):
{summary_text}

Overall stats:
- Average mood (these entries): {avg_m}/10
- Mood trend: {"improving" if trend > 0.5 else "declining" if trend < -0.5 else "stable"}
- Most frequent keywords: {", ".join(top_kws)}

Write a warm, insightful personal trend report with exactly these 4 sections:

1. **Mood patterns** — describe specific mood trends, highs, lows, and what seems to drive them
2. **Recurring themes** — what topics and phrases keep showing up, and what they might mean
3. **Notable correlations** — specific connections like "your mood drops when X appears" or "you feel better on days when Y comes up"
4. **One thing to watch** — a gentle, actionable observation to carry forward

Be specific and reference actual keywords and dates from the data. Sound like a perceptive friend, not a clinical report. Keep each section to 2-4 sentences."""

            response = ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=900,
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
    
    # Calculate trend line using numpy polyfit
    x_numeric = np.arange(len(mood_values))
    z = np.polyfit(x_numeric, mood_values, 2)  # 2nd degree polynomial for smooth trend
    p = np.poly1d(z)
    trend_line = p(x_numeric)
    
    fig_mood = go.Figure()
    
    # Add filled area under the curve
    fig_mood.add_trace(go.Scatter(
        x=mood_dates, y=mood_values,
        fill="tozeroy",
        fillcolor="rgba(61, 171, 122, 0.1)",
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=False,
        hoverinfo="skip"
    ))
    
    # Add scatter points
    fig_mood.add_trace(go.Scatter(
        x=mood_dates, y=mood_values,
        mode="markers",
        name="Mood",
        marker=dict(size=8, color="#3dab7a", opacity=0.85, line=dict(width=1, color="white")),
        hovertemplate="<b>%{x}</b><br>Mood: %{y:.1f}<extra></extra>"
    ))
    
    # Add trend line
    fig_mood.add_trace(go.Scatter(
        x=mood_dates, y=trend_line,
        mode="lines",
        name="Trend",
        line=dict(color="#d4850a", width=2.5, dash="dash"),
        hovertemplate="<b>%{x}</b><br>Trend: %{y:.1f}<extra></extra>"
    ))
    
    fig_mood.update_layout(
        title="Mood Over Time",
        xaxis_title="Date",
        yaxis_title="Mood (1-10)",
        paper_bgcolor="#f7f6f2",
        plot_bgcolor="#f7f6f2",
        font=dict(family="DM Sans", color="#2a2a2a"),
        height=320,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)", bordercolor="rgba(200,200,200,0.5)", borderwidth=1)
    )
    fig_mood.update_yaxes(range=[0, 10])

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

    # Display 2-column dashboard
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(fig_mood, use_container_width=True)
    with col2:
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
    fig_mood_dist.update_yaxes(range=[0, 10])
    st.plotly_chart(fig_mood_dist, use_container_width=True)

    # Cosine similarity: find most similar past entry to today's
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Similar past entries</div>', unsafe_allow_html=True)
    today_rows = [r for r in rows if r["entry_date"] == date.today().isoformat()]
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


# ── Today's reflection tab ────────────────────────────────────────────────────
def render_today_tab(rows):
    total, avg_mood_30d, top_topic, streak, today_row = load_stats(rows)
    default_content = today_row["content"] if today_row else ""
    default_mood    = float(today_row["mood"]) if today_row else 6.5
    if today_row and not st.session_state.get("keywords"):
        st.session_state["keywords"] = today_row.get("keywords") or []

    today_str  = date.today().strftime("%A · %B") + f" {date.today().day}, {date.today().year}"
    streak_lbl = f"🔥 {streak}-day streak" if streak > 1 else ("✨ Start your streak!" if streak == 0 else "Day 1 streak!")

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
    mood_col, val_col = st.columns([10, 1])
    with mood_col:
        mood = st.slider("mood", 1.0, 10.0, default_mood, step=0.5, label_visibility="collapsed")
    with val_col:
        st.markdown(f'<div class="mood-value" style="padding-top:18px">{mood}</div>', unsafe_allow_html=True)

    st.markdown("""<div class="kw-header">
      <div class="section-label" style="margin-top:1rem">Detected keywords</div>
      <div class="kw-ai-label"> AI-extracted</div>
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
        st.markdown('<div style="color:#bbb;font-size:0.9rem;margin-top:0.4rem">Keywords will appear after you write your reflection.</div>', unsafe_allow_html=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-card-label">Entries</div><div class="stat-card-value">{total}</div><div class="stat-card-sub">total logged</div></div>
      <div class="stat-card"><div class="stat-card-label">Avg Mood</div><div class="stat-card-value">{avg_mood_30d}</div><div class="stat-card-sub">past 30 days</div></div>
      <div class="stat-card"><div class="stat-card-label">Top Topic</div><div class="stat-card-value" style="font-size:1.3rem;padding-top:4px">{top_topic}</div><div class="stat-card-sub">this week</div></div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _, btn_clear, btn_save = st.columns([4, 1.2, 1.8])
    with btn_clear:
        if st.button("Clear", use_container_width=True):
            st.session_state["keywords"] = []
            st.session_state["save_success"] = False
            st.rerun()
    with btn_save:
        if st.button("Save reflection", type="primary", use_container_width=True):
            if content.strip():
                with st.spinner("Extracting keywords…"):
                    kws = extract_keywords(content)
                st.session_state["keywords"] = kws
                save_reflection(content, mood, kws, st.session_state["user_id"])
                st.session_state["save_success"] = True
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("Write something first before saving.")

    if st.session_state.get("save_success"):
        st.markdown('<div class="save-msg">✓ Reflection saved for today.</div>', unsafe_allow_html=True)


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
    st.markdown('<div class="login-sub">WHERE PATTERNS EVOLVE INTO AWARENESS</div>', unsafe_allow_html=True)

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

# Logout button
with st.container():
    col_space, col_logout = st.columns([5, 1])
    with col_logout:
        if st.button("Sign out", key="logout"):
            for k in ["logged_in", "user_id", "username", "keywords",
                      "save_success", "dendro_results", "insight_report"]:
                st.session_state.pop(k, None)
            st.cache_data.clear()
            st.rerun()

user_id = st.session_state["user_id"]
rows = load_all_entries(user_id)

tab1, tab2, tab3, tab4 = st.tabs(["📝 Today", "🗺️ Topic Map", "🌿 Dendrogram", "✨ Insights"])

with tab1:
    render_today_tab(rows)

with tab2:
    render_bertopic_tab(rows)

with tab3:
    render_dendrogram_tab(rows)

with tab4:
    render_insights_tab(rows)
