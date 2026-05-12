"""
Intro / welcome page for Mirra.

Shown the first time a user signs in (or any time `has_seen_intro` is False
in the `users` table). Matches the existing Mirra styling: cream background,
sage accent (#3dab7a), Lora headings, DM Sans body.

Usage in app.py:

    from intro_page import render_intro_page, user_has_seen_intro

    if not user_has_seen_intro(supabase, st.session_state["user_id"]):
        render_intro_page(supabase, st.session_state["user_id"])
        st.stop()
"""

import streamlit as st


# ── Intro page styles ─────────────────────────────────────────────────────────
INTRO_CSS = """
<style>
.intro-wrap { max-width: 640px; margin: 0 auto; padding-top: 0.5rem; }

.intro-eyebrow {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #3dab7a;
    text-align: center;
    margin-bottom: 0.8rem;
}
.intro-title {
    font-family: 'Lora', serif;
    font-size: 2.2rem;
    font-weight: 700;
    color: #1a1a1a;
    text-align: center;
    line-height: 1.25;
    margin: 0 0 0.6rem;
}
.intro-lede {
    font-size: 1.02rem;
    color: #555;
    text-align: center;
    line-height: 1.65;
    margin: 0 auto 2.2rem;
    max-width: 480px;
}

.intro-card {
    background: white;
    border-radius: 16px;
    padding: 1.3rem 1.5rem;
    margin-bottom: 0.9rem;
    box-shadow: 0 1px 8px rgba(0,0,0,0.04);
    border: 1px solid #ece9df;
}
.intro-card-head {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 0.55rem;
}
.intro-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: #e8f5f0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.15rem;
    flex-shrink: 0;
}
.intro-card-title {
    font-family: 'Lora', serif;
    font-size: 1.15rem;
    font-weight: 700;
    color: #1a1a1a;
    margin: 0;
}
.intro-card-body {
    font-size: 0.96rem;
    color: #555;
    line-height: 1.65;
    margin: 0;
    padding-left: 50px;
}

.intro-callout {
    background: #e8f5f0;
    border-left: 4px solid #3dab7a;
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    margin: 1.6rem 0 1.8rem;
    color: #1e6b45;
    font-size: 0.95rem;
    line-height: 1.6;
}

.intro-footnote {
    text-align: center;
    color: #aaa;
    font-size: 0.82rem;
    margin-top: 0.8rem;
}
</style>
"""


# ── Supabase helpers ──────────────────────────────────────────────────────────
def user_has_seen_intro(supabase, user_id: str) -> bool:
    """Returns True if the user has already dismissed the intro page.

    Requires a boolean `has_seen_intro` column on the `users` table.
    Missing column or row defaults to False (i.e. show the intro).
    """
    try:
        res = (
            supabase.table("users")
            .select("has_seen_intro")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("has_seen_intro"):
            return True
    except Exception:
        pass
    return False


def mark_intro_seen(supabase, user_id: str) -> None:
    """Persist that the user has seen the intro page."""
    try:
        supabase.table("users").update(
            {"has_seen_intro": True}
        ).eq("id", user_id).execute()
    except Exception:
        # If the column doesn't exist yet, fall back to session-only
        st.session_state["has_seen_intro"] = True


# ── Page renderer ─────────────────────────────────────────────────────────────
def render_intro_page(supabase, user_id: str) -> None:
    st.markdown(INTRO_CSS, unsafe_allow_html=True)

    st.markdown('<div class="intro-wrap">', unsafe_allow_html=True)

    st.markdown(
        '<div class="intro-eyebrow">Welcome to Mirra</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<h1 class="intro-title">Listen to what your body already knows</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="intro-lede">'
        "Your body sends signals all day — about stress, energy, emotion. "
        "Most of us miss them. Mirra helps you notice."
        "</p>",
        unsafe_allow_html=True,
    )

    # ── Three concept cards ──
    st.markdown(
        """
        <div class="intro-card">
          <div class="intro-card-head">
            <div class="intro-icon">🫀</div>
            <p class="intro-card-title">Interoception</p>
          </div>
          <p class="intro-card-body">
            The skill of sensing what's happening inside you — heart rate,
            breath, tension, fatigue. Like any skill, it can be trained.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="intro-card">
          <div class="intro-card-head">
            <div class="intro-icon">🔍</div>
            <p class="intro-card-title">The gap</p>
          </div>
          <p class="intro-card-body">
            Sometimes your body shows stress your mind hasn't registered yet.
            Tight shoulders all afternoon, but the day felt &ldquo;fine.&rdquo;
            That gap is where insight lives.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="intro-card">
          <div class="intro-card-head">
            <div class="intro-icon">💍</div>
            <p class="intro-card-title">Where your ring helps</p>
          </div>
          <p class="intro-card-body">
            Oura externalizes signals you might be missing. Pair it with daily
            reflection, and over time you start catching them yourself.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="intro-callout">'
        "Each reflection helps you connect what your body felt with what your "
        "mind noticed — building awareness, one day at a time."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── CTA ──
    _, btn_col, _ = st.columns([1, 2, 1])
    with btn_col:
        if st.button(
            "Start today's reflection",
            type="primary",
            use_container_width=True,
            key="intro_continue",
        ):
            mark_intro_seen(supabase, user_id)
            st.session_state["has_seen_intro"] = True
            st.rerun()

    st.markdown(
        '<div class="intro-footnote">You can revisit this from Settings anytime.</div>',
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)
