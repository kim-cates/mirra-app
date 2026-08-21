import streamlit as st
import anthropic
import base64
from supabase import create_client
from datetime import date, datetime, timedelta
import json
import numpy as np
import plotly.graph_objects as go

import oura
import oura_ui
import connections_ui  # MIR-3: provider framework (Spotify, Whoop, …)
from oura import user_today
from auth import render_login_page, render_logout_button
from intro_page import render_intro_page, user_has_seen_intro
from insight_inquiry import render_insight_inquiry, user_has_completed_inquiry
from onboarding import should_run_onboarding
from profile_form import render_profile_form, user_has_completed_profile
from profile_tab import render_profile_tab


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mirra", page_icon="logo.png", layout="centered")

# Mobile viewport — Streamlit doesn't always inject one, and without this
# phones render at desktop-width and zoom out, making everything tiny.
app_icon_base64 = None
try:
    with open("logo.png", "rb") as f:
        app_icon_base64 = base64.b64encode(f.read()).decode()
except FileNotFoundError:
    app_icon_base64 = None

icon_links = ''
if app_icon_base64:
    icon_links = f'''
    <link rel="icon" type="image/png" href="data:image/png;base64,{app_icon_base64}">
    <link rel="shortcut icon" href="data:image/png;base64,{app_icon_base64}">
    <link rel="apple-touch-icon" href="data:image/png;base64,{app_icon_base64}">
    <meta name="theme-color" content="#faf9f5">
    '''

st.markdown(
    '<meta name="viewport" content="width=device-width, initial-scale=1.0, '
    'maximum-scale=5.0">' + icon_links,
    unsafe_allow_html=True,
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

/* Force the cream background onto Streamlit's actual outermost containers.
   Targeting just html/body wasn't enough — Streamlit applies its own theme
   colors to .stApp and related wrappers, and on phones in dark mode those
   wrappers would override our cream and bleed black through to the user.
   Setting all of them explicitly + the !important flag wins against the
   built-in dark theme. The config.toml at .streamlit/config.toml also
   forces light theme on Streamlit Cloud, this is the belt-and-suspenders. */
html, body, .stApp, [data-testid="stAppViewContainer"], .main, .block-container {
    background-color: #faf9f5 !important;
    color: #2a2a2a !important;
    font-family: 'DM Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.6rem 2rem 4rem 2rem; max-width: 1180px; }

/* Tab styling — slimmer, lower-contrast, more typographic */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px; background: transparent; border-bottom: 1px solid #ece9df;
    border-radius: 0; padding: 0 0 0 4px; margin-bottom: 1rem;
    /* Allow horizontal scrolling on mobile so 6 tabs don't crush together. */
    overflow-x: auto; flex-wrap: nowrap;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { height: 0; }
.stTabs [data-baseweb="tab"] {
    border-radius: 0; padding: 10px 18px; font-size: 0.86rem;
    font-weight: 500; color: #999; background: transparent; border: none;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
    transition: color 0.15s ease, border-color 0.15s ease;
    white-space: nowrap;  /* don't wrap tab labels onto two lines */
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
    white-space: nowrap;
}
.section-label {
    font-size: 0.72rem; font-weight: 600; color: #888;
    letter-spacing: 0.14em; text-transform: uppercase;
    margin-bottom: 0.7rem; margin-top: 1.8rem;
}

/* Inputs — !important to beat dark-theme defaults */
textarea, input[type="text"], input[type="password"], .stTextInput input, .stTextArea textarea {
    background-color: #ffffff !important; border: 1px solid #ece9df !important;
    border-radius: 10px !important; font-family: 'DM Sans', sans-serif !important;
    font-size: 0.98rem !important; color: #2a2a2a !important;
    transition: border-color 0.15s ease !important;
}
textarea:focus, input:focus { border-color: #3dab7a !important; box-shadow: 0 0 0 3px rgba(61,171,122,0.08) !important; }

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
.kw-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 4px; }
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
.login-logo img { max-width: 100%; height: auto; }
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

/* ── Native Streamlit widgets ──────────────────────────────────────────────
   Everything above styles our own markup. These rules cover the widgets
   Streamlit renders itself — buttons, multiselect, slider read-outs, the tab
   underline — which until now took whatever theme Streamlit resolved at
   runtime. When that resolved to the default (or to dark, on a dark-mode
   machine) they came out near-black with a red accent on our cream page,
   while the `color: #2a2a2a` rule at the top kept their labels dark: black
   button with black text, unreadable feelings picker. Pinning them to the
   palette here means the UI stays legible even if the theme file goes
   missing again. Colors mirror .streamlit/config.toml. */

/* Buttons — secondary (the default) is a quiet white pill; primary is sage. */
.stButton > button,
.stFormSubmitButton > button,
[data-testid="stBaseButton-secondary"] {
    background-color: #ffffff !important; color: #2a2a2a !important;
    border: 1px solid #ece9df !important; border-radius: 10px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.92rem !important; font-weight: 500 !important;
    padding: 0.45rem 1.1rem !important; box-shadow: none !important;
    transition: border-color 0.15s ease, color 0.15s ease, background-color 0.15s ease !important;
}
.stButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid="stBaseButton-secondary"]:hover {
    background-color: #f7fbf9 !important; border-color: #3dab7a !important; color: #2a8a5e !important;
}
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"],
[data-testid="stBaseButton-primary"] {
    background-color: #3dab7a !important; color: #ffffff !important;
    border: 1px solid #3dab7a !important;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover {
    background-color: #349168 !important; border-color: #349168 !important; color: #ffffff !important;
}
.stButton > button:focus-visible,
.stFormSubmitButton > button:focus-visible {
    outline: none !important; box-shadow: 0 0 0 3px rgba(61,171,122,0.18) !important;
}
.stButton > button:disabled, .stButton > button:disabled:hover {
    background-color: #f5f4ee !important; color: #b5b1a6 !important;
    border-color: #ece9df !important; cursor: not-allowed !important;
}

/* Multiselect / selectbox — white field, sage-tinted tags matching .kw-chip.
   Streamlit 1.61 rewrote these widgets from baseweb to react-aria, so the
   old `[data-baseweb="select"]` / `[data-baseweb="tag"]` hooks match nothing
   here; the live markup is `.react-aria-ComboBox` with `span[data-tag]`.
   The emotion class names next to them (st-emotion-cache-*) are generated
   per build and must never be selected on. */
[data-testid="stMultiSelect"] div[role="group"],
[data-testid="stSelectbox"] div[role="group"] {
    background-color: #ffffff !important; color: #2a2a2a !important;
    border: 1px solid #ece9df !important; border-radius: 10px !important;
    box-shadow: none !important;
}
[data-testid="stMultiSelect"] div[role="group"]:focus-within,
[data-testid="stSelectbox"] div[role="group"]:focus-within {
    border-color: #3dab7a !important; box-shadow: 0 0 0 3px rgba(61,171,122,0.08) !important;
}
/* The combobox's own input sits inside that field — the generic `input`
   rule at the top of this stylesheet would otherwise paint a second white
   bordered box inside the field. */
[data-testid="stMultiSelect"] input, [data-testid="stSelectbox"] input {
    background-color: transparent !important; border: none !important;
    border-radius: 0 !important; box-shadow: none !important;
}
[data-testid="stMultiSelectTagsContainer"] span[data-tag] {
    background-color: #e8f5f0 !important; color: #2a7a55 !important;
    border: 1px solid #c9e4d6 !important; border-radius: 999px !important;
    font-size: 0.82rem !important; font-weight: 500 !important;
}
[data-testid="stMultiSelectTagsContainer"] span[data-tag] span,
[data-testid="stMultiSelectTagsContainer"] span[data-tag] button,
[data-testid="stMultiSelectTagsContainer"] span[data-tag] svg {
    color: #2a7a55 !important; fill: #2a7a55 !important; background: transparent !important;
}
/* Dropdown panel — rendered in a portal outside .stApp, so it needs its own
   background or it inherits the browser default (white-on-white text). */
.react-aria-Popover, [data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"] {
    background-color: #ffffff !important; color: #2a2a2a !important;
    border: 1px solid #ece9df !important; border-radius: 10px !important;
}
[role="option"]:hover, [role="option"][aria-selected="true"],
[data-baseweb="menu"] li:hover, [data-baseweb="menu"] li[aria-selected="true"] {
    background-color: #f0f8f4 !important; color: #1e6b45 !important;
}
::placeholder { color: #a9a49a !important; opacity: 1 !important; }

/* Checkbox / radio labels — the box itself comes from the theme's primary. */
[data-testid="stCheckbox"] label, [data-testid="stRadio"] label {
    color: #2a2a2a !important; font-size: 0.9rem !important;
}

/* Slider read-outs — the floating thumb value ships as a filled accent badge,
   i.e. sage text on a sage chip directly above the sage track: unreadable.
   Streamlit's emotion styles are injected after this stylesheet, so an equal
   specificity selector loses even with !important — hence the extra
   [data-testid="stSlider"] ancestor. Don't extend this to the badge's parent:
   that element is the draggable thumb itself, and clearing its background
   makes the knob disappear from the track. */
[data-testid="stSlider"] [data-testid="stSliderThumbValue"] {
    background: transparent !important; color: #2a8a5e !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.8rem !important; font-weight: 600 !important;
}
[data-testid="stSlider"] [data-testid="stSliderTickBar"] {
    background: transparent !important; color: #b5b1a6 !important; font-size: 0.75rem !important;
}

/* Tabs: the moving underline is a separate element from the tab's own
   border-bottom, so it kept the default red even with the rule above. */
.stTabs [data-baseweb="tab-highlight"] { background-color: #3dab7a !important; }
.stTabs [data-baseweb="tab-border"] { background-color: #ece9df !important; }

/* ── Mobile breakpoints ────────────────────────────────────────────────────
   Streamlit's st.columns doesn't auto-stack on mobile, but our custom HTML
   grids (.stat-grid, the Oura badge row in oura_ui.py, the weekly insights
   cards) need explicit media queries to wrap. Without these they crush down
   into unreadable thin columns on phones.

   Two breakpoints:
   - <=768px (tablet / large phone landscape): 4-col grids drop to 2-col
   - <=480px (phone portrait): all grids stack to a single column;
     reduce body padding so content reaches closer to the screen edges
*/
@media (max-width: 768px) {
    .block-container { padding: 1rem 1rem 3rem 1rem; }
    .stat-grid { grid-template-columns: 1fr 1fr !important; gap: 8px; }
    .title-text { font-size: 1.5rem; }
    .insight-card { padding: 1rem 1.1rem; }
    /* Force any 4-column inline grid (the Oura badge row uses inline style
       grid-template-columns: repeat(4, 1fr); we can't add a class to it
       without editing each occurrence, so this universal selector catches
       any inline-styled 4-col grids and downgrades them to 2-col.) */
    div[style*="grid-template-columns:repeat(4,1fr)"],
    div[style*="grid-template-columns: repeat(4,1fr)"],
    div[style*="grid-template-columns: repeat(4, 1fr)"] {
        grid-template-columns: 1fr 1fr !important;
    }
}
@media (max-width: 480px) {
    .block-container { padding: 0.8rem 0.8rem 3rem 0.8rem; }
    .stat-grid { grid-template-columns: 1fr !important; }
    .title-text { font-size: 1.35rem; }
    .stTabs [data-baseweb="tab"] { padding: 8px 12px; font-size: 0.8rem; }
    /* On phones, even the 2-col fallback for the badge row gets cramped —
       stack everything single-file. */
    div[style*="grid-template-columns:repeat(4,1fr)"],
    div[style*="grid-template-columns: repeat(4,1fr)"],
    div[style*="grid-template-columns: repeat(4, 1fr)"],
    div[style*="grid-template-columns:repeat(2,1fr)"],
    div[style*="grid-template-columns: repeat(2,1fr)"],
    div[style*="grid-template-columns: repeat(2, 1fr)"] {
        grid-template-columns: 1fr !important;
    }
    .insight-card { padding: 0.9rem 1rem; font-size: 0.92rem; }
    .section-label { margin-top: 1.4rem; }
}
</style>
""", unsafe_allow_html=True)


# ── Clients ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase():
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
        client = create_client(url, key)
        # quick connectivity check (non-destructive)
        try:
            client.table("users").select("id").limit(1).execute()
        except Exception:
            import logging
            logging.exception("Supabase connectivity check failed")
            # Surface a concise message in the Streamlit UI and re-raise
            st.error("Unable to reach Supabase. Check `SUPABASE_URL`, `SUPABASE_KEY`, and network egress.")
            raise
        return client
    except Exception:
        import logging
        logging.exception("Supabase client initialization failed")
        st.error("Supabase initialization failed — see logs for details.")
        raise

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


# Biometric fields fed into clustering alongside text. Each contributes
# `_BIOMETRIC_FEATURE_DIMS` columns to the augmented embedding (the value is
# tiled so the bundle has comparable weight to ~50 text-embedding dims),
# and is z-scored across the corpus first so different scales (mood 1-10
# vs HRV 20-90 vs RHR 45-80, etc.) don't make one feature dominate.
_BIOMETRIC_FIELDS = ("mood", "sleep_score", "readiness_score", "hrv_avg", "resting_hr")
_BIOMETRIC_FEATURE_DIMS = 10


def build_biometric_features(
    values_per_field: dict[str, list[float | None]],
) -> np.ndarray:
    """Standardise each field across the corpus then tile it.

    Args:
        values_per_field: maps field name -> list of values aligned with the
            rows being clustered (one value per row, None where missing).

    Returns:
        Array of shape (n_rows, len(fields) * _BIOMETRIC_FEATURE_DIMS).
        Missing values are imputed with the field mean so the feature space
        stays well-defined. If a field has no data at all, its block is zeros.
    """
    n = len(next(iter(values_per_field.values())))
    blocks = []
    for field in _BIOMETRIC_FIELDS:
        vals = values_per_field.get(field) or [None] * n
        present = [v for v in vals if v is not None]
        if not present:
            # No data for this field — contribute a zero block so the column
            # count stays consistent across runs.
            blocks.append(np.zeros((n, _BIOMETRIC_FEATURE_DIMS)))
            continue
        arr = np.array(present, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std()) or 1.0
        # Impute missing with the mean, then z-score everything.
        filled = np.array([float(v) if v is not None else mean for v in vals])
        z = (filled - mean) / std
        blocks.append(np.tile(z.reshape(-1, 1), (1, _BIOMETRIC_FEATURE_DIMS)))
    return np.hstack(blocks)


def biometric_profile_per_phrase(
    phrases: list[str],
    rows: list[dict],
    oura_by_date: dict[str, dict],
) -> dict[str, list[float | None]]:
    """For each phrase, average each biometric across the entries it appears in.

    A phrase doesn't have a single date — it can recur across many days. To
    cluster phrases by physiological context, we compute the mean of each
    biometric over the days where the phrase appears in the reflection
    content (case-insensitive substring match). Phrases that don't appear in
    any entry (e.g. ones synthesised from a similarity query) get None for
    every field; those rows will be mean-imputed by build_biometric_features.

    Returns a dict in the same shape build_biometric_features expects.
    """
    # Lower-case content lookup for case-insensitive matching.
    entries = [
        {
            "content_lc": (r.get("content") or "").lower(),
            "date": r.get("entry_date"),
            "mood": r.get("mood"),
        }
        for r in rows
    ]

    out: dict[str, list[float | None]] = {f: [] for f in _BIOMETRIC_FIELDS}
    for phrase in phrases:
        needle = phrase.lower().strip()
        matching = [e for e in entries if needle and needle in e["content_lc"]]

        # Gather available values per field across matching entries.
        per_field_vals: dict[str, list[float]] = {f: [] for f in _BIOMETRIC_FIELDS}
        for e in matching:
            if e["mood"] is not None:
                per_field_vals["mood"].append(float(e["mood"]))
            oura_row = oura_by_date.get(e["date"]) or {}
            for f in ("sleep_score", "readiness_score", "hrv_avg", "resting_hr"):
                v = oura_row.get(f)
                if v is not None:
                    per_field_vals[f].append(float(v))

        for f in _BIOMETRIC_FIELDS:
            vs = per_field_vals[f]
            out[f].append(sum(vs) / len(vs) if vs else None)
    return out


def cluster_characteristics_from_phrases(
    cluster_to_phrases: dict[int, list[str]],
    rows: list[dict],
    oura_by_date: dict[str, dict],
) -> dict[int, dict]:
    """For each phrase-dendrogram cluster, gather the moods, feelings, and
    biometrics from every reflection where any of the cluster's phrases
    appear.

    Phrase clusters are different from entry clusters: one phrase can show
    up in many reflections, and one reflection can contribute to multiple
    phrase clusters. We resolve this by collecting the UNION of entries
    where any cluster phrase appears (case-insensitive substring match),
    then averaging mood + biometrics over that union and counting feelings
    across it.

    Returns a dict {cluster_id: {
        "n_entries": int,            # distinct reflections touched
        "n_phrases": int,            # phrase count in the cluster
        "mood_avg":      float|None,
        "mood_std":      float|None,
        "sleep_avg":     float|None,
        "readiness_avg": float|None,
        "hrv_avg":       float|None,
        "rhr_avg":       float|None,
        "top_feelings":  list[(name, count)],   # top 4 by frequency
        "top_keywords":  list[str],             # from the entries' keyword fields
    }}.
    """
    # Pre-lower entries for case-insensitive matching.
    entries = [
        {
            "content_lc": (r.get("content") or "").lower(),
            "date": r.get("entry_date"),
            "mood": r.get("mood"),
            "feelings": r.get("feelings") or [],
            "keywords": r.get("keywords") or [],
        }
        for r in rows
    ]

    out: dict[int, dict] = {}
    for cid, phrases in cluster_to_phrases.items():
        needles = [p.lower().strip() for p in phrases if p and p.strip()]
        if not needles:
            out[int(cid)] = {
                "n_entries": 0, "n_phrases": len(phrases),
                "mood_avg": None, "mood_std": None,
                "sleep_avg": None, "readiness_avg": None,
                "hrv_avg": None, "rhr_avg": None,
                "top_feelings": [], "top_keywords": [],
            }
            continue

        # Match an entry if ANY of the cluster's phrases appears in it.
        # We dedupe by date so the same reflection doesn't get double-counted.
        matched_dates: set[str] = set()
        matched_entries: list[dict] = []
        for e in entries:
            if e["date"] in matched_dates:
                continue
            if any(needle in e["content_lc"] for needle in needles):
                matched_dates.add(e["date"])
                matched_entries.append(e)

        # Aggregate mood.
        moods = [float(e["mood"]) for e in matched_entries if e.get("mood") is not None]
        mood_avg = float(np.mean(moods)) if moods else None
        mood_std = float(np.std(moods)) if len(moods) > 1 else None

        # Aggregate biometrics from oura_by_date keyed by entry date.
        bio_lists: dict[str, list[float]] = {
            "sleep_score": [], "readiness_score": [], "hrv_avg": [], "resting_hr": [],
        }
        for e in matched_entries:
            oura_row = oura_by_date.get(e["date"]) or {}
            for field in bio_lists:
                v = oura_row.get(field)
                if v is not None:
                    bio_lists[field].append(float(v))

        def _avg(vals: list[float]) -> float | None:
            return float(np.mean(vals)) if vals else None

        # Aggregate feelings across the matched entries.
        feeling_counts: dict[str, int] = {}
        for e in matched_entries:
            for f in e["feelings"]:
                name = (f.get("name") or "").lower().strip()
                if name:
                    feeling_counts[name] = feeling_counts.get(name, 0) + 1
        top_feelings = sorted(feeling_counts.items(), key=lambda kv: -kv[1])[:4]

        # Aggregate keyword frequency across the matched entries.
        kw_counts: dict[str, int] = {}
        for e in matched_entries:
            for k in e["keywords"]:
                kl = (k or "").lower().strip()
                if kl:
                    kw_counts[kl] = kw_counts.get(kl, 0) + 1
        top_keywords = [k for k, _ in sorted(kw_counts.items(), key=lambda kv: -kv[1])[:5]]

        out[int(cid)] = {
            "n_entries": len(matched_entries),
            "n_phrases": len(phrases),
            "mood_avg": mood_avg,
            "mood_std": mood_std,
            "sleep_avg":     _avg(bio_lists["sleep_score"]),
            "readiness_avg": _avg(bio_lists["readiness_score"]),
            "hrv_avg":       _avg(bio_lists["hrv_avg"]),
            "rhr_avg":       _avg(bio_lists["resting_hr"]),
            "top_feelings":  top_feelings,
            "top_keywords":  top_keywords,
        }
    return out


def describe_cluster_in_words(profile: dict) -> str:
    """Turn a cluster profile dict into a short one-sentence description.

    The description weaves mood, dominant feelings, and the most notable
    biometric signal into prose, so the user gets the gestalt without
    having to read the metrics row. We deliberately keep it short and
    descriptive rather than interpretive (no "this means you're stressed"
    — just "low mood, anxious-leaning, with reduced HRV").
    """
    if profile["n_entries"] == 0:
        return "No matching reflections found for these phrases."

    bits: list[str] = []

    # Mood band
    mood = profile["mood_avg"]
    if mood is not None:
        if mood >= 7.5:
            bits.append(f"high mood ({mood:.1f}/10)")
        elif mood >= 5.5:
            bits.append(f"moderate mood ({mood:.1f}/10)")
        elif mood >= 3.5:
            bits.append(f"low-moderate mood ({mood:.1f}/10)")
        else:
            bits.append(f"low mood ({mood:.1f}/10)")

    # Dominant feelings — just the names, comma-separated, max 2
    if profile["top_feelings"]:
        feels = ", ".join(name for name, _ in profile["top_feelings"][:2])
        bits.append(f"{feels}-leaning")

    # Biometric tone: pick the most notable signal. We don't have z-scores
    # vs corpus baseline here so we use rough population thresholds for
    # Oura's typical adult ranges as a soft signal.
    biometric_bits = []
    if profile["sleep_avg"] is not None:
        if profile["sleep_avg"] >= 80:
            biometric_bits.append("good sleep")
        elif profile["sleep_avg"] < 65:
            biometric_bits.append("poor sleep")
    if profile["hrv_avg"] is not None:
        if profile["hrv_avg"] >= 50:
            biometric_bits.append("strong HRV recovery")
        elif profile["hrv_avg"] < 30:
            biometric_bits.append("suppressed HRV")
    if profile["rhr_avg"] is not None:
        if profile["rhr_avg"] >= 70:
            biometric_bits.append("elevated resting HR")
        elif profile["rhr_avg"] < 55:
            biometric_bits.append("low resting HR")
    if biometric_bits:
        bits.append("with " + " and ".join(biometric_bits[:2]))

    return ", ".join(bits).capitalize() + "."


# ── Thematic insights from dendrogram retrieval ──────────────────────────────
# Given the phrases the dendrogram returned for a query, plus the user's full
# corpus, surface insight cuts that answer "within this theme, what's
# different about good days vs bad days?" These take the dendrogram's job
# from "show me the structure of these phrases" to "tell me what those
# phrases reveal about my life."

def _entries_matching_phrases(
    phrases: list[str],
    rows: list[dict],
) -> list[dict]:
    """Return the unique reflections (deduped by date) where ANY of the
    given phrases appears as a case-insensitive substring of the content.
    Each returned dict carries its row plus a lowercased content for downstream
    matching — done once here to avoid repeated .lower() calls in hot loops."""
    needles = [p.lower().strip() for p in phrases if p and p.strip()]
    if not needles:
        return []
    seen: set = set()
    out: list[dict] = []
    for r in rows:
        d = r.get("entry_date")
        if d in seen:
            continue
        content_lc = (r.get("content") or "").lower()
        if any(n in content_lc for n in needles):
            seen.add(d)
            row_copy = dict(r)
            row_copy["_content_lc"] = content_lc
            out.append(row_copy)
    return out


def _discriminating_phrases(
    high_entries: list[dict],
    low_entries: list[dict],
    candidate_phrases: list[str],
    min_appearances: int = 2,
) -> list[tuple[str, int, int, float]]:
    """For each candidate phrase, compute how much more often it appears in
    `high_entries` vs `low_entries`, normalized by group size so the result
    isn't biased toward whichever group is bigger.

    Returns a list of (phrase, high_count, low_count, score) sorted by score
    descending. `score` is the rate difference (high/n_high - low/n_low),
    bounded in [-1, 1]. We filter phrases appearing fewer than
    `min_appearances` times total across both groups to drop one-off noise.
    """
    if not high_entries and not low_entries:
        return []
    n_high = max(1, len(high_entries))
    n_low = max(1, len(low_entries))

    out: list[tuple[str, int, int, float]] = []
    for phrase in candidate_phrases:
        needle = phrase.lower().strip()
        if not needle:
            continue
        hi = sum(1 for e in high_entries if needle in e["_content_lc"])
        lo = sum(1 for e in low_entries if needle in e["_content_lc"])
        if hi + lo < min_appearances:
            continue
        # Rate difference: how much more concentrated in the high group.
        # Positive = associated with the high group, negative = low group.
        score = (hi / n_high) - (lo / n_low)
        out.append((phrase, hi, lo, score))
    return sorted(out, key=lambda t: t[3], reverse=True)


def _build_corpus_phrase_pool(
    rows: list[dict],
    theme_entries: list[dict],
    seed_phrases: list[str],
    top_n: int = 80,
) -> list[str]:
    """Build the candidate phrase pool for discriminating cuts.

    The dendrogram's 25 phrases are semantically similar to the QUERY ("night
    shifts and lack of sleep"). They won't include phrases like "yoga class"
    that might be what *differentiates* good days from bad days in that
    theme. So we widen the pool: extract 3-word noun phrases from the theme
    entries (and from the broader corpus, lightly), and merge with the seed.

    `seed_phrases` are the dendrogram's retrieved phrases — always included.
    """
    from sklearn.feature_extraction.text import CountVectorizer

    pool: set[str] = {p.lower().strip() for p in seed_phrases if p and p.strip()}

    # Theme-entry phrases: things you tend to write about ON theme days.
    # These are the most likely to differentiate good vs bad theme days.
    theme_texts = [e.get("content") or "" for e in theme_entries if e.get("content")]
    if len(theme_texts) >= 2:
        try:
            vec = CountVectorizer(
                ngram_range=(2, 3),
                stop_words="english",
                max_features=top_n,
                min_df=1,
                token_pattern=r"[a-zA-Z]{3,}",
            )
            vec.fit(theme_texts)
            for p in vec.get_feature_names_out():
                pool.add(p.lower().strip())
        except Exception:
            pass

    return sorted(pool)


def compute_thematic_insights(
    seed_phrases: list[str],
    cluster_to_phrases: dict[int, list[str]],
    rows: list[dict],
    oura_by_date: dict[str, dict],
) -> dict:
    """Compute the four insight cuts for the dendrogram's theme view.

    Args:
        seed_phrases: the phrases returned by the dendrogram retrieval (these
            define the theme).
        cluster_to_phrases: {cluster_id: [phrases]} from the dendrogram.
        rows: all reflections.
        oura_by_date: {date_iso: {sleep_score, readiness_score, hrv_avg, resting_hr}}

    Returns a dict with:
        - theme_entries: list of entries in the theme corpus (for n display)
        - mood_split: { mood_high, mood_low, n_high, n_low,
                        top_high_phrases, top_low_phrases }
        - biometric_splits: { field: { high_phrases, low_phrases, ... } }
        - cooccurrence: list of (phrase_a, phrase_b, count) top pairs
        - cluster_mood_ranking: list of (cluster_id, n_entries, mood_avg)
          sorted high → low

        If theme entries are too few for a cut, that section's payload is
        marked with skip=True and a brief reason. Skip messages bubble up
        to the UI so the user knows WHY a cut is missing.
    """
    theme_entries = _entries_matching_phrases(seed_phrases, rows)

    out: dict = {
        "theme_entries": theme_entries,
        "n_theme": len(theme_entries),
        "mood_split": None,
        "biometric_splits": {},
        "cooccurrence": [],
        "cluster_mood_ranking": [],
    }

    # ── 1. Mood split: high-mood vs low-mood theme entries ──────────────────
    # Need at least 4 entries with mood values to do a meaningful split
    # (median of 4 still gives 2 per side). Below that the contrast is noise.
    moods_with_rows = [(e, e["mood"]) for e in theme_entries if e.get("mood") is not None]
    if len(moods_with_rows) >= 4:
        mood_median = float(np.median([m for _, m in moods_with_rows]))
        high = [e for e, m in moods_with_rows if m >= mood_median]
        low = [e for e, m in moods_with_rows if m < mood_median]
        # Re-balance: if all entries have the same mood, median sends them
        # all to one side. Bail in that degenerate case.
        if high and low:
            phrase_pool = _build_corpus_phrase_pool(rows, theme_entries, seed_phrases)
            discr = _discriminating_phrases(high, low, phrase_pool, min_appearances=2)
            # Top 5 in each direction, with the rate diff floor of 0.10 to
            # filter out near-tied phrases that aren't really differentiating.
            top_high = [t for t in discr if t[3] >= 0.10][:5]
            top_low = [t for t in reversed(discr) if t[3] <= -0.10][:5]
            out["mood_split"] = {
                "median": mood_median,
                "mood_high_avg": float(np.mean([m for _, m in moods_with_rows if m >= mood_median])),
                "mood_low_avg":  float(np.mean([m for _, m in moods_with_rows if m < mood_median])),
                "n_high": len(high),
                "n_low": len(low),
                "top_high_phrases": top_high,
                "top_low_phrases": top_low,
            }
        else:
            out["mood_split"] = {"skip": True, "reason": "All theme entries have the same mood — no contrast to surface."}
    else:
        out["mood_split"] = {"skip": True, "reason": f"Only {len(moods_with_rows)} theme entries with mood values — need at least 4 for a split."}

    # ── 2. Biometric splits: same logic for each Oura metric ──────────────────
    bio_fields = [
        ("sleep_score",     "sleep score",  "higher = better"),
        ("readiness_score", "readiness",    "higher = better"),
        ("hrv_avg",         "HRV",          "higher = better recovery"),
        ("resting_hr",      "resting HR",   "lower = better"),
    ]
    phrase_pool_cached: list[str] | None = None  # build once, reuse across fields
    for field, label, direction in bio_fields:
        # Pair each theme entry with its biometric value.
        paired = [
            (e, (oura_by_date.get(e.get("entry_date")) or {}).get(field))
            for e in theme_entries
        ]
        paired = [(e, v) for e, v in paired if v is not None]
        if len(paired) < 4:
            out["biometric_splits"][field] = {
                "skip": True, "label": label, "direction": direction,
                "reason": f"Only {len(paired)} theme entries with {label} — need at least 4.",
            }
            continue
        med = float(np.median([v for _, v in paired]))
        hi_rows = [e for e, v in paired if v >= med]
        lo_rows = [e for e, v in paired if v < med]
        if not hi_rows or not lo_rows:
            out["biometric_splits"][field] = {
                "skip": True, "label": label, "direction": direction,
                "reason": f"No variation in {label} across theme entries.",
            }
            continue
        if phrase_pool_cached is None:
            phrase_pool_cached = _build_corpus_phrase_pool(rows, theme_entries, seed_phrases)
        discr = _discriminating_phrases(hi_rows, lo_rows, phrase_pool_cached, min_appearances=2)
        top_hi = [t for t in discr if t[3] >= 0.10][:4]
        top_lo = [t for t in reversed(discr) if t[3] <= -0.10][:4]
        out["biometric_splits"][field] = {
            "skip": False, "label": label, "direction": direction,
            "median": med,
            "hi_avg": float(np.mean([v for _, v in paired if v >= med])),
            "lo_avg": float(np.mean([v for _, v in paired if v < med])),
            "n_hi": len(hi_rows), "n_lo": len(lo_rows),
            "top_hi_phrases": top_hi,
            "top_lo_phrases": top_lo,
        }

    # ── 3. Co-occurrence: which seed phrases appear together in the same entry ──
    # We restrict co-occurrence to seed phrases (the dendrogram's retrieval).
    # Widening to the full pool would surface generic pairs like
    # ("the work", "and then") that don't add insight.
    pair_counts: dict[tuple[str, str], int] = {}
    seeds_lc = [p.lower().strip() for p in seed_phrases if p and p.strip()]
    for entry in theme_entries:
        present = [p for p in seeds_lc if p in entry["_content_lc"]]
        # All unordered pairs of phrases present in this entry.
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = sorted([present[i], present[j]])
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
    out["cooccurrence"] = sorted(
        [(a, b, c) for (a, b), c in pair_counts.items() if c >= 2],
        key=lambda t: -t[2],
    )[:6]

    # ── 4. Cluster-level mood ranking ────────────────────────────────────────
    # For each dendrogram cluster, average mood across reflections containing
    # any phrase from that cluster. Surfaces "cluster 2 is your good-mood
    # theme; cluster 5 is your stressed-out theme" at a glance.
    cluster_ranking: list[tuple[int, int, float]] = []
    for cid, phs in cluster_to_phrases.items():
        cluster_entries = _entries_matching_phrases(phs, rows)
        cluster_moods = [e["mood"] for e in cluster_entries if e.get("mood") is not None]
        if not cluster_moods:
            continue
        cluster_ranking.append((int(cid), len(cluster_entries), float(np.mean(cluster_moods))))
    out["cluster_mood_ranking"] = sorted(cluster_ranking, key=lambda t: -t[2])

    return out


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


# ── Topic Map: UMAP + KMeans with silhouette-optimised k ─────────────────────
def _cluster_cohesion(embeddings: np.ndarray, labels: np.ndarray) -> dict[int, float]:
    """Per-cluster cohesion = mean cosine similarity of each point to its
    cluster centroid. Range [-1, 1], higher = tighter cluster."""
    cohesion: dict[int, float] = {}
    # Normalize once so dot product == cosine similarity.
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
def run_topic_map(
    texts: tuple,
    biometrics: tuple | None = None,
    n_clusters: int | None = None,
    k_search_range: tuple[int, int] = (2, 10),
):
    """Cluster reflection texts into topic groups.

    Args:
        texts: tuple of reflection content strings.
        biometrics: optional tuple of (field_name, values_tuple) pairs, one
            tuple per text in the same order. Fields should be from
            `_BIOMETRIC_FIELDS` (mood, sleep_score, readiness_score, hrv_avg,
            resting_hr). Tuple-of-tuples form is used (rather than a dict) so
            the function args stay hashable for st.cache_data. When provided,
            these are z-scored and concatenated onto the text embeddings
            before clustering so groups reflect physiological similarity in
            addition to semantic content.
        n_clusters: if provided, use KMeans with this exact cluster count.
            If None, sweep `k_search_range` and pick the k with the highest
            silhouette score.
        k_search_range: (min_k, max_k) inclusive, used only when n_clusters
            is None. max_k is automatically capped at n_samples - 1.

    Returns:
        reduced: (n, 2) UMAP coords for plotting.
        labels: list of cluster ids per text (no noise label; every point
            belongs to a cluster).
        cluster_labels: {cid: "term1 · term2 · term3"} TF-IDF top terms.
        text_list: filtered list of non-blank texts (aligned with labels).
        metrics: dict with keys:
            - "silhouette": global silhouette score (float, [-1, 1])
            - "cohesion": global mean intra-cluster cosine cohesion (float)
            - "per_cluster_cohesion": {cid: float}
            - "per_cluster_silhouette": {cid: float}
            - "k_used": int, the cluster count actually used
            - "k_search_results": list of (k, silhouette) tuples if a sweep
              was run (else empty list).
    """
    from umap import UMAP
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score, silhouette_samples
    from sklearn.feature_extraction.text import TfidfVectorizer

    embedder = load_nlp_models()
    text_list = [t for t in texts if t and t.strip()]
    if len(text_list) < 5:
        raise ValueError(f"Need at least 5 entries, got {len(text_list)}.")

    embeddings = embedder.encode(text_list, show_progress_bar=False)

    # Augment with standardized biometric features. We keep the same
    # filtering rule (drop blank texts) above, so the biometric values must
    # be aligned by index AFTER that filter — callers pass values already
    # aligned with `texts`, so we slice to match the kept indices.
    if biometrics:
        bio_dict = dict(biometrics)
        kept_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        aligned = {
            field: [list(bio_dict.get(field) or [None] * len(texts))[i] for i in kept_indices]
            for field in _BIOMETRIC_FIELDS
        }
        biometric_block = build_biometric_features(aligned)
        embeddings = np.hstack([embeddings, biometric_block])

    n = len(text_list)
    reduced = UMAP(
        n_components=2, n_neighbors=min(5, n - 1),
        min_dist=0.1, random_state=42
    ).fit_transform(embeddings)

    # ── Cluster count: either user-fixed, or sweep silhouette to find optimum ──
    # We cap k at n-1 so silhouette is always defined (it needs >=2 clusters
    # and >=2 points per cluster on average to be meaningful).
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
                # silhouette is undefined if a single cluster swallows everything.
                if len(set(trial_labels)) < 2:
                    continue
                s = float(silhouette_score(embeddings, trial_labels, metric="cosine"))
                k_search_results.append((k_try, s))
                if s > best_s:
                    best_s, best_k = s, k_try
            except Exception:
                continue
        k_used = best_k

    # Final fit at chosen k.
    labels = KMeans(
        n_clusters=k_used, n_init=10, random_state=42
    ).fit_predict(embeddings)

    # ── Quality metrics ──
    # Silhouette score: -1 (bad) to 1 (well-separated).
    # Cohesion: mean cosine similarity to centroid; 1 = identical, 0 = orthogonal.
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

    # Label each cluster with top TF-IDF terms from its texts
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


TOPIC_COLORS = [
    "#e05a3a", "#3dab7a", "#d4850a", "#5b6fa6", "#9b59b6",
    "#1abc9c", "#e74c3c", "#2980b9", "#f39c12", "#27ae60",
]


def _avg_or_none(values):
    """Mean of a list of numerics treating None as missing; returns None if all missing."""
    nums = [float(v) for v in values if v is not None]
    return float(np.mean(nums)) if nums else None


def _fmt_metric(v, suffix="", digits=1):
    return "—" if v is None else f"{v:.{digits}f}{suffix}"


def _cluster_top_keywords(texts_in_cluster, all_texts, top_n=5):
    """TF-IDF top distinctive keywords for a cluster vs the rest of the corpus."""
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
        # Distinctiveness: weight up terms more frequent in cluster than corpus.
        distinctiveness = cluster_vec - 0.6 * corpus_vec
        top_idx = distinctiveness.argsort()[::-1][:top_n]
        return [terms[i] for i in top_idx if distinctiveness[i] > 0]
    except Exception:
        return []


def render_bertopic_tab(rows, oura_by_date):
    st.markdown('<p class="title-text">Topic Map</p>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">sentence-transformers + UMAP + KMeans + TF-IDF labels &middot; clusters also factor in mood &amp; Oura biometrics</div>', unsafe_allow_html=True)

    MIN_ENTRIES = 10
    if len(rows) < MIN_ENTRIES:
        st.markdown(f'<div class="min-data-msg">Topic modeling needs at least <strong>{MIN_ENTRIES} entries</strong>. You have <strong>{len(rows)}</strong> so far &mdash; keep journaling.</div>', unsafe_allow_html=True)
        return

    texts = [r["content"] for r in rows]
    dates = [r["entry_date"] for r in rows]
    moods = [r["mood"] for r in rows]
    n_texts = sum(1 for t in texts if t and t.strip())

    # Build per-row biometric values aligned to `texts`. Pull from Oura by
    # entry_date — missing days come through as None and get mean-imputed
    # inside build_biometric_features(). Tuple-of-tuples form keeps the arg
    # hashable for run_topic_map's @st.cache_data decorator.
    biometrics = (
        ("mood", tuple(moods)),
        ("sleep_score",     tuple((oura_by_date.get(d) or {}).get("sleep_score")     for d in dates)),
        ("readiness_score", tuple((oura_by_date.get(d) or {}).get("readiness_score") for d in dates)),
        ("hrv_avg",         tuple((oura_by_date.get(d) or {}).get("hrv_avg")         for d in dates)),
        ("resting_hr",      tuple((oura_by_date.get(d) or {}).get("resting_hr")      for d in dates)),
    )

    # ── Cluster-count controls ──
    # Auto: sweep k in [2, min(10, n-1)] and pick the one with the highest
    # silhouette score. Manual: user picks k directly. The manual upper bound
    # caps at n-1 so silhouette is always defined.
    st.markdown('<div class="section-label" style="margin-top:0">Cluster settings</div>', unsafe_allow_html=True)
    ctrl_col1, ctrl_col2 = st.columns([1, 2])
    with ctrl_col1:
        mode = st.radio(
            "Cluster count",
            options=["Auto-optimize", "Choose manually"],
            index=0,
            key="topic_cluster_mode",
            label_visibility="visible",
        )
    with ctrl_col2:
        max_k = max(2, min(12, n_texts - 1))
        if mode == "Choose manually":
            chosen_k = st.slider(
                "Number of clusters (k)",
                min_value=2, max_value=max_k, value=min(5, max_k), step=1,
                key="topic_manual_k",
            )
        else:
            chosen_k = None
            st.markdown(
                f'<div style="color:#888; font-size:0.86rem; padding-top:0.4rem">'
                f'Sweeping k = 2…{min(10, max_k)} and picking the k with the best silhouette score.'
                f'</div>',
                unsafe_allow_html=True,
            )

    if not st.button("▶ Run Topic Model", type="primary", key="run_topic_map"):
        st.markdown('<div style="color:#aaa; font-size:0.92rem; margin-top:0.5rem">Click to cluster your entries. Takes ~20 sec on first run.</div>', unsafe_allow_html=True)
        return

    status = st.status("Building topic map…", expanded=True)
    with status:
        st.write("Loading NLP models…")
        load_nlp_models()
        st.write("Embedding and clustering…")
        try:
            reduced, topics, topic_labels, text_list, metrics = run_topic_map(
                tuple(texts), biometrics,
                n_clusters=chosen_k,
                k_search_range=(2, min(10, max_k)),
            )
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
    color_map = {t: TOPIC_COLORS[i % len(TOPIC_COLORS)] for i, t in enumerate(unique_topics)}

    # ── Global quality metrics card ──
    # Silhouette: -1 to 1 (separation between clusters). >0.5 strong, 0.25-0.5
    # reasonable, <0.25 weak. Cohesion: 0 to 1 (intra-cluster cosine similarity
    # to centroid). >0.5 tight, <0.3 loose. We label qualitatively so users
    # don't have to remember the scale.
    sil = metrics["silhouette"]
    coh = metrics["cohesion"]
    k_used = metrics["k_used"]

    def _qual(score, thresholds):
        if score is None or (isinstance(score, float) and np.isnan(score)):
            return "n/a", "#999"
        for label, lo, color in thresholds:
            if score >= lo:
                return label, color
        return "weak", "#c0392b"

    sil_label, sil_color = _qual(sil, [
        ("strong", 0.5, "#2a8a5e"),
        ("reasonable", 0.25, "#d4850a"),
        ("weak", -1.0, "#c0392b"),
    ])
    coh_label, coh_color = _qual(coh, [
        ("tight", 0.5, "#2a8a5e"),
        ("moderate", 0.3, "#d4850a"),
        ("loose", -1.0, "#c0392b"),
    ])

    st.markdown('<div class="section-label" style="margin-top:1.6rem">Cluster quality</div>', unsafe_allow_html=True)
    # NOTE: HTML must be written WITHOUT leading whitespace per line.
    # Streamlit pipes st.markdown() output through a markdown parser before
    # rendering, and markdown treats 4+ spaces of indentation as a code block,
    # which causes our HTML to render as literal text. We build the string
    # without indentation to avoid that trap.
    k_source = "auto-selected" if chosen_k is None else "user-selected"
    metrics_html = (
        '<div class="stat-grid">'
        '<div class="stat-card">'
        '<div class="stat-card-label">Clusters (k)</div>'
        f'<div class="stat-card-value">{k_used}</div>'
        f'<div class="stat-card-sub">{k_source}</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-card-label">Silhouette</div>'
        f'<div class="stat-card-value">{_fmt_metric(sil, digits=2)}</div>'
        f'<div class="stat-card-sub" style="color:{sil_color}">{sil_label} separation</div>'
        '</div>'
        '<div class="stat-card">'
        '<div class="stat-card-label">Cohesion</div>'
        f'<div class="stat-card-value">{_fmt_metric(coh, digits=2)}</div>'
        f'<div class="stat-card-sub" style="color:{coh_color}">{coh_label} grouping</div>'
        '</div>'
        '</div>'
    )
    st.markdown(metrics_html, unsafe_allow_html=True)

    # If we ran a sweep, show the silhouette curve so the user can see why this k won.
    if metrics["k_search_results"]:
        sweep = metrics["k_search_results"]
        sweep_fig = go.Figure()
        ks = [k for k, _ in sweep]
        ss = [s for _, s in sweep]
        bar_colors = ["#3dab7a" if k == k_used else "#c9d4cb" for k in ks]
        sweep_fig.add_trace(go.Bar(
            x=ks, y=ss, marker=dict(color=bar_colors),
            text=[f"{s:.2f}" for s in ss], textposition="outside",
            hovertemplate="k=%{x}<br>silhouette=%{y:.3f}<extra></extra>",
        ))
        sweep_fig.update_layout(
            paper_bgcolor="#f7f6f2", plot_bgcolor="#f7f6f2",
            margin=dict(l=20, r=20, t=10, b=30), height=200,
            xaxis=dict(title="k (clusters)", color="#888", dtick=1),
            yaxis=dict(title="silhouette", color="#888", showgrid=True, gridcolor="#ece9df"),
            font=dict(family="DM Sans"),
            showlegend=False,
        )
        with st.expander(f"Silhouette sweep — k={k_used} picked"):
            st.plotly_chart(sweep_fig, use_container_width=True)

    # ── Main scatter plot ──
    st.markdown('<div class="section-label" style="margin-top:1.6rem">Topic map</div>', unsafe_allow_html=True)
    fig = go.Figure()
    for tid in unique_topics:
        mask = [i for i, t in enumerate(topics) if t == tid]
        label = topic_labels.get(tid, f"Cluster {tid}")
        hover = [f"<b>{aligned_dates[i]}</b><br>Mood: {aligned_moods[i]}<br>{text_list[i][:80]}…" for i in mask]
        fig.add_trace(go.Scatter(
            x=[reduced[i, 0] for i in mask],
            y=[reduced[i, 1] for i in mask],
            mode="markers",
            name=f"Cluster {tid} — {label}",
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

    # ── Per-cluster characteristic summary ──
    # For each cluster, surface: mood + biometric averages, top distinctive
    # TF-IDF keywords, top feelings (from per-row feelings payload), and
    # per-cluster cohesion/silhouette. This is the "what does this cluster
    # actually feel like?" view.
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label" style="margin-top:0">Cluster characteristics</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.88rem; margin-bottom:0.8rem">'
        'What each cluster looks like physiologically and thematically.'
        '</div>',
        unsafe_allow_html=True,
    )

    # Pre-index rows by content for biometric + feelings lookup.
    content_to_row = {r["content"]: r for r in rows}

    for tid in unique_topics:
        idxs = [i for i, t in enumerate(topics) if t == tid]
        if not idxs:
            continue
        color = color_map[tid]
        label = topic_labels.get(tid, f"Cluster {tid}")
        count = len(idxs)

        # Mood: pull from aligned moods (already per-row).
        cluster_moods = [aligned_moods[i] for i in idxs if aligned_moods[i] is not None]
        avg_mood = float(np.mean(cluster_moods)) if cluster_moods else None
        mood_std = float(np.std(cluster_moods)) if len(cluster_moods) > 1 else None

        # Biometrics: pull from oura_by_date keyed on each entry's date.
        cluster_sleep, cluster_readiness, cluster_hrv, cluster_rhr = [], [], [], []
        for i in idxs:
            d = aligned_dates[i]
            oura_row = oura_by_date.get(d) or {}
            cluster_sleep.append(oura_row.get("sleep_score"))
            cluster_readiness.append(oura_row.get("readiness_score"))
            cluster_hrv.append(oura_row.get("hrv_avg"))
            cluster_rhr.append(oura_row.get("resting_hr"))

        avg_sleep = _avg_or_none(cluster_sleep)
        avg_readiness = _avg_or_none(cluster_readiness)
        avg_hrv = _avg_or_none(cluster_hrv)
        avg_rhr = _avg_or_none(cluster_rhr)

        # Top distinctive keywords for this cluster vs the rest of the corpus.
        cluster_texts = [text_list[i] for i in idxs]
        kws = _cluster_top_keywords(cluster_texts, text_list, top_n=5)

        # Top feelings appearing in this cluster's entries (from the feelings
        # payload stored per reflection). Count occurrences, then take top 4.
        feeling_counter: dict[str, int] = {}
        for i in idxs:
            row = content_to_row.get(text_list[i]) or {}
            for f in (row.get("feelings") or []):
                name = (f.get("name") or "").strip()
                if name:
                    feeling_counter[name] = feeling_counter.get(name, 0) + 1
        top_feelings = sorted(feeling_counter.items(), key=lambda x: -x[1])[:4]

        # Per-cluster quality metrics
        c_sil = metrics["per_cluster_silhouette"].get(tid)
        c_coh = metrics["per_cluster_cohesion"].get(tid)

        # Build chips for keywords + feelings
        kw_chips = "".join(
            f'<span class="kw-chip">{k}</span>' for k in kws
        ) if kws else '<span style="color:#aaa; font-size:0.86rem">no distinctive terms</span>'
        feel_chips = "".join(
            f'<span class="kw-chip kw-chip-neutral">{name} &middot; {cnt}</span>'
            for name, cnt in top_feelings
        ) if top_feelings else '<span style="color:#aaa; font-size:0.86rem">no feelings logged in this cluster</span>'

        # Card. We use the existing .insight-card / .stat-card classes so it
        # matches the rest of the app's visual language. Built as concatenated
        # strings (no leading whitespace per line) because Streamlit's markdown
        # parser treats 4+ spaces of indentation as a code block.
        mood_sub = ("±" + f"{mood_std:.1f}") if mood_std is not None else "single entry"
        card_html = (
            f'<div class="insight-card" style="border-left:4px solid {color}; padding:1.2rem 1.4rem">'
            f'<div style="display:flex; align-items:center; gap:10px; margin-bottom:0.4rem">'
            f'<div style="width:12px;height:12px;border-radius:50%;background:{color}"></div>'
            f'<div class="insight-header" style="margin:0">Cluster {tid} &mdash; {label}</div>'
            f'</div>'
            f'<div style="color:#888; font-size:0.84rem; margin-bottom:1rem">'
            f'{count} entries &middot; cohesion {_fmt_metric(c_coh, digits=2)} &middot; silhouette {_fmt_metric(c_sil, digits=2)}'
            f'</div>'
            f'<div class="stat-grid" style="grid-template-columns: repeat(5, 1fr); gap:8px; margin-bottom:1rem">'
            f'<div class="stat-card" style="padding:0.75rem 0.9rem">'
            f'<div class="stat-card-label">Mood</div>'
            f'<div class="stat-card-value" style="font-size:1.4rem">{_fmt_metric(avg_mood)}</div>'
            f'<div class="stat-card-sub">{mood_sub}</div>'
            f'</div>'
            f'<div class="stat-card" style="padding:0.75rem 0.9rem">'
            f'<div class="stat-card-label">Sleep</div>'
            f'<div class="stat-card-value" style="font-size:1.4rem">{_fmt_metric(avg_sleep, digits=0)}</div>'
            f'<div class="stat-card-sub">score</div>'
            f'</div>'
            f'<div class="stat-card" style="padding:0.75rem 0.9rem">'
            f'<div class="stat-card-label">Readiness</div>'
            f'<div class="stat-card-value" style="font-size:1.4rem">{_fmt_metric(avg_readiness, digits=0)}</div>'
            f'<div class="stat-card-sub">score</div>'
            f'</div>'
            f'<div class="stat-card" style="padding:0.75rem 0.9rem">'
            f'<div class="stat-card-label">HRV</div>'
            f'<div class="stat-card-value" style="font-size:1.4rem">{_fmt_metric(avg_hrv, digits=0)}</div>'
            f'<div class="stat-card-sub">ms avg</div>'
            f'</div>'
            f'<div class="stat-card" style="padding:0.75rem 0.9rem">'
            f'<div class="stat-card-label">Resting HR</div>'
            f'<div class="stat-card-value" style="font-size:1.4rem">{_fmt_metric(avg_rhr, digits=0)}</div>'
            f'<div class="stat-card-sub">bpm</div>'
            f'</div>'
            f'</div>'
            f'<div style="font-size:0.74rem; font-weight:600; color:#888; letter-spacing:0.12em; text-transform:uppercase; margin-bottom:0.4rem">Key reflection terms</div>'
            f'<div class="keywords-row" style="margin-bottom:0.9rem">{kw_chips}</div>'
            f'<div style="font-size:0.74rem; font-weight:600; color:#888; letter-spacing:0.12em; text-transform:uppercase; margin-bottom:0.4rem">Top feelings</div>'
            f'<div class="keywords-row">{feel_chips}</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)


# ── Dendrogram viz ────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def run_dendrogram(
    phrases_tuple: tuple,
    biometrics: tuple | None = None,
    n_clusters: int | None = None,
    k_search_range: tuple[int, int] = (2, 8),
):
    """Run hierarchical clustering on a tuple of pre-filtered phrases.

    Args:
        phrases_tuple: tuple of phrase strings.
        biometrics: optional tuple of (field_name, values_tuple) pairs — one
            value per phrase, the average of that biometric across days the
            phrase appears in (see biometric_profile_per_phrase). Tuple-of-
            tuples form keeps args hashable for st.cache_data.
        n_clusters: if provided, cut the dendrogram tree at the level that
            produces exactly this many flat clusters. If None, sweep
            `k_search_range` and pick the k with the best silhouette score.
        k_search_range: (min_k, max_k) inclusive, used only when n_clusters
            is None. Capped at n_phrases - 1 so silhouette stays defined.

    Returns:
        phrases, Z, cluster_ids, metrics
        - cluster_ids: 1-indexed (scipy convention from fcluster).
        - metrics: dict with silhouette, cohesion (mean intra-cluster cosine
          similarity to centroid), per-cluster versions, k_used, and the
          k-search sweep results if one was run.

        Returns (None, None, None, None) on too few phrases.
    """
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist
    from sklearn.metrics import silhouette_score, silhouette_samples

    phrases = list(phrases_tuple)
    if len(phrases) < 4:
        return None, None, None, None

    embeddings = get_embeddings(phrases)
    if embeddings.shape[0] == 0:
        return None, None, None, None

    # Augment phrase embeddings with the phrase's mean biometric profile.
    # A phrase like "creative projects" appearing on high-HRV/high-mood days
    # will cluster closer to other phrases from similar physiological contexts
    # than text alignment alone would suggest.
    if biometrics:
        bio_dict = dict(biometrics)
        aligned = {f: list(bio_dict.get(f) or [None] * len(phrases)) for f in _BIOMETRIC_FIELDS}
        biometric_block = build_biometric_features(aligned)
        embeddings = np.hstack([embeddings, biometric_block])

    # Compute linkage once. The dendrogram tree itself is the same regardless
    # of where we cut it for flat clusters — only the flat cluster assignment
    # changes when k changes.
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

    # Cut the tree at k_used. fcluster returns 1-indexed labels — that's
    # scipy's convention and the rest of the dendrogram code already expects it.
    cluster_ids = fcluster(Z, t=k_used, criterion="maxclust")

    # ── Quality metrics ──
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


def render_connections_tab(supabase, user_id: str, show_header: bool = True) -> None:
    # show_header=False when this renders inside the Profile tab, which
    # already carries the page title.
    if show_header:
        st.markdown('<p class="title-text">Connections</p>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">'
        'Connect external health and wellness apps to Mirra. More integrations coming soon.'
        '</div>',
        unsafe_allow_html=True,
    )

    oura_action_url = None
    oura_client_id = st.secrets.get("OURA_CLIENT_ID")
    oura_client_secret = st.secrets.get("OURA_CLIENT_SECRET")
    oura_redirect_uri = st.secrets.get("OURA_REDIRECT_URI")
    if oura_client_id and oura_client_secret and oura_redirect_uri:
        # One helper mints AND persists the nonce (oura_ui.issue_oauth_state), so
        # this card and the "Connect with Oura" button below can never disagree
        # about whether the state is in `oura_oauth_states`.
        state = oura_ui.issue_oauth_state(supabase, user_id)
        if state:
            oura_action_url = oura.build_oauth_authorize_url(
                client_id=oura_client_id,
                redirect_uri=oura_redirect_uri,
                state=state,
            )

    # --- Debug helper (temporary) ------------------------------------------------
    try:
        if st.checkbox("Show Oura debug info (developer only)", key="oura_debug"):
            st.markdown("**Oura debug**")
            st.write("session_state['oura_oauth_state']:", st.session_state.get("oura_oauth_state"))
            st.write("OURA_CLIENT_ID present:", bool(oura_client_id))
            st.write("OURA_REDIRECT_URI present:", bool(oura_redirect_uri))
            try:
                rows = supabase.table("oura_oauth_states").select("*").eq("user_id", user_id).execute()
                st.write("DB: oura_oauth_states rows for this user:", rows.data if getattr(rows, 'data', None) is not None else rows)
            except Exception as e:
                st.write("DB query failed:", e)
            # Show the authorize URL so you can copy/paste it to inspect redirect errors
            if oura_action_url:
                st.write("Authorize URL:", oura_action_url)
    except Exception:
        pass

    oura_creds_res = supabase.table("oura_credentials").select("user_id").eq("user_id", user_id).execute()
    oura_connected = bool(oura_creds_res.data)
    oura_status = (
        "Connected" if oura_connected else "Ready to connect" if oura_action_url else "Not configured"
    )
    oura_action_label = "Reconnect" if oura_connected else "Connect"

    apps = [
        {
            "name": "Oura",
            "description": "Connect your Oura Ring for sleep, readiness, and activity data.",
            "status": oura_status,
            "action_url": oura_action_url,
            "action_label": oura_action_label,
        },
        {"name": "Whoop", "description": "Coming soon: connect Whoop for recovery and strain insights.", "status": "Not configured", "action_url": None},
        {"name": "Strava", "description": "Coming soon: connect Strava to sync workouts and training data.", "status": "Not configured", "action_url": None},
        # MIR-3: live Spotify connection via the provider framework. Falls back to
        # a "Not configured" card if secrets or the connections tables are missing,
        # so this card can never break the tab.
        connections_ui.provider_card(
            supabase, user_id, "spotify",
            description="Connect Spotify for listening and mood correlations.",
        ),
    ]

    for app in apps:
        button_label = app.get("action_label", "Connect") if app["action_url"] else "Coming soon"
        action_html = ""
        # target="_top", not "_self": vendor consent pages send
        # `X-Frame-Options: DENY` / `frame-ancestors 'none'`, so if the app is
        # ever viewed inside a frame (Streamlit Cloud's editor preview, an
        # embedded browser, an <iframe> embed) a "_self" hop navigates the frame
        # and the browser shows "refused to connect". "_top" always targets the
        # real tab, and behaves exactly like "_self" when there's no frame.
        card_start = (
            f'<a href="{app["action_url"]}" target="_top" '
            f'style="display:block;text-decoration:none;color:inherit;">'
        ) if app["action_url"] else ""
        card_end = "</a>" if app["action_url"] else ""

        if app["action_url"]:
            action_html = (
                f'<span style="display:inline-block;background:#3dab7a;color:white;'
                f'border-radius:10px;padding:0.75rem 1.2rem;font-weight:700;">'
                f'{button_label}</span>'
            )
        else:
            action_html = (
                f'<button style="background:#ccc;color:white;border:none;border-radius:10px;'
                f'padding:0.75rem 1.2rem;font-weight:700;" disabled>{button_label}</button>'
            )

        # The card body is built from <span>s, not <div>s, on purpose. st.markdown
        # renders this single line as inline HTML inside a <p>, and the HTML5
        # parser closes that <p> the moment it meets a block element — which
        # tears the wrapping <a> apart and leaves most of the card unclickable.
        # Inline elements with display:block/flex keep the anchor in one piece.
        st.markdown(
            f'{card_start}'
            f'<span style="display:block; background:#fff; border:1px solid #ece9df; border-radius:15px; padding:1.2rem; margin-bottom:0.9rem;">'
            f'<span style="display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:0.6rem;">'
            f'<span style="display:block;">'
            f'<span style="display:block; font-size:1rem; font-weight:700; color:#1a1a1a;">{app["name"]}</span>'
            f'<span style="display:block; font-size:0.9rem; color:#666; margin-top:0.18rem;">{app["description"]}</span>'
            f'</span>'
            f'<span style="display:block;">{action_html}</span>'
            f'</span>'
            f'<span style="display:block; font-size:0.82rem; color:#999;">Status: {app["status"]}</span>'
            f'</span>'
            f'{card_end}',
            unsafe_allow_html=True,
        )


def render_dendrogram_tab(rows, oura_by_date):
    st.markdown('<p class="title-text">Phrase Dendrogram</p>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem"> noun phrases (3&ndash;5 words) &middot; sentence-transformers embeddings &middot; hierarchical clustering with silhouette-optimised cut &middot; clusters factor in each phrase\'s avg mood &amp; Oura biometrics</div>', unsafe_allow_html=True)

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

    # ── Cluster-count controls ────────────────────────────────────────────────
    # Auto: sweep k=2..8 over the dendrogram's fcluster cuts and pick the k
    # with the highest silhouette score. Manual: user picks where to cut the
    # tree directly. The dendrogram visualization is the same either way —
    # only the flat-cluster colouring/grouping changes with k.
    st.markdown('<div class="section-label" style="margin-top:0">Cluster settings</div>', unsafe_allow_html=True)
    ctrl_col1, ctrl_col2 = st.columns([1, 2])
    with ctrl_col1:
        dendro_mode = st.radio(
            "Cluster count",
            options=["Auto-optimize", "Choose manually"],
            index=0,
            key="dendro_cluster_mode",
            label_visibility="visible",
        )
    # Phrase-count for slider upper bound depends on whether a query is active.
    # If query active, the phrase set is capped at 25; otherwise it's all
    # unique_phrases. We use a safe ceiling of 10 since beyond ~8 the
    # dendrogram becomes hard to interpret visually.
    candidate_n = 25 if query.strip() else len(unique_phrases)
    max_k_dendro = max(2, min(10, candidate_n - 1))
    with ctrl_col2:
        if dendro_mode == "Choose manually":
            chosen_k_dendro = st.slider(
                "Number of clusters (k)",
                min_value=2, max_value=max_k_dendro,
                value=min(4, max_k_dendro), step=1,
                key="dendro_manual_k",
            )
        else:
            chosen_k_dendro = None
            st.markdown(
                f'<div style="color:#888; font-size:0.86rem; padding-top:0.4rem">'
                f'Sweeping k = 2…{min(8, max_k_dendro)} and picking the k with '
                f'the best silhouette score.'
                f'</div>',
                unsafe_allow_html=True,
            )

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
            st.write("Clustering with text and biometric profile…")
            # Build per-phrase biometric averages from the reflection corpus.
            # Phrases that don't appear in any entry (e.g. synthesised by a
            # similarity query) get None values, which mean-impute inside
            # build_biometric_features.
            phrase_bio = biometric_profile_per_phrase(
                phrases_to_cluster, rows, oura_by_date
            )
            biometric_tuple = tuple(
                (field, tuple(phrase_bio[field])) for field in _BIOMETRIC_FIELDS
            )
            try:
                phrases, Z, cluster_ids, metrics = run_dendrogram(
                    tuple(phrases_to_cluster), biometric_tuple,
                    n_clusters=chosen_k_dendro,
                    k_search_range=(2, min(8, max_k_dendro)),
                )
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
            "metrics": metrics,
            "chosen_k": chosen_k_dendro,
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
    metrics          = res.get("metrics") or {}
    chosen_k_stored  = res.get("chosen_k")
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

    # ── Global cluster quality metrics ────────────────────────────────────────
    # Same scoring scheme as the Topic Map tab: silhouette + cohesion with
    # qualitative labels. These describe the FULL clustering (the result of
    # the Run button), not whatever is currently filtered in the view below.
    if metrics:
        sil = metrics.get("silhouette")
        coh = metrics.get("cohesion")
        k_used = metrics.get("k_used")

        def _qual_d(score, thresholds):
            if score is None or (isinstance(score, float) and np.isnan(score)):
                return "n/a", "#999"
            for label, lo, color in thresholds:
                if score >= lo:
                    return label, color
            return "weak", "#c0392b"

        sil_label, sil_color = _qual_d(sil, [
            ("strong", 0.5, "#2a8a5e"),
            ("reasonable", 0.25, "#d4850a"),
            ("weak", -1.0, "#c0392b"),
        ])
        coh_label, coh_color = _qual_d(coh, [
            ("tight", 0.5, "#2a8a5e"),
            ("moderate", 0.3, "#d4850a"),
            ("loose", -1.0, "#c0392b"),
        ])

        def _fmt_d(v, digits=2):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return "—"
            return f"{v:.{digits}f}"

        k_source = "auto-selected" if chosen_k_stored is None else "user-selected"
        st.markdown('<div class="section-label" style="margin-top:1rem">Cluster quality</div>', unsafe_allow_html=True)
        metrics_html = (
            '<div class="stat-grid">'
            '<div class="stat-card">'
            '<div class="stat-card-label">Clusters (k)</div>'
            f'<div class="stat-card-value">{k_used if k_used is not None else "—"}</div>'
            f'<div class="stat-card-sub">{k_source}</div>'
            '</div>'
            '<div class="stat-card">'
            '<div class="stat-card-label">Silhouette</div>'
            f'<div class="stat-card-value">{_fmt_d(sil)}</div>'
            f'<div class="stat-card-sub" style="color:{sil_color}">{sil_label} separation</div>'
            '</div>'
            '<div class="stat-card">'
            '<div class="stat-card-label">Cohesion</div>'
            f'<div class="stat-card-value">{_fmt_d(coh)}</div>'
            f'<div class="stat-card-sub" style="color:{coh_color}">{coh_label} grouping</div>'
            '</div>'
            '</div>'
        )
        st.markdown(metrics_html, unsafe_allow_html=True)

        # If we ran an auto-sweep, surface the silhouette curve in an expander
        # so the user can see why the chosen k won.
        sweep = metrics.get("k_search_results") or []
        if sweep:
            sweep_fig = go.Figure()
            ks = [k for k, _ in sweep]
            ss = [s for _, s in sweep]
            bar_colors = ["#3dab7a" if k == k_used else "#c9d4cb" for k in ks]
            sweep_fig.add_trace(go.Bar(
                x=ks, y=ss, marker=dict(color=bar_colors),
                text=[f"{s:.2f}" for s in ss], textposition="outside",
                hovertemplate="k=%{x}<br>silhouette=%{y:.3f}<extra></extra>",
            ))
            sweep_fig.update_layout(
                paper_bgcolor="#f7f6f2", plot_bgcolor="#f7f6f2",
                margin=dict(l=20, r=20, t=10, b=30), height=200,
                xaxis=dict(title="k (clusters)", color="#888", dtick=1),
                yaxis=dict(title="silhouette", color="#888", showgrid=True, gridcolor="#ece9df"),
                font=dict(family="DM Sans"),
                showlegend=False,
            )
            with st.expander(f"Silhouette sweep — k={k_used} picked"):
                st.plotly_chart(sweep_fig, use_container_width=True)

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
        # Re-cluster the filtered subset. Re-build biometrics over just the
        # kept phrases so the sub-dendrogram stays consistent with the full
        # one (same text + biometric augmentation, just a narrower input).
        try:
            sub_bio = biometric_profile_per_phrase(keep, rows, oura_by_date)
            sub_bio_tuple = tuple(
                (field, tuple(sub_bio[field])) for field in _BIOMETRIC_FIELDS
            )
            # When drilling into a single cluster, let the sub-dendrogram
            # auto-pick its own k via silhouette — the user already filtered,
            # so a second slider would be redundant noise.
            view_phrases, view_Z, view_cluster_ids, _sub_metrics = run_dendrogram(
                tuple(keep), sub_bio_tuple
            )
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

        # ── Thematic insights ────────────────────────────────────────────────
        # The dendrogram retrieved 25 phrases related to the query. The cards
        # below pivot from describing the CLUSTERING to describing what those
        # phrases reveal about your life: what's different about your
        # high-mood vs low-mood theme entries, what biometric signals split
        # them, which phrases recur together, and which dendrogram cluster
        # tends to coincide with your best/worst moods.
        insights = compute_thematic_insights(
            phrases, cluster_to_phrases, rows, oura_by_date
        )

        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.markdown('<div class="section-label" style="margin-top:0">Thematic insights</div>', unsafe_allow_html=True)

        n_theme = insights["n_theme"]
        theme_blurb = (
            f'Your reflections touched this theme on <strong>{n_theme}</strong> '
            f'day{"s" if n_theme != 1 else ""}. '
            f'These cuts contrast what shows up on different kinds of theme days.'
        )
        if n_theme == 0:
            theme_blurb = (
                'None of your reflections directly contain the retrieved phrases as text — '
                'the dendrogram surfaced semantically similar concepts, but they don\'t appear verbatim. '
                'Try a query closer to your own writing.'
            )
        st.markdown(
            f'<div style="color:#666; font-size:0.9rem; margin-bottom:1.2rem; line-height:1.5">{theme_blurb}</div>',
            unsafe_allow_html=True,
        )

        if n_theme == 0:
            # Nothing meaningful to show below — bail cleanly.
            return

        def _phrase_chip_row(items: list[tuple], variant: str = "good") -> str:
            """Render a row of phrase chips with their high/low counts.
            `items` is list of (phrase, high_count, low_count, score)."""
            if not items:
                return '<div style="color:#aaa; font-size:0.86rem; padding:0.3rem 0">No phrases stood out for this cut.</div>'
            cls = "kw-chip" if variant == "good" else "kw-chip kw-chip-neutral"
            html = '<div class="keywords-row">'
            for phrase, hi, lo, _score in items:
                # Show the raw count split so the user can see we're not
                # over-claiming from a 1-vs-0 cut.
                html += f'<span class="{cls}">{phrase} <span style="opacity:0.6">&middot; {hi}/{lo}</span></span>'
            html += "</div>"
            return html

        # ── Headline insight: mood split ────────────────────────────────────
        ms = insights["mood_split"] or {}
        st.markdown(
            '<div style="font-family:Lora,serif; font-size:1.05rem; font-weight:600; color:#1a1a1a; margin:0.6rem 0 0.3rem">'
            'What shows up on your higher-mood theme days'
            '</div>',
            unsafe_allow_html=True,
        )
        if ms.get("skip"):
            st.markdown(
                f'<div style="color:#aaa; font-size:0.88rem; padding:0.4rem 0">{ms.get("reason", "")}</div>',
                unsafe_allow_html=True,
            )
        else:
            sub = (
                f'Split at mood median <strong>{ms["median"]:.1f}</strong> &middot; '
                f'higher half avg <strong>{ms["mood_high_avg"]:.1f}</strong> (n={ms["n_high"]}) &middot; '
                f'lower half avg <strong>{ms["mood_low_avg"]:.1f}</strong> (n={ms["n_low"]})'
            )
            st.markdown(
                f'<div style="color:#888; font-size:0.86rem; margin-bottom:0.7rem">{sub}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="font-size:0.78rem; font-weight:600; color:#2a8a5e; letter-spacing:0.08em; '
                'text-transform:uppercase; margin-bottom:0.3rem">More on higher-mood days</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_phrase_chip_row(ms["top_high_phrases"], "good"), unsafe_allow_html=True)
            st.markdown(
                '<div style="font-size:0.78rem; font-weight:600; color:#c25540; letter-spacing:0.08em; '
                'text-transform:uppercase; margin:0.8rem 0 0.3rem">More on lower-mood days</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_phrase_chip_row(ms["top_low_phrases"], "low"), unsafe_allow_html=True)
            st.markdown(
                '<div style="color:#999; font-size:0.78rem; margin-top:0.5rem; font-style:italic">'
                'Counts shown as higher-mood / lower-mood. These are associations, not causes — '
                'the phrase appears more on those days.'
                '</div>',
                unsafe_allow_html=True,
            )

        # ── Biometric splits ────────────────────────────────────────────────
        bio_splits = insights["biometric_splits"]
        any_bio = any(not v.get("skip") for v in bio_splits.values())
        if any_bio:
            st.markdown(
                '<div style="font-family:Lora,serif; font-size:1.05rem; font-weight:600; color:#1a1a1a; margin:1.6rem 0 0.3rem">'
                'What shows up on different biometric days'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="color:#888; font-size:0.86rem; margin-bottom:0.8rem">'
                'Within this theme, the phrases that distinguish your physiologically good days from bad ones.'
                '</div>',
                unsafe_allow_html=True,
            )
            for field, payload in bio_splits.items():
                if payload.get("skip"):
                    continue
                lbl = payload["label"]
                direction = payload["direction"]
                # For resting HR (lower is better), we flip the framing so
                # "higher half" still maps to "physiologically worse" — the
                # green chip row should always be the favorable side.
                if field == "resting_hr":
                    good_side, good_n = payload["top_lo_phrases"], payload["n_lo"]
                    bad_side, bad_n   = payload["top_hi_phrases"], payload["n_hi"]
                    good_label = f"lower {lbl}"
                    bad_label  = f"higher {lbl}"
                else:
                    good_side, good_n = payload["top_hi_phrases"], payload["n_hi"]
                    bad_side, bad_n   = payload["top_lo_phrases"], payload["n_lo"]
                    good_label = f"higher {lbl}"
                    bad_label  = f"lower {lbl}"

                with st.expander(f"{lbl.title()} — split at median ({direction})"):
                    st.markdown(
                        f'<div style="color:#888; font-size:0.84rem; margin-bottom:0.6rem">'
                        f'Split at {payload["median"]:.1f}. Better-side avg '
                        f'{payload["hi_avg"]:.1f} (n={payload["n_hi"]}), '
                        f'worse-side avg {payload["lo_avg"]:.1f} (n={payload["n_lo"]}).'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="font-size:0.78rem; font-weight:600; color:#2a8a5e; letter-spacing:0.08em; '
                        f'text-transform:uppercase; margin-bottom:0.3rem">More on {good_label} days (n={good_n})</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(_phrase_chip_row(good_side, "good"), unsafe_allow_html=True)
                    st.markdown(
                        f'<div style="font-size:0.78rem; font-weight:600; color:#c25540; letter-spacing:0.08em; '
                        f'text-transform:uppercase; margin:0.8rem 0 0.3rem">More on {bad_label} days (n={bad_n})</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(_phrase_chip_row(bad_side, "low"), unsafe_allow_html=True)

        # ── Co-occurring phrases ────────────────────────────────────────────
        cooc = insights["cooccurrence"]
        if cooc:
            st.markdown(
                '<div style="font-family:Lora,serif; font-size:1.05rem; font-weight:600; color:#1a1a1a; margin:1.6rem 0 0.3rem">'
                'Phrases that appear together'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="color:#888; font-size:0.86rem; margin-bottom:0.7rem">'
                'Pairs of retrieved phrases that turn up in the same reflection.'
                '</div>',
                unsafe_allow_html=True,
            )
            cooc_html = '<div style="display:flex; flex-direction:column; gap:6px">'
            for a, b, count in cooc:
                cooc_html += (
                    f'<div style="display:flex; align-items:center; gap:8px; '
                    f'background:#f0efe8; padding:8px 12px; border-radius:8px; font-size:0.88rem">'
                    f'<span class="kw-chip" style="margin:0">{a}</span>'
                    f'<span style="color:#aaa">+</span>'
                    f'<span class="kw-chip" style="margin:0">{b}</span>'
                    f'<span style="color:#888; margin-left:auto; font-size:0.82rem">'
                    f'co-occurred in <strong>{count}</strong> entr{"ies" if count != 1 else "y"}'
                    f'</span>'
                    f'</div>'
                )
            cooc_html += '</div>'
            st.markdown(cooc_html, unsafe_allow_html=True)

        # ── Cluster-level mood ranking ──────────────────────────────────────
        ranking = insights["cluster_mood_ranking"]
        if len(ranking) >= 2:
            st.markdown(
                '<div style="font-family:Lora,serif; font-size:1.05rem; font-weight:600; color:#1a1a1a; margin:1.6rem 0 0.3rem">'
                'Cluster mood ranking'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="color:#888; font-size:0.86rem; margin-bottom:0.7rem">'
                'Average mood across reflections containing any phrase from each cluster.'
                '</div>',
                unsafe_allow_html=True,
            )
            rank_html = '<div style="display:flex; flex-direction:column; gap:6px">'
            mood_min = min(t[2] for t in ranking)
            mood_max = max(t[2] for t in ranking)
            mood_range = max(0.1, mood_max - mood_min)  # avoid div-by-zero
            for cid, n_e, m in ranking:
                color = DENDRO_COLORS[(cid - 1) % len(DENDRO_COLORS)]
                # Bar width as a percentage of the mood range so the visual
                # ranking is unambiguous even when all clusters cluster near
                # the same mood.
                pct = int(20 + 80 * (m - mood_min) / mood_range)
                lbl_text = cluster_names.get(cid, f"Cluster {cid}")
                rank_html += (
                    f'<div style="display:flex; align-items:center; gap:10px; font-size:0.88rem">'
                    f'<span style="width:11px;height:11px;border-radius:50%;background:{color};flex-shrink:0"></span>'
                    f'<span style="color:#2a2a2a; min-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">Cluster {cid} — {lbl_text}</span>'
                    f'<div style="flex:1; height:8px; background:#ece9df; border-radius:4px; overflow:hidden">'
                    f'<div style="width:{pct}%; height:100%; background:{color}"></div>'
                    f'</div>'
                    f'<span style="color:#1a1a1a; font-weight:600; min-width:38px; text-align:right">{m:.1f}</span>'
                    f'<span style="color:#aaa; font-size:0.78rem; min-width:48px; text-align:right">n={n_e}</span>'
                    f'</div>'
                )
            rank_html += '</div>'
            st.markdown(rank_html, unsafe_allow_html=True)




# ── Main ──────────────────────────────────────────────────────────────────────
if not st.session_state.get("logged_in"):
    render_login_page(supabase)
    st.stop()

# Onboarding chain (MIR-1): login → intro → profile (#16) → inquiry (#43) → app.
# Each gate reads a completion marker from the users table, so signing back in
# later drops straight into the app — these screens belong to a new account.
# See onboarding.py for what happens before the markers migration is applied.
if should_run_onboarding(supabase):
    if not user_has_seen_intro(supabase, st.session_state["user_id"]):
        render_intro_page(supabase, st.session_state["user_id"])
        st.stop()

    if not user_has_completed_profile(supabase, st.session_state["user_id"]):
        render_profile_form(supabase, st.session_state["user_id"], mode="create")
        st.stop()

    if not user_has_completed_inquiry(supabase, st.session_state["user_id"]):
        render_insight_inquiry(supabase, st.session_state["user_id"])
        st.stop()

st.session_state.pop("new_account", None)  # onboarding is behind us

render_logout_button()




# ── Feelings distribution helpers ────────────────────────────────────────────
def _collect_feelings(rows: list[dict], min_ratings: int = 1) -> dict[str, list[float]]:
    """Pull all (feeling_name → list of intensity ratings) from a row set.

    Skip-rated feelings (intensity=None) are excluded since they have no
    numeric value to plot. Names are lowercased and stripped so "Anxious"
    and "anxious " count as the same feeling.

    min_ratings filters out feelings logged fewer than N times with a numeric
    intensity — useful when we want stable distribution shapes, not one-off
    dots.
    """
    bucket: dict[str, list[float]] = {}
    for r in rows:
        for f in (r.get("feelings") or []):
            name = (f.get("name") or "").lower().strip()
            intensity = f.get("intensity")
            if not name or intensity is None:
                continue
            bucket.setdefault(name, []).append(float(intensity))
    return {n: vs for n, vs in bucket.items() if len(vs) >= min_ratings}


def _top_feelings_by_frequency(
    rows: list[dict], top_n: int = 6
) -> list[str]:
    """Rank feelings by total occurrences (rated + skip-rated combined).

    We rank by raw frequency rather than only by rated frequency because a
    feeling someone marked seven times this week but never rated is still a
    dominant feeling worth surfacing — the violin will just be empty/dot for
    it and that's honest about the data.
    """
    counts: dict[str, int] = {}
    for r in rows:
        for f in (r.get("feelings") or []):
            name = (f.get("name") or "").lower().strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
    return [name for name, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top_n]]


# Palette for feelings violins — warm to cool to neutral, picked so adjacent
# violins don't clash. Cycled if there are more feelings than colors.
_FEELING_COLORS = [
    "#e05a3a",  # coral
    "#d4850a",  # amber
    "#3dab7a",  # sage
    "#5b6fa6",  # indigo
    "#9b59b6",  # plum
    "#1abc9c",  # teal
    "#c25540",  # rust
    "#27ae60",  # emerald
]


def _render_feelings_violin_single(
    feelings_data: dict[str, list[float]],
    feeling_order: list[str],
    title_color: str = "#3dab7a",
) -> go.Figure | None:
    """One violin per feeling, intensity on y-axis. Single time window."""
    feelings_with_data = [f for f in feeling_order if feelings_data.get(f)]
    if not feelings_with_data:
        return None

    fig = go.Figure()
    for i, name in enumerate(feelings_with_data):
        values = feelings_data[name]
        color = _FEELING_COLORS[i % len(_FEELING_COLORS)]
        # Convert hex to rgba for the fill so we can vary opacity without
        # touching the outline color.
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
    """Two violins per feeling side-by-side: recent vs all-time baseline.

    Uses `side="negative"` / `side="positive"` so the two halves sit
    back-to-back at the same x-tick — the user reads each pair as one
    feeling, with the left half being the long-term shape and the right half
    being the recent shape. Anywhere the right half is taller/higher than
    the left, that feeling has been hitting harder lately than baseline.
    """
    # Only plot feelings that have data in at least one window.
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
        # All-time on the left (negative side) — fainter, "baseline" visual.
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
                showlegend=(name == plottable[0]),  # show legend entry once
                legendgroup=alltime_label,
            ))
        # Recent on the right (positive side) — bolder, "current" visual.
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


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a #rrggbb hex string to an rgba() string. Used so violin
    fills can share a base color with their outline but be translucent."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


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

    # ── Feelings distribution: violins, this week only ────────────────────────
    # One violin per top-frequency feeling, showing the spread of intensity
    # ratings. The chip row below still gives the count + average; the violin
    # answers "did 'anxious' stay around a 4, or did it swing between 2 and 9
    # this week?" — which a single mean number can't show.
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Feelings intensity distribution</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.88rem; margin-bottom:0.8rem">'
        'Your top 6 feelings this week, by how intensely you rated each.'
        '</div>',
        unsafe_allow_html=True,
    )

    top_feels_week = _top_feelings_by_frequency(week_rows, top_n=6)
    week_feel_intensities = _collect_feelings(week_rows)
    fig_feel_week = _render_feelings_violin_single(week_feel_intensities, top_feels_week)
    if fig_feel_week is not None:
        st.plotly_chart(fig_feel_week, use_container_width=True)
    else:
        st.markdown(
            '<div style="color:#aaa; font-size:0.88rem; padding:0.5rem 0">'
            'No rated feelings this week yet — log a few intensities to see the distribution.'
            '</div>',
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

    # ── Feelings distribution: last 30 days vs all-time, per feeling ──────────
    # Side-by-side violins anchor each feeling to its long-term baseline.
    # If a feeling's recent (right) violin sits higher or fatter than its
    # all-time (left) violin, the user has been experiencing it more
    # intensely than usual recently. This is the trends-page equivalent of
    # the single-window violin in Weekly Insights.
    st.markdown('<div class="section-label" style="margin-top:0">Feelings intensity: recent vs baseline</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.88rem; margin-bottom:0.8rem">'
        'Top 6 feelings from your last 30 days. Left half of each pair is your '
        'all-time baseline; right half is the last 30 days.'
        '</div>',
        unsafe_allow_html=True,
    )

    # Recent window: last 30 days inclusive of today.
    today = user_today()
    cutoff_30 = (today - timedelta(days=30)).isoformat()
    recent_rows = [r for r in rows if r["entry_date"] >= cutoff_30]

    # Rank feelings by frequency in the RECENT window — that's what the user
    # cares about most right now. The all-time violin then provides context
    # for whether each of those feelings has been hitting harder than usual.
    top_feels_recent = _top_feelings_by_frequency(recent_rows, top_n=6)
    recent_intensities = _collect_feelings(recent_rows)
    alltime_intensities = _collect_feelings(rows)
    fig_feel_compare = _render_feelings_violin_compare(
        recent_intensities, alltime_intensities, top_feels_recent,
        recent_label="Last 30 days", alltime_label="All time",
    )
    if fig_feel_compare is not None:
        st.plotly_chart(fig_feel_compare, use_container_width=True)

        # Inline summary: which feelings have been running hot recently.
        # We flag a feeling as "elevated" if its 30-day mean is at least 1.0
        # higher than its all-time mean AND it has enough samples to be
        # reliable (>=3 ratings in each window).
        elevated = []
        cooler = []
        for name in top_feels_recent:
            recent_vs = recent_intensities.get(name) or []
            all_vs = alltime_intensities.get(name) or []
            if len(recent_vs) >= 3 and len(all_vs) >= 3:
                delta = float(np.mean(recent_vs) - np.mean(all_vs))
                if delta >= 1.0:
                    elevated.append((name, delta))
                elif delta <= -1.0:
                    cooler.append((name, delta))
        if elevated or cooler:
            bits = []
            if elevated:
                names = ", ".join(
                    f"<strong>{n.title()}</strong> (+{d:.1f})" for n, d in elevated
                )
                bits.append(f"running hotter: {names}")
            if cooler:
                names = ", ".join(
                    f"<strong>{n.title()}</strong> ({d:+.1f})" for n, d in cooler
                )
                bits.append(f"running cooler: {names}")
            st.markdown(
                f"<div style='color:#666; font-size:0.88rem; margin-top:-0.4rem'>"
                f"vs your all-time baseline &mdash; {' &middot; '.join(bits)}"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div style="color:#aaa; font-size:0.88rem; padding:0.5rem 0">'
            'Not enough rated feelings yet to compare against your baseline.'
            '</div>',
            unsafe_allow_html=True,
        )
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
# MIR-3 callback runs first, but only claims states shaped "<provider>:<nonce>"
# (Spotify, Whoop, …). Oura's plain-nonce state falls through to its own handler
# below untouched.
connections_ui.handle_oauth_callback(supabase, user_id)
oura_ui.handle_oauth_callback(supabase, user_id)
rows = load_all_entries(user_id)

# Pull fresh Oura data if today's row is missing/incomplete (throttled to 15 min).
oura.auto_sync_if_stale(
    supabase, user_id,
    client_id=st.secrets.get("OURA_CLIENT_ID"),
    client_secret=st.secrets.get("OURA_CLIENT_SECRET"),
)
oura_by_date = oura.load_oura_for_user(supabase, user_id)

# Connections and the Oura settings both live inside Profile now — one place
# the user manages "my stuff", instead of three tabs that each own a slice of it.
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Daily Reflection",
    "Weekly Insights",
    "Reflection Trends",
    "Topic Map",
    "Dendrogram",
    "Profile",
])

with tab1:
    render_daily_reflection_tab(rows)

with tab2:
    render_weekly_insights_tab(rows, oura_by_date)

with tab3:
    render_reflection_trends_tab(rows, oura_by_date)

with tab4:
    render_bertopic_tab(rows, oura_by_date)

with tab5:
    render_dendrogram_tab(rows, oura_by_date)

with tab6:
    render_profile_tab(supabase, user_id, render_connections=render_connections_tab)