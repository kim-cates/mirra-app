"""Profile tab (MIR-1 #18) — the one place a signed-in user manages their account.

Five sections, all reachable without leaving the tab:
  • About you   — the MIR-1 profile fields, prefilled from the database.
  • Insight focus — what the onboarding inquiry captured, retakeable.
  • Personalization — how insights are presented (data-driven / hybrid /
                      insight-focused) and which areas to focus on.
  • Connections — external data sources (Oura today, more later) + sync settings.
  • Account     — username, member since, password change, sign out.

Connections are injected as a callback rather than imported so this module
stays independent of app.py (and of whichever OAuth implementation MIR-3
settles on).
"""

from datetime import datetime

import streamlit as st

import auth
import focus_areas
import insight_inquiry
import insight_style
import insights_data as idata
import oura_ui
from intro_page import render_intro_page
from profile_form import render_profile_form

_RETAKE_KEY = "profile_retake_inquiry"


def _member_since(supabase, user_id: str) -> str | None:
    try:
        res = (supabase.table("users").select("created_at")
               .eq("id", user_id).limit(1).execute())
        if res.data and res.data[0].get("created_at"):
            raw = res.data[0]["created_at"].replace("Z", "+00:00")
            return datetime.fromisoformat(raw).strftime("%B %Y")
    except Exception:
        pass
    return None


def render_profile_tab(supabase, user_id: str, render_connections=None) -> None:
    st.markdown('<p class="title-text">Profile</p>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">'
        'Your details, what Mirra focuses on for you, and the apps you\'ve connected.'
        '</div>',
        unsafe_allow_html=True,
    )

    about_tab, focus_tab, personalization_tab, connections_tab, account_tab = st.tabs(
        ["About you", "Insight focus", "Personalization", "Connections", "Account"]
    )

    with about_tab:
        render_profile_form(supabase, user_id, mode="edit")

    with focus_tab:
        _render_focus_section(supabase, user_id)

    with personalization_tab:
        _render_personalization_section(supabase, user_id)

    with connections_tab:
        if render_connections is not None:
            render_connections(supabase, user_id, show_header=False)
        oura_ui.render_settings_tab(supabase, user_id, show_header=False)

    with account_tab:
        _render_account_section(supabase, user_id)


# ── Personalization ───────────────────────────────────────────────────────────
_PERSONALIZATION_RESULT_KEY = "personalization_save_result"


def _save_personalization(supabase, user_id: str) -> None:
    # A submit callback, not code after the button: saving the style also
    # updates the Simples toggle, which has already rendered by the time this
    # tab's code runs, and Streamlit only allows that change before the run.
    style_saved = insight_style.save_from_picker(supabase, user_id)
    areas_saved = focus_areas.save_from_picker(supabase, user_id)
    st.session_state[_PERSONALIZATION_RESULT_KEY] = style_saved and areas_saved


def _render_personalization_section(supabase, user_id: str) -> None:
    """Insight style + focus areas, saved together by one button."""
    with st.form("personalization_form"):
        insight_style.render_style_field(supabase, user_id)
        st.divider()
        focus_areas.render_focus_field(
            supabase, user_id,
            priorities=idata.load_priorities(supabase, user_id),
            df=idata.load_daily_frame(supabase, user_id),
        )
        st.form_submit_button("Save changes", type="primary",
                              on_click=_save_personalization,
                              args=(supabase, user_id))

    result = st.session_state.pop(_PERSONALIZATION_RESULT_KEY, None)
    if result is True:
        st.success("Saved. Your insights will follow these settings.")
    elif result is False:
        st.warning("Your changes apply for this session but couldn't be saved. "
                   "The users table may be missing the personalization columns — "
                   "see docs/migrations/personalization.sql.")


# ── Insight focus ─────────────────────────────────────────────────────────────
def _render_focus_section(supabase, user_id: str) -> None:
    """Show what the inquiry captured, with a way to answer it again."""
    if st.session_state.get(_RETAKE_KEY):
        st.caption("Update your answers — everything stays optional.")
        insight_inquiry.render_insight_inquiry(
            supabase, user_id, mode="edit",
            on_complete=lambda: st.session_state.pop(_RETAKE_KEY, None),
        )
        if st.button("Cancel", key="cancel_retake"):
            st.session_state.pop(_RETAKE_KEY, None)
            st.session_state.pop("inquiry_step", None)
            st.rerun()
        return

    responses = insight_inquiry.load_inquiry_responses(supabase, user_id)
    answered = {
        q["key"]: responses.get(q["key"], {})
        for q in insight_inquiry.INQUIRY_QUESTIONS
    }
    has_content = any(
        a.get("text") or a.get("categories") for a in answered.values()
    ) or (responses.get("_priorities") or {}).get("top")

    if not has_content:
        st.info("You haven't answered the insight questions yet. They tell Mirra "
                "what to look for in your reflections.")
    else:
        priorities = responses.get("_priorities") or {}
        if priorities.get("top"):
            with st.container(border=True):
                st.markdown("**Focusing on right now**")
                st.markdown(" · ".join(priorities["top"]))
                st.caption(f"For the next {priorities.get('period', '1 month')}.")

        for question in insight_inquiry.INQUIRY_QUESTIONS:
            answer = answered.get(question["key"], {})
            if not (answer.get("text") or answer.get("categories")):
                continue
            with st.container(border=True):
                st.markdown(f"**{question['prompt']}**")
                if answer.get("categories"):
                    st.markdown(" · ".join(answer["categories"]))
                if answer.get("text"):
                    st.caption(answer["text"])

    label = "Answer the questions" if not has_content else "Retake the questions"
    if st.button(label, type="primary", key="retake_inquiry"):
        insight_inquiry.seed_widget_state(responses)
        st.session_state[_RETAKE_KEY] = True
        st.session_state.pop("inquiry_step", None)
        st.rerun()


# ── Account ───────────────────────────────────────────────────────────────────
def _render_account_section(supabase, user_id: str) -> None:
    with st.container(border=True):
        st.markdown("**Account**")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Username", value=st.session_state.get("username", ""),
                          disabled=True, key="account_username",
                          help="Usernames can't be changed yet — ping us if you need one changed.")
        with col2:
            since = _member_since(supabase, user_id)
            st.text_input("Member since", value=since or "—", disabled=True,
                          key="account_member_since")

    with st.container(border=True):
        st.markdown("**Change password**")
        with st.form("change_password_form", border=False):
            current = st.text_input("Current password", type="password", key="pw_current")
            col1, col2 = st.columns(2)
            with col1:
                new = st.text_input("New password", type="password", key="pw_new")
            with col2:
                confirm = st.text_input("Confirm new password", type="password", key="pw_confirm")
            submitted = st.form_submit_button("Update password", use_container_width=True)
        if submitted:
            ok, message = auth.change_password(supabase, user_id, current, new, confirm)
            if ok:
                st.success(message)
            else:
                st.error(message)

    with st.expander("Revisit the welcome intro"):
        render_intro_page(supabase, user_id, show_cta=False)

    with st.container(border=True):
        st.markdown("**Your data**")
        st.caption("Your reflections and biometrics are yours. Mirra never shares "
                   "them with advertisers or third parties. Export and delete "
                   "controls are coming — ask us and we'll do it by hand meanwhile.")

    if st.button("Sign out", key="profile_sign_out"):
        auth.sign_out()
