"""
Intro / welcome page for Mirra.

Shown the first time a user signs in (or any time `has_seen_intro` is False
in the `users` table). Matches the existing Mirra styling: cream background,
sage accent (#3dab7a), Lora headings, DM Sans body — no emojis.

Usage in app.py:

    from intro_page import render_intro_page, user_has_seen_intro

    if not user_has_seen_intro(supabase, st.session_state["user_id"]):
        render_intro_page(supabase, st.session_state["user_id"])
        st.stop()
"""

import streamlit as st


# ── Intro page styles ─────────────────────────────────────────────────────────
# Visual identity: thin sage accent rules instead of emoji icons, more
# generous letter-spacing on display type, white cards on cream background
# with a very soft 1px hairline border.
INTRO_CSS = """
<style>
.intro-wrap { max-width: 620px; margin: 0 auto; padding-top: 1rem; }

.intro-eyebrow {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: #3dab7a;
    text-align: center;
    margin-bottom: 1rem;
}
.intro-title {
    font-family: 'Lora', serif;
    font-size: 2.4rem;
    font-weight: 600;
    color: #1a1a1a;
    text-align: center;
    line-height: 1.22;
    letter-spacing: -0.01em;
    margin: 0 0 0.7rem;
}
.intro-lede {
    font-size: 1.05rem;
    color: #6a6a66;
    text-align: center;
    line-height: 1.7;
    margin: 0 auto 2.6rem;
    max-width: 480px;
}

.intro-card {
    background: white;
    border-radius: 14px;
    padding: 1.4rem 1.6rem 1.5rem;
    margin-bottom: 0.85rem;
    border: 1px solid #ece9df;
    transition: border-color 0.2s ease;
}
.intro-card:hover { border-color: #d8e8df; }

.intro-card-head {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 0.6rem;
}
/* Sage accent rule instead of an emoji icon block */
.intro-accent {
    width: 22px;
    height: 2px;
    background: #3dab7a;
    border-radius: 2px;
    flex-shrink: 0;
}
.intro-card-title {
    font-family: 'Lora', serif;
    font-size: 1.15rem;
    font-weight: 600;
    color: #1a1a1a;
    margin: 0;
    letter-spacing: -0.005em;
}
.intro-card-body {
    font-size: 0.97rem;
    color: #5a5a55;
    line-height: 1.7;
    margin: 0;
    padding-left: 36px;
}

.intro-callout {
    background: transparent;
    border-top: 1px solid #ece9df;
    border-bottom: 1px solid #ece9df;
    padding: 1.2rem 0;
    margin: 2rem 0 2.2rem;
    color: #3a3a36;
    font-size: 0.98rem;
    line-height: 1.65;
    text-align: center;
    font-style: italic;
}

.intro-footnote {
    text-align: center;
    color: #aaa;
    font-size: 0.82rem;
    margin-top: 1rem;
    letter-spacing: 0.02em;
}
</style>
"""


# ── Supabase helpers ──────────────────────────────────────────────────────────
def user_has_seen_intro(supabase, user_id: str) -> bool:
    """Returns True if the user has already dismissed the intro page.

    Requires a boolean `has_seen_intro` column on the `users` table.
    Missing column or row defaults to False (i.e. show the intro).
    """
    # Session-state short-circuit: avoids a Supabase round-trip on every
    # rerun within the same session after the user dismisses the intro.
    if st.session_state.get("has_seen_intro"):
        return True
    try:
        res = (
            supabase.table("users")
            .select("has_seen_intro")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("has_seen_intro"):
            st.session_state["has_seen_intro"] = True
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
        # If the column doesn't exist yet, fall back to session-only so the
        # user doesn't see the intro twice in a session.
        pass
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
        "Your body sends signals all day &mdash; about stress, energy, emotion. "
        "Most of us miss them. Mirra helps you notice."
        "</p>",
        unsafe_allow_html=True,
    )

    # Concept cards — emoji-free, using a thin sage accent rule for visual rhythm.
    st.markdown(
        """
        <div class="intro-card">
          <div class="intro-card-head">
            <div class="intro-accent"></div>
            <p class="intro-card-title">Interoception</p>
          </div>
          <p class="intro-card-body">
            The skill of sensing what's happening inside you &mdash; heart rate,
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
            <div class="intro-accent"></div>
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
            <div class="intro-accent"></div>
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
        "mind noticed &mdash; building awareness, one day at a time."
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
            st.rerun()

    st.markdown(
        '<div class="intro-footnote">You can revisit this from Settings anytime.</div>',
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)