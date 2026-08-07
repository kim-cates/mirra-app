"""Profile form — expanded user profile fields (MIR-1, sub-issues #16 / #18).

Renders the MIR-1 fields in two logical groups (per the story's acceptance
criteria): **Contact** (email, phone, location, timezone) and **About You**
(date of birth, sex, gender identity, occupation). All fields are optional —
nothing here blocks account creation. Inline validation uses the pure
helpers from validation.py (#17).

Storage: values are collected into a plain dict and handed to
``save_profile``. Until the #15 migration is applied (waiting on Supabase
creds + the profiles-vs-users decision), the seam stores values in
``st.session_state`` — swapping in the Supabase upsert is the only change
needed later. The same form serves both the Create User page (mode="create")
and Profile Settings (mode="edit", #18).
"""

import zoneinfo
from datetime import date

import streamlit as st

from validation import normalize_email, normalize_phone, validate_email, validate_phone

DEFAULT_TIMEZONE = "Pacific/Honolulu"

SEX_OPTIONS = ["Prefer not to say", "Female", "Male", "Intersex"]

# Field groups (order defines display order). Rendering is driven by this
# config so adding a field never means touching the layout logic.
PROFILE_GROUPS = {
    "Contact": ["email", "phone", "location", "timezone"],
    "About You": ["date_of_birth", "sex", "gender_identity", "occupation"],
}

_STATE_KEY = "profile_values"


def _timezones() -> list[str]:
    zones = sorted(zoneinfo.available_timezones())
    # Keep the default first so the selectbox lands on it out of the box.
    zones.remove(DEFAULT_TIMEZONE)
    return [DEFAULT_TIMEZONE] + zones


def collect_profile() -> dict:
    """Read widget values → normalized profile dict (only non-empty values)."""
    dob = st.session_state.get("profile_date_of_birth")
    values = {
        "email": normalize_email(st.session_state.get("profile_email", "")),
        "phone": normalize_phone(st.session_state.get("profile_phone", "")),
        "location": (st.session_state.get("profile_location") or "").strip(),
        "timezone": st.session_state.get("profile_timezone", DEFAULT_TIMEZONE),
        "date_of_birth": dob.isoformat() if isinstance(dob, date) else None,
        "sex": st.session_state.get("profile_sex"),
        "gender_identity": (st.session_state.get("profile_gender_identity") or "").strip(),
        "occupation": (st.session_state.get("profile_occupation") or "").strip(),
    }
    if values["sex"] == "Prefer not to say":
        values["sex"] = None
    return {k: v for k, v in values.items() if v}


def validate_profile() -> dict[str, str]:
    """Validate current widget values → {field: error message} (empty = ok)."""
    errors = {}
    ok, err = validate_email(st.session_state.get("profile_email", ""))
    if not ok:
        errors["email"] = err
    ok, err = validate_phone(st.session_state.get("profile_phone", ""))
    if not ok:
        errors["phone"] = err
    return errors


def user_has_completed_profile(supabase, user_id: str) -> bool:
    """True once the user saved the onboarding profile.

    Reads users.profile_completed_at (#15 migration); falls back to session
    state while the column doesn't exist yet, so the flow works pre-migration.
    """
    if st.session_state.get(_STATE_KEY):
        return True
    if supabase is not None:
        try:
            res = (supabase.table("users").select("profile_completed_at")
                   .eq("id", user_id).limit(1).execute())
            if res.data and res.data[0].get("profile_completed_at"):
                st.session_state[_STATE_KEY] = {"from_db": True}
                return True
        except Exception:
            pass  # column not migrated yet — session gate only
    return False


def save_profile(supabase, user_id: str, values: dict) -> None:
    """Persist profile values to users (#15) with session fallback.

    Writes the profile columns + profile_completed_at. If the migration
    hasn't been applied yet the update fails silently and the session copy
    keeps the flow working.
    """
    if supabase is not None:
        try:
            from datetime import datetime, timezone as tz
            supabase.table("users").update(
                {**values, "profile_completed_at": datetime.now(tz.utc).isoformat()}
            ).eq("id", user_id).execute()
        except Exception:
            pass  # pre-migration — session fallback below
    st.session_state[_STATE_KEY] = values


def render_profile_form(supabase, user_id: str, mode: str = "create") -> None:
    """Render the grouped profile form. mode: "create" | "edit" (#18)."""
    if mode == "create":
        st.markdown("### A little about you")
        st.caption("All of this is optional — fill in what you're comfortable with. "
                   "You can add or change everything later in Profile Settings.")
    else:
        st.markdown("### Profile Settings")
        st.caption("Update your details anytime. All fields are optional.")

    errors = validate_profile()

    # ── Contact ──────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Contact**")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Email", key="profile_email", placeholder="you@example.com")
            if "email" in errors:
                st.markdown(f":red[{errors['email']}]")
        with col2:
            st.text_input("Phone", key="profile_phone", placeholder="+1 808 555 1234")
            if "phone" in errors:
                st.markdown(f":red[{errors['phone']}]")
        col3, col4 = st.columns(2)
        with col3:
            st.text_input("Location", key="profile_location", placeholder="Honolulu, HI")
        with col4:
            st.selectbox("Timezone", options=_timezones(), key="profile_timezone",
                         help="Used so 'today' matches your day, including Oura data.")

    # ── About You ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**About You**")
        col1, col2 = st.columns(2)
        with col1:
            st.date_input("Date of birth", key="profile_date_of_birth", value=None,
                          min_value=date(1900, 1, 1), max_value=date.today(),
                          format="MM/DD/YYYY")
        with col2:
            st.selectbox("Sex", options=SEX_OPTIONS, key="profile_sex")
        col3, col4 = st.columns(2)
        with col3:
            st.text_input("Gender identity", key="profile_gender_identity",
                          placeholder="In your own words (optional)")
        with col4:
            st.text_input("Occupation", key="profile_occupation",
                          placeholder="What do you do?")

    label = "Save profile" if mode == "edit" else "Continue"
    if st.button(label, type="primary", use_container_width=True):
        if errors:
            st.error("Please fix the highlighted fields before saving.")
        else:
            save_profile(supabase, user_id, collect_profile())
            st.success("Profile saved.")
            st.rerun()
