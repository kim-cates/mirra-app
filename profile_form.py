"""Profile form — expanded user profile fields (MIR-1, sub-issues #16 / #18).

Renders the MIR-1 fields in two logical groups (per the story's acceptance
criteria): **Contact** (email, phone, location, timezone) and **About You**
(date of birth, sex, gender identity, occupation). All fields are optional —
nothing here blocks account creation. Inline validation uses the pure
helpers from validation.py (#17).

Storage: the `users` table (see the MIR-1 block in migrations.sql). Values
live in the profile columns; `users.profile_completed_at` is the marker that
tells the onboarding chain the user is past this screen — without it, every
sign-in would replay onboarding, because all fields being optional means
"done" can't be inferred from the data itself.

If the migration hasn't been applied to a given Supabase project yet, reads
and writes degrade to session state so the flow still works — but the UI
says so instead of pretending the save was durable.

The same form serves both onboarding (mode="create") and the Profile tab
(mode="edit", #18).
"""

import zoneinfo
from datetime import date, datetime, timezone as _tz

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

PROFILE_COLUMNS = [f for fields in PROFILE_GROUPS.values() for f in fields]

_STATE_KEY = "profile_values"
_SEEDED_KEY = "profile_widgets_seeded"


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


# ── Storage ───────────────────────────────────────────────────────────────────
def load_profile(supabase, user_id: str) -> dict:
    """Read the user's saved profile columns. {} pre-migration or on error."""
    if supabase is None:
        return dict(st.session_state.get(_STATE_KEY) or {})
    try:
        res = (supabase.table("users")
               .select(",".join(PROFILE_COLUMNS))
               .eq("id", user_id).limit(1).execute())
        if res.data:
            return {k: v for k, v in res.data[0].items() if v}
    except Exception:
        pass  # pre-migration — fall back to whatever this session holds
    return dict(st.session_state.get(_STATE_KEY) or {})


def user_has_completed_profile(supabase, user_id: str) -> bool:
    """True once the user saved (or skipped) the onboarding profile.

    Reads users.profile_completed_at; falls back to session state while the
    column doesn't exist yet, so the flow still works pre-migration.
    """
    if st.session_state.get(_STATE_KEY) is not None:
        return True
    if supabase is not None:
        try:
            res = (supabase.table("users").select("profile_completed_at")
                   .eq("id", user_id).limit(1).execute())
            if res.data and res.data[0].get("profile_completed_at"):
                st.session_state[_STATE_KEY] = {}
                return True
        except Exception:
            pass  # column not migrated yet — session gate only
    return False


def save_profile(supabase, user_id: str, values: dict) -> tuple[bool, str]:
    """Persist profile values + the completion marker.

    Returns (persisted_to_db, message). A False means the values are only in
    session state (migration not applied, or the write was rejected) — the
    caller surfaces that instead of claiming a durable save.
    """
    st.session_state[_STATE_KEY] = values
    if supabase is None:
        return False, "No database connection — saved for this session only."

    # Blank out cleared fields explicitly: collect_profile() drops empty
    # values, so without this a field the user erased would keep its old
    # value in the database.
    payload = {col: values.get(col) for col in PROFILE_COLUMNS}
    payload["profile_completed_at"] = datetime.now(_tz.utc).isoformat()
    try:
        supabase.table("users").update(payload).eq("id", user_id).execute()
        return True, ""
    except Exception as exc:
        detail = str(exc)
        if "idx_users_email" in detail or "duplicate key" in detail or "23505" in detail:
            return False, "That email is already used by another account."
        # PostgREST reports unknown columns as PGRST204 ("could not find the
        # 'x' column ... in the schema cache"); Postgres itself as 42703.
        if "PGRST204" in detail or "42703" in detail or "schema cache" in detail:
            return False, ("Saved for this session only — the profile columns "
                           "aren't in this database yet (see migrations.sql).")
        return False, "Couldn't reach the database — saved for this session only."


def mark_profile_completed(supabase, user_id: str) -> None:
    """Record that the user passed the onboarding profile screen (e.g. skipped)."""
    st.session_state.setdefault(_STATE_KEY, {})
    if supabase is None:
        return
    try:
        supabase.table("users").update(
            {"profile_completed_at": datetime.now(_tz.utc).isoformat()}
        ).eq("id", user_id).execute()
    except Exception:
        pass  # pre-migration — session marker above keeps the gate closed


def seed_widget_state(supabase, user_id: str, force: bool = False) -> None:
    """Prefill the form widgets from the saved profile, once per session.

    Streamlit widgets keep their value in session_state under their key, so
    seeding has to happen before the widgets are created — otherwise the edit
    form would open empty for a returning user.
    """
    if st.session_state.get(_SEEDED_KEY) and not force:
        return
    profile = load_profile(supabase, user_id)
    st.session_state[_SEEDED_KEY] = True

    st.session_state.setdefault("profile_email", profile.get("email") or "")
    st.session_state.setdefault("profile_phone", profile.get("phone") or "")
    st.session_state.setdefault("profile_location", profile.get("location") or "")
    st.session_state.setdefault("profile_timezone", profile.get("timezone") or DEFAULT_TIMEZONE)
    st.session_state.setdefault("profile_gender_identity", profile.get("gender_identity") or "")
    st.session_state.setdefault("profile_occupation", profile.get("occupation") or "")

    sex = profile.get("sex")
    st.session_state.setdefault("profile_sex", sex if sex in SEX_OPTIONS else SEX_OPTIONS[0])

    dob = profile.get("date_of_birth")
    if isinstance(dob, str):
        try:
            dob = date.fromisoformat(dob)
        except ValueError:
            dob = None
    st.session_state.setdefault("profile_date_of_birth", dob if isinstance(dob, date) else None)


# ── Renderer ──────────────────────────────────────────────────────────────────
def render_profile_form(supabase, user_id: str, mode: str = "create") -> None:
    """Render the grouped profile form. mode: "create" | "edit" (#18)."""
    seed_widget_state(supabase, user_id)

    if mode == "create":
        st.markdown("### A little about you")
        st.caption("All of this is optional — fill in what you're comfortable with. "
                   "You can add or change everything later in your Profile tab.")
    else:
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
            st.date_input("Date of birth", key="profile_date_of_birth",
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

    if mode == "edit":
        if st.button("Save changes", type="primary", use_container_width=True):
            if errors:
                st.error("Please fix the highlighted fields before saving.")
            else:
                ok, message = save_profile(supabase, user_id, collect_profile())
                if ok:
                    st.success("Profile saved.")
                else:
                    st.warning(message)
        return

    # Onboarding: saving continues the chain, and skipping still closes the
    # gate — a returning user must never be trapped behind an optional form.
    save_col, skip_col = st.columns([3, 1])
    with save_col:
        if st.button("Continue", type="primary", use_container_width=True):
            if errors:
                st.error("Please fix the highlighted fields before saving.")
            else:
                ok, message = save_profile(supabase, user_id, collect_profile())
                if not ok:
                    st.warning(message)
                st.rerun()
    with skip_col:
        if st.button("Skip for now", use_container_width=True):
            mark_profile_completed(supabase, user_id)
            st.rerun()
