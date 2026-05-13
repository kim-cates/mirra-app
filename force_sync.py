"""
One-off: force a fresh Oura sync for a user, bypassing the throttle.

Run from your project root:
    python force_sync.py

Edit USER_ID below before running.
"""
import streamlit as st
from supabase import create_client

import oura

# ─── EDIT THIS ──────────────────────────────────────────────────────────────
USER_ID = "dc7c7701-d24c-4c8a-8a51-f463e426a6b6"
# ────────────────────────────────────────────────────────────────────────────


def main():
    # Streamlit secrets only work inside `streamlit run`. For a plain script,
    # read from .streamlit/secrets.toml directly or set env vars.
    try:
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_KEY"]
        oura_client_id = st.secrets.get("OURA_CLIENT_ID")
        oura_client_secret = st.secrets.get("OURA_CLIENT_SECRET")
    except Exception:
        import os
        supabase_url = os.environ["SUPABASE_URL"]
        supabase_key = os.environ["SUPABASE_KEY"]
        oura_client_id = os.environ.get("OURA_CLIENT_ID")
        oura_client_secret = os.environ.get("OURA_CLIENT_SECRET")

    supabase = create_client(supabase_url, supabase_key)

    print(f"Fetching valid token for user {USER_ID}…")
    token = oura.get_valid_token(supabase, USER_ID, oura_client_id, oura_client_secret)
    if not token:
        print("✗ No Oura credentials found for this user. Connect Oura in Settings first.")
        return

    print("✓ Got token. Validating with /personal_info…")
    try:
        info = oura.validate_token(token)
        print(f"  Connected as Oura user: {info.get('email', '(no email)')}")
    except oura.OuraAuthError as e:
        print(f"✗ Token rejected: {e}")
        print("  → Reconnect Oura in Settings.")
        return

    print("Pulling last 3 days from Oura API…")
    try:
        written = oura.sync_oura(supabase, USER_ID, token, days_back=3)
        print(f"✓ Wrote {written} day(s) to Supabase.")
    except oura.OuraError as e:
        print(f"✗ Sync failed: {e}")
        return

    # Show what we actually got
    print("\nResulting rows:")
    res = (supabase.table("oura_daily")
           .select("entry_date,sleep_score,total_sleep_seconds,readiness_score,activity_score")
           .eq("user_id", USER_ID)
           .order("entry_date", desc=True)
           .limit(3)
           .execute())
    for r in res.data or []:
        sleep_h = r["total_sleep_seconds"] // 3600 if r["total_sleep_seconds"] else "—"
        sleep_m = (r["total_sleep_seconds"] % 3600) // 60 if r["total_sleep_seconds"] else ""
        print(f"  {r['entry_date']}: sleep={r['sleep_score']} ({sleep_h}h {sleep_m}m)  "
              f"readiness={r['readiness_score']}  activity={r['activity_score']}")


if __name__ == "__main__":
    main()
