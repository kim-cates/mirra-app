"""Configuration, styling, and constants for Mirra app."""

import streamlit as st


def configure_page():
    """Set up Streamlit page configuration."""
    st.set_page_config(page_title="Mirra", layout="centered")
    
    # Mobile viewport
    st.markdown(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, '
        'maximum-scale=5.0">',
        unsafe_allow_html=True,
    )


def apply_styling():
    """Apply global CSS styling to the app."""
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"], .main, .block-container {
    background-color: #faf9f5 !important;
    color: #2a2a2a !important;
    font-family: 'DM Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.6rem 2rem 4rem 2rem; max-width: 1180px; }

.stTabs [data-baseweb="tab-list"] {
    gap: 2px; background: transparent; border-bottom: 1px solid #ece9df;
    border-radius: 0; padding: 0 0 0 4px; margin-bottom: 1rem;
    overflow-x: auto; flex-wrap: nowrap;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { height: 0; }
.stTabs [data-baseweb="tab"] {
    border-radius: 0; padding: 10px 18px; font-size: 0.86rem;
    font-weight: 500; color: #999; background: transparent; border: none;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
    transition: color 0.15s ease, border-color 0.15s ease;
    white-space: nowrap;
}
.stTabs [data-baseweb="tab"]:hover { color: #555; }
.stTabs [aria-selected="true"] {
    background: transparent !important; color: #1a1a1a !important;
    font-weight: 600; box-shadow: none !important;
    border-bottom: 2px solid #3dab7a !important;
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.4rem; }

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

.feeling-name { font-size: 0.95rem; font-weight: 500; color: #2a2a2a; padding-top: 8px; }
.feeling-hint { color: #888; font-size: 0.86rem; margin: 0.3rem 0 0.8rem; line-height: 1.55; }
.feeling-skip { color: #aaa; font-size: 0.85rem; font-style: italic; margin-top: 0.4rem; }

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

.login-wrap { max-width: 400px; margin: 0 auto; padding-top: 1rem; }
.login-logo { text-align: center; margin-bottom: 1.4rem; }
.login-logo img { max-width: 100%; height: auto; }
.login-title { font-family: 'Lora', serif; font-size: 2rem; font-weight: 600; color: #1a1a1a; text-align: center; margin-bottom: 0.3rem; letter-spacing: -0.01em; }
.login-sub { color: #999; font-size: 0.74rem; text-align: center; letter-spacing: 0.18em; text-transform: uppercase; margin-bottom: 1.8rem; font-weight: 500; }
.logout-btn { position: fixed; top: 14px; right: 18px; z-index: 999; }
.login-card > div:first-child:empty { display: none; }
.block-container > div:first-child { padding-top: 0 !important; }

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

@media (max-width: 768px) {
    .block-container { padding: 1rem 1rem 3rem 1rem; }
    .stat-grid { grid-template-columns: 1fr 1fr !important; gap: 8px; }
    .title-text { font-size: 1.5rem; }
    .insight-card { padding: 1rem 1.1rem; }
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


# Constants
PRESET_FEELINGS = [
    "anxious", "stressed", "overwhelmed", "depressed", "sad", "frustrated", "angry",
    "tired", "neutral", "present", "calm", "relaxed", "content", "happy",
    "grateful", "energized", "focused", "excited",
]

TOPIC_COLORS = [
    "#e05a3a", "#3dab7a", "#d4850a", "#5b6fa6", "#9b59b6",
    "#1abc9c", "#e74c3c", "#2980b9", "#f39c12", "#27ae60",
]

DENDRO_COLORS = [
    "#e05a3a", "#3dab7a", "#d4850a", "#5b6fa6", "#9b59b6",
    "#1abc9c", "#e74c3c", "#2980b9", "#f39c12", "#27ae60",
    "#c0392b", "#8e44ad", "#16a085", "#c9302c"
]

DENDRO_LABELS = ["work stress", "gratitude", "self-care", "social", "growth"]

FEELING_COLORS = [
    "#e05a3a",  # coral
    "#d4850a",  # amber
    "#3dab7a",  # sage
    "#5b6fa6",  # indigo
    "#9b59b6",  # plum
    "#1abc9c",  # teal
    "#c25540",  # rust
    "#27ae60",  # emerald
]

# Biometric configuration
BIOMETRIC_FIELDS = ("mood", "sleep_score", "readiness_score", "hrv_avg", "resting_hr")
BIOMETRIC_FEATURE_DIMS = 10
