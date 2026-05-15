"""NLP and machine learning utilities for text analysis."""

import streamlit as st
import numpy as np
from config import BIOMETRIC_FIELDS, BIOMETRIC_FEATURE_DIMS


@st.cache_resource(show_spinner="Loading NLP models…")
def load_nlp_models():
    """Load sentence transformer embeddings model."""
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
    """Get embeddings for a list of texts."""
    if not texts:
        return np.zeros((0, 384))
    embedder = load_nlp_models()
    return embedder.encode(texts, show_progress_bar=False)


def build_biometric_features(
    values_per_field: dict[str, list[float | None]],
) -> np.ndarray:
    """Standardise each biometric field across the corpus then tile it."""
    n = len(next(iter(values_per_field.values())))
    blocks = []
    for field in BIOMETRIC_FIELDS:
        vals = values_per_field.get(field) or [None] * n
        present = [v for v in vals if v is not None]
        if not present:
            blocks.append(np.zeros((n, BIOMETRIC_FEATURE_DIMS)))
            continue
        arr = np.array(present, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std()) or 1.0
        filled = np.array([float(v) if v is not None else mean for v in vals])
        z = (filled - mean) / std
        blocks.append(np.tile(z.reshape(-1, 1), (1, BIOMETRIC_FEATURE_DIMS)))
    return np.hstack(blocks)


def biometric_profile_per_phrase(
    phrases: list[str],
    rows: list[dict],
    oura_by_date: dict[str, dict],
) -> dict[str, list[float | None]]:
    """For each phrase, average each biometric across entries it appears in."""
    entries = [
        {
            "content_lc": (r.get("content") or "").lower(),
            "date": r.get("entry_date"),
            "mood": r.get("mood"),
        }
        for r in rows
    ]

    out: dict[str, list[float | None]] = {f: [] for f in BIOMETRIC_FIELDS}
    for phrase in phrases:
        needle = phrase.lower().strip()
        matching = [e for e in entries if needle and needle in e["content_lc"]]

        per_field_vals: dict[str, list[float]] = {f: [] for f in BIOMETRIC_FIELDS}
        for e in matching:
            if e["mood"] is not None:
                per_field_vals["mood"].append(float(e["mood"]))
            oura_row = oura_by_date.get(e["date"]) or {}
            for f in ("sleep_score", "readiness_score", "hrv_avg", "resting_hr"):
                v = oura_row.get(f)
                if v is not None:
                    per_field_vals[f].append(float(v))

        for f in BIOMETRIC_FIELDS:
            vs = per_field_vals[f]
            out[f].append(sum(vs) / len(vs) if vs else None)
    return out


def extract_noun_phrase_clusters(rows: list[dict], top_n: int = 60) -> list[str]:
    """Extract top-N commonly occurring multi-word phrases."""
    from sklearn.feature_extraction.text import CountVectorizer
    
    docs = [r["content"] for r in rows if r.get("content", "").strip()]
    if len(docs) < 4:
        return []
    
    texts = [str(t).strip() for t in docs if t and str(t).strip()]
    if not texts:
        return []
    
    vectorizer = CountVectorizer(
        ngram_range=(2, 4),
        stop_words="english",
        min_df=1,
        max_features=500,
        token_pattern=r"[a-zA-Z]{2,}"
    )
    
    try:
        X = vectorizer.fit_transform(texts)
    except ValueError:
        return []
    
    phrase_counts = X.sum(axis=0).A1
    phrases = vectorizer.get_feature_names_out()
    
    phrase_freq = list(zip(phrases, phrase_counts))
    phrase_freq.sort(key=lambda x: x[1], reverse=True)
    
    filtered_phrases = []
    for phrase, count in phrase_freq[:top_n * 2]:
        is_substring = False
        for existing in filtered_phrases:
            if phrase in existing and phrase != existing:
                is_substring = True
                break
        
        if not is_substring:
            filtered_phrases = [p for p in filtered_phrases if phrase not in p or p == phrase]
            filtered_phrases.append(phrase)
    
    return filtered_phrases[:top_n]


def get_top_similar_phrases(query: str, phrases: list[str], top_n: int = 25) -> list[str]:
    """Return the top_n phrases most semantically similar to the query."""
    from sklearn.metrics.pairwise import cosine_similarity

    if not phrases:
        return []

    all_texts = [query] + phrases
    embeddings = get_embeddings(all_texts)

    query_vec = embeddings[0].reshape(1, -1)
    phrase_vecs = embeddings[1:]

    similarities_matrix = cosine_similarity(query_vec, phrase_vecs)[0]
    similarities = [(phrases[i], float(similarities_matrix[i])) for i in range(len(phrases))]
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    return [p for p, _ in similarities[:top_n]]


@st.cache_data(ttl=300)
def run_topic_map(
    texts: tuple,
    biometrics: tuple | None = None,
    n_clusters: int | None = None,
    k_search_range: tuple[int, int] = (2, 10),
):
    """Cluster reflection texts into topic groups using UMAP + KMeans."""
    from umap import UMAP
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score, silhouette_samples
    from sklearn.feature_extraction.text import TfidfVectorizer

    embedder = load_nlp_models()
    text_list = [t for t in texts if t and t.strip()]
    if len(text_list) < 5:
        raise ValueError(f"Need at least 5 entries, got {len(text_list)}.")

    embeddings = embedder.encode(text_list, show_progress_bar=False)

    if biometrics:
        bio_dict = dict(biometrics)
        kept_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        aligned = {
            field: [list(bio_dict.get(field) or [None] * len(texts))[i] for i in kept_indices]
            for field in BIOMETRIC_FIELDS
        }
        biometric_block = build_biometric_features(aligned)
        embeddings = np.hstack([embeddings, biometric_block])

    n = len(text_list)
    reduced = UMAP(
        n_components=2, n_neighbors=min(5, n - 1),
        min_dist=0.1, random_state=42
    ).fit_transform(embeddings)

    max_possible_k = max(2, n - 1)
    k_search_results: list[tuple[int, float]] = []

    if n_clusters is not None:
        k_used = int(max(2, min(n_clusters, max_possible_k)))
    else:
        lo, hi = k_search_range
        lo = max(2, int(lo))
        hi = min(max_possible_k, int(hi))
        best_k, best_s = lo, -1.0
        for k_try in range(lo, hi + 1):
            try:
                trial_labels = KMeans(
                    n_clusters=k_try, n_init=10, random_state=42
                ).fit_predict(embeddings)
                if len(set(trial_labels)) < 2:
                    continue
                s = float(silhouette_score(embeddings, trial_labels, metric="cosine"))
                k_search_results.append((k_try, s))
                if s > best_s:
                    best_s, best_k = s, k_try
            except Exception:
                continue
        k_used = best_k

    labels = KMeans(
        n_clusters=k_used, n_init=10, random_state=42
    ).fit_predict(embeddings)

    try:
        global_sil = float(silhouette_score(embeddings, labels, metric="cosine"))
        sample_sils = silhouette_samples(embeddings, labels, metric="cosine")
        per_cluster_sil = {
            int(cid): float(sample_sils[labels == cid].mean())
            for cid in sorted(set(labels.tolist()))
        }
    except Exception:
        global_sil = float("nan")
        per_cluster_sil = {}

    per_cluster_cohesion = _cluster_cohesion(embeddings, labels)
    global_cohesion = (
        float(np.mean(list(per_cluster_cohesion.values())))
        if per_cluster_cohesion else float("nan")
    )

    cluster_ids = sorted(set(labels.tolist()))
    cluster_labels = {}
    tfidf = TfidfVectorizer(max_features=500, stop_words="english", ngram_range=(1, 2))
    try:
        tfidf.fit(text_list)
        terms = tfidf.get_feature_names_out()
        tfidf_matrix = tfidf.transform(text_list).toarray()
        for cid in cluster_ids:
            idxs = [i for i, l in enumerate(labels) if l == cid]
            mean_vec = tfidf_matrix[idxs].mean(axis=0)
            top_terms = [terms[i] for i in mean_vec.argsort()[::-1][:3]]
            cluster_labels[int(cid)] = " · ".join(top_terms)
    except Exception:
        for cid in cluster_ids:
            cluster_labels[int(cid)] = f"Cluster {cid}"

    metrics = {
        "silhouette": global_sil,
        "cohesion": global_cohesion,
        "per_cluster_cohesion": per_cluster_cohesion,
        "per_cluster_silhouette": per_cluster_sil,
        "k_used": k_used,
        "k_search_results": k_search_results,
    }

    return reduced, [int(l) for l in labels.tolist()], cluster_labels, text_list, metrics


def _cluster_cohesion(embeddings: np.ndarray, labels: np.ndarray) -> dict[int, float]:
    """Per-cluster cohesion = mean cosine similarity of each point to its centroid."""
    cohesion: dict[int, float] = {}
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / np.where(norms == 0, 1, norms)
    for cid in sorted(set(labels.tolist())):
        idxs = np.where(labels == cid)[0]
        if len(idxs) == 0:
            cohesion[int(cid)] = 0.0
            continue
        centroid = normed[idxs].mean(axis=0)
        c_norm = np.linalg.norm(centroid) or 1.0
        centroid = centroid / c_norm
        sims = normed[idxs] @ centroid
        cohesion[int(cid)] = float(sims.mean())
    return cohesion


@st.cache_data(ttl=300)
def run_dendrogram(
    phrases_tuple: tuple,
    biometrics: tuple | None = None,
    n_clusters: int | None = None,
    k_search_range: tuple[int, int] = (2, 8),
):
    """Run hierarchical clustering on phrases."""
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist
    from sklearn.metrics import silhouette_score, silhouette_samples

    phrases = list(phrases_tuple)
    if len(phrases) < 4:
        return None, None, None, None

    embeddings = get_embeddings(phrases)
    if embeddings.shape[0] == 0:
        return None, None, None, None

    if biometrics:
        bio_dict = dict(biometrics)
        aligned = {f: list(bio_dict.get(f) or [None] * len(phrases)) for f in BIOMETRIC_FIELDS}
        biometric_block = build_biometric_features(aligned)
        embeddings = np.hstack([embeddings, biometric_block])

    norms  = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / np.where(norms == 0, 1, norms)
    dist   = pdist(normed, metric="cosine")
    Z      = linkage(dist, method="ward")

    n = len(phrases)
    max_possible_k = max(2, n - 1)
    k_search_results: list[tuple[int, float]] = []

    if n_clusters is not None:
        k_used = int(max(2, min(n_clusters, max_possible_k)))
    else:
        lo, hi = k_search_range
        lo = max(2, int(lo))
        hi = min(max_possible_k, int(hi))
        best_k, best_s = lo, -1.0
        for k_try in range(lo, hi + 1):
            try:
                trial_labels = fcluster(Z, t=k_try, criterion="maxclust")
                if len(set(trial_labels.tolist())) < 2:
                    continue
                s = float(silhouette_score(embeddings, trial_labels, metric="cosine"))
                k_search_results.append((k_try, s))
                if s > best_s:
                    best_s, best_k = s, k_try
            except Exception:
                continue
        k_used = best_k

    cluster_ids = fcluster(Z, t=k_used, criterion="maxclust")

    try:
        global_sil = float(silhouette_score(embeddings, cluster_ids, metric="cosine"))
        sample_sils = silhouette_samples(embeddings, cluster_ids, metric="cosine")
        per_cluster_sil = {
            int(cid): float(sample_sils[cluster_ids == cid].mean())
            for cid in sorted(set(cluster_ids.tolist()))
        }
    except Exception:
        global_sil = float("nan")
        per_cluster_sil = {}

    per_cluster_cohesion: dict[int, float] = {}
    for cid in sorted(set(cluster_ids.tolist())):
        idxs = np.where(cluster_ids == cid)[0]
        if len(idxs) == 0:
            per_cluster_cohesion[int(cid)] = 0.0
            continue
        centroid = normed[idxs].mean(axis=0)
        c_norm = np.linalg.norm(centroid) or 1.0
        centroid = centroid / c_norm
        sims = normed[idxs] @ centroid
        per_cluster_cohesion[int(cid)] = float(sims.mean())
    global_cohesion = (
        float(np.mean(list(per_cluster_cohesion.values())))
        if per_cluster_cohesion else float("nan")
    )

    metrics = {
        "silhouette": global_sil,
        "cohesion": global_cohesion,
        "per_cluster_silhouette": per_cluster_sil,
        "per_cluster_cohesion": per_cluster_cohesion,
        "k_used": int(k_used),
        "k_search_results": k_search_results,
    }

    return phrases, Z, cluster_ids, metrics
