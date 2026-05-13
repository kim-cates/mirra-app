"""
Oura Ring API client for Mirra.

Supports two auth modes:
  - PAT  (Personal Access Token, single-user, no expiry)
  - OAuth2 (multi-user, refresh token flow)

Data model: one row per (user_id, entry_date) in `oura_daily`.
Credentials stored in `oura_credentials`.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

try:
    # Python 3.9+ — preferred
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

import requests

# ── Constants ─────────────────────────────────────────────────────────────────
OURA_API_BASE = "https://api.ouraring.com/v2/usercollection"
OURA_AUTH_BASE = "https://cloud.ouraring.com"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"

# Scopes you'll typically want. `personal` is needed for /personal_info,
# the rest map to the daily summary endpoints.
DEFAULT_SCOPES = "personal daily heartrate workout session spo2 ring_configuration"

REQUEST_TIMEOUT = 15  # seconds

# ── User timezone ─────────────────────────────────────────────────────────────
# Server (Streamlit Cloud, most hosts) typically runs in UTC, so date.today()
# can be a full day ahead of the user. Oura tags sleep sessions by the user's
# local day, so we must compute "today" in the user's timezone — not the
# server's — for everything user-facing (display, fallback, throttle keys).
#
# TODO: store this per-user. For now it's a single default since Mirra is
# single-tenant. If you ever multi-tenant, add a `timezone` column to `users`
# and thread it through.
DEFAULT_USER_TZ = "Pacific/Honolulu"


def user_today(tz_name: str = DEFAULT_USER_TZ) -> date:
    """Today's date in the user's local timezone, not the server's."""
    return datetime.now(ZoneInfo(tz_name)).date()


# ── Errors ────────────────────────────────────────────────────────────────────
class OuraError(Exception):
    """Base class for Oura API errors."""


class OuraAuthError(OuraError):
    """Token is invalid, expired, or refresh failed. Caller should re-auth."""


class OuraRateLimitError(OuraError):
    """429 from Oura. Caller should back off."""


# ── Low-level request helper ──────────────────────────────────────────────────
def _get(path: str, token: str, params: Optional[dict] = None) -> dict:
    """GET an Oura endpoint, raising typed errors."""
    url = f"{OURA_API_BASE}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params=params or {}, timeout=REQUEST_TIMEOUT)

    if resp.status_code == 401:
        raise OuraAuthError("Oura token rejected (401). Reconnect required.")
    if resp.status_code == 429:
        raise OuraRateLimitError("Oura rate limit hit (429). Back off and retry.")
    if not resp.ok:
        raise OuraError(f"Oura {resp.status_code}: {resp.text[:200]}")

    return resp.json()


# ── OAuth flow ────────────────────────────────────────────────────────────────
def build_oauth_authorize_url(client_id: str, redirect_uri: str,
                              state: str, scopes: str = DEFAULT_SCOPES) -> str:
    """
    Step 1 of OAuth: build the URL the user clicks to authorize.

    `state` should be a random nonce you store in session and verify on callback.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    }
    return f"{OURA_AUTH_BASE}/oauth/authorize?{urlencode(params)}"


def exchange_code_for_token(code: str, client_id: str, client_secret: str,
                            redirect_uri: str) -> dict:
    """
    Step 2 of OAuth: exchange the `code` from the callback for tokens.

    Returns the full token payload, including:
      - access_token
      - refresh_token
      - expires_in (seconds)
      - token_type
    """
    resp = requests.post(
        OURA_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise OuraAuthError(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """Refresh an expired OAuth access token. Returns the new token payload."""
    resp = requests.post(
        OURA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise OuraAuthError(f"Refresh failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


# ── Credential management (Supabase-backed) ───────────────────────────────────
def get_valid_token(supabase, user_id: str,
                    client_id: Optional[str] = None,
                    client_secret: Optional[str] = None) -> Optional[str]:
    """
    Return a usable access token for this user, refreshing if needed.
    Returns None if the user has no Oura credentials.

    For PAT users: returns the stored token directly.
    For OAuth users: refreshes if within 5 min of expiry, persists new tokens.
    """
    res = supabase.table("oura_credentials").select("*").eq("user_id", user_id).execute()
    rows = res.data or []
    if not rows:
        return None
    cred = rows[0]

    if cred["auth_type"] == "pat":
        return cred["access_token"]

    # OAuth path — check expiry
    if not (client_id and client_secret):
        raise OuraError("OAuth client credentials required to refresh token.")

    expires_at = cred.get("token_expires_at")
    needs_refresh = True
    if expires_at:
        # Parse ISO timestamp; treat as UTC
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        # Refresh if less than 5 minutes left
        needs_refresh = exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=5)

    if not needs_refresh:
        return cred["access_token"]

    # Refresh
    new_tok = refresh_access_token(cred["refresh_token"], client_id, client_secret)
    new_expiry = datetime.now(timezone.utc) + timedelta(seconds=new_tok["expires_in"])
    supabase.table("oura_credentials").update({
        "access_token": new_tok["access_token"],
        "refresh_token": new_tok.get("refresh_token", cred["refresh_token"]),
        "token_expires_at": new_expiry.isoformat(),
    }).eq("user_id", user_id).execute()
    return new_tok["access_token"]


def save_pat_credentials(supabase, user_id: str, token: str) -> None:
    supabase.table("oura_credentials").upsert({
        "user_id": user_id,
        "access_token": token,
        "refresh_token": None,
        "token_expires_at": None,
        "auth_type": "pat",
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id").execute()


def save_oauth_credentials(supabase, user_id: str, token_payload: dict) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_payload["expires_in"])
    supabase.table("oura_credentials").upsert({
        "user_id": user_id,
        "access_token": token_payload["access_token"],
        "refresh_token": token_payload["refresh_token"],
        "token_expires_at": expires_at.isoformat(),
        "auth_type": "oauth",
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id").execute()


def disconnect(supabase, user_id: str) -> None:
    supabase.table("oura_credentials").delete().eq("user_id", user_id).execute()


# ── Data fetching ─────────────────────────────────────────────────────────────
def _safe_first(data_list: list, key: str = None):
    """Return first item from a list-of-dicts, or None."""
    if not data_list:
        return None
    return data_list[0]


def fetch_oura_range(token: str, start: date, end: date) -> dict[str, dict]:
    """
    Fetch all summaries between start and end (inclusive).

    Returns: dict mapping ISO date string -> flat row dict ready for Supabase upsert.
    Each row contains scalar columns + a `raw` jsonb blob with the original payloads.

    Doing this as a range fetch (not per-day) is ~4x fewer API calls.
    """
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}

    # One API call per endpoint, covering the whole range
    sleep_resp     = _get("daily_sleep", token, params)
    readiness_resp = _get("daily_readiness", token, params)
    activity_resp  = _get("daily_activity", token, params)
    detailed_resp  = _get("sleep", token, params)  # detailed sleep periods

    # Index by date
    by_date: dict[str, dict] = {}

    def _ensure(d: str) -> dict:
        if d not in by_date:
            by_date[d] = {"entry_date": d, "raw": {}}
        return by_date[d]

    for item in sleep_resp.get("data", []):
        d = item.get("day")
        if not d:
            continue
        row = _ensure(d)
        row["sleep_score"] = item.get("score")
        row["raw"]["daily_sleep"] = item

    for item in readiness_resp.get("data", []):
        d = item.get("day")
        if not d:
            continue
        row = _ensure(d)
        row["readiness_score"] = item.get("score")
        row["raw"]["daily_readiness"] = item

    for item in activity_resp.get("data", []):
        d = item.get("day")
        if not d:
            continue
        row = _ensure(d)
        row["activity_score"] = item.get("score")
        row["steps"] = item.get("steps")
        row["raw"]["daily_activity"] = item

    # Detailed sleep: there can be multiple periods per day (naps + main sleep).
    # We attribute each period to the LOCAL DATE THE USER WOKE UP, not Oura's
    # `day` field. Oura's `/sleep` tags the day containing the most of the
    # session, so a pre-midnight bedtime puts the whole night under yesterday —
    # but `/daily_sleep` (the score) uses wake-up date. Aligning to wake-up date
    # keeps duration on the same row as the score.
    #
    # `bedtime_end` is ISO-8601 with offset; parsing keeps the source offset, but
    # `.date()` on that returns the calendar date in the source offset — which
    # for cloud hosts is usually UTC. We need the user's *local* wake-up date,
    # so convert to the configured tz first. Otherwise an early-morning wake-up
    # in a UTC-behind timezone (e.g. HST) can land a day late in the row map.
    user_tz = ZoneInfo(DEFAULT_USER_TZ)
    sleep_by_day: dict[str, list[dict]] = {}
    for item in detailed_resp.get("data", []):
        wake_iso = item.get("bedtime_end")
        if wake_iso:
            try:
                wake_dt = datetime.fromisoformat(wake_iso.replace("Z", "+00:00"))
                d = wake_dt.astimezone(user_tz).date().isoformat()
            except ValueError:
                d = item.get("day")
        else:
            d = item.get("day")
        if not d:
            continue
        # Skip pure-nap periods (type='nap') so they don't inflate sleep totals.
        if item.get("type") == "nap":
            continue
        sleep_by_day.setdefault(d, []).append(item)

    for d, periods in sleep_by_day.items():
        # Total sleep = sum across all periods attributed to this wake-up day
        # (handles cases where Oura splits one night into multiple records).
        total = sum((p.get("total_sleep_duration") or 0) for p in periods)
        # HRV / resting HR / stage durations come from the longest period only —
        # averaging across short awakenings would distort them.
        main = max(periods, key=lambda s: s.get("total_sleep_duration") or 0)
        row = _ensure(d)
        row["total_sleep_seconds"] = total or None
        # Convenience duplicates of total in hours, and stage breakdowns in
        # minutes. Stage durations come from Oura in seconds.
        row["sleep_hours"] = round(total / 3600, 2) if total else None
        deep_s = main.get("deep_sleep_duration")
        rem_s = main.get("rem_sleep_duration")
        row["deep_sleep_min"] = round(deep_s / 60) if deep_s is not None else None
        row["rem_sleep_min"] = round(rem_s / 60) if rem_s is not None else None
        row["hrv_avg"] = main.get("average_hrv")
        row["resting_hr"] = main.get("lowest_heart_rate")
        row["raw"]["sleep"] = main

    return by_date


def sync_oura(supabase, user_id: str, token: str, days_back: int = 7) -> int:
    """
    Fetch the last N days of Oura data and upsert to Supabase.
    Returns the number of days written.

    "Today" is computed in the user's local timezone, not the server's, so
    we ask Oura for the right calendar days regardless of where the app runs.
    """
    today = user_today()
    start = today - timedelta(days=days_back - 1)
    by_date = fetch_oura_range(token, start, today)

    rows = []
    for d, payload in by_date.items():
        payload["user_id"] = user_id
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
        rows.append(payload)

    if rows:
        supabase.table("oura_daily").upsert(rows, on_conflict="user_id,entry_date").execute()
    return len(rows)


def validate_token(token: str) -> dict:
    """
    Check a token works by calling /personal_info.
    Returns the user info dict on success, raises OuraAuthError on failure.
    """
    try:
        return _get("personal_info", token)
    except OuraAuthError:
        raise
    except OuraError as e:
        raise OuraAuthError(f"Token validation failed: {e}")


# ── Convenience: load Oura data for a user ───────────────────────────────────
def load_oura_for_user(supabase, user_id: str) -> dict[str, dict]:
    """Returns dict mapping entry_date string -> oura_daily row."""
    res = supabase.table("oura_daily").select("*").eq("user_id", user_id).execute()
    return {r["entry_date"]: r for r in (res.data or [])}


def _row_is_complete(row: Optional[dict]) -> bool:
    """True iff the row has all the metrics we display. Activity is the laggard."""
    if not row:
        return False
    return all(
        row.get(k) is not None
        for k in ("sleep_score", "readiness_score", "activity_score")
    )


def auto_sync_if_stale(supabase, user_id: str,
                       client_id: Optional[str] = None,
                       client_secret: Optional[str] = None,
                       min_interval_seconds: int = 900) -> bool:
    """
    Sync the last 2 days from Oura if today's row is missing/incomplete AND we
    haven't synced in the last `min_interval_seconds` (default 15 min).

    Returns True if a sync ran, False otherwise. Silent on failure — this is
    a background-style refresh, not a user-initiated action.
    """
    # Throttle: check most recent fetched_at across this user's rows
    today_iso = user_today().isoformat()
    yesterday_iso = (user_today() - timedelta(days=1)).isoformat()

    res = (supabase.table("oura_daily")
           .select("entry_date,sleep_score,readiness_score,activity_score,fetched_at")
           .eq("user_id", user_id)
           .in_("entry_date", [today_iso, yesterday_iso])
           .execute())
    rows = {r["entry_date"]: r for r in (res.data or [])}
    today_row = rows.get(today_iso)

    # If today is already complete, nothing to do.
    if _row_is_complete(today_row):
        return False

    # Throttle on the most recent fetched_at we've seen for either day
    last_fetch = None
    for r in rows.values():
        ts = r.get("fetched_at")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if last_fetch is None or dt > last_fetch:
                    last_fetch = dt
            except ValueError:
                pass
    if last_fetch and (datetime.now(timezone.utc) - last_fetch).total_seconds() < min_interval_seconds:
        return False

    try:
        token = get_valid_token(supabase, user_id, client_id, client_secret)
        if not token:
            return False
        sync_oura(supabase, user_id, token, days_back=2)
        return True
    except OuraError:
        # Don't surface errors here — page will just render with stale data.
        return False


# Metrics surfaced in the Today view. Each one prefers today's value, then
# falls back to yesterday if today is missing. The UI labels which day the
# value came from via `_source_by_metric` so users see honest provenance
# rather than a silently-stale number.
#
# Sleep metrics and readiness usually post within a few hours of wake-up,
# but on a slow-sync morning yesterday's number is more useful than a blank.
# Activity accumulates through the day and its final score lands late, so
# yesterday's score is the right at-a-glance default until today's lands.
# Resting HR comes from the prior night's sleep period — by definition
# "yesterday's" once today's sleep is processed.
_FALLBACKABLE_METRICS = (
    "sleep_score",
    "readiness_score",
    "activity_score",
    "steps",
    "hrv_avg",
    "resting_hr",
    "total_sleep_seconds",
)


def build_today_view(oura_by_date: dict[str, dict]) -> Optional[dict]:
    """
    Merge today's and yesterday's Oura rows into one view, taking today's value
    for each metric where available and falling back to yesterday otherwise.

    Returns None if neither day has any data. Otherwise returns a dict with the
    same shape as an oura_daily row, plus a `_source_by_metric` field mapping
    each metric name to either "today" or "yesterday" so the UI can label it.
    """
    today_iso = user_today().isoformat()
    yesterday_iso = (user_today() - timedelta(days=1)).isoformat()
    today_row = oura_by_date.get(today_iso) or {}
    yesterday_row = oura_by_date.get(yesterday_iso) or {}

    if not today_row and not yesterday_row:
        return None

    merged: dict = {"entry_date": today_iso}
    sources: dict[str, str] = {}
    for m in _FALLBACKABLE_METRICS:
        if today_row.get(m) is not None:
            merged[m] = today_row[m]
            sources[m] = "today"
        elif yesterday_row.get(m) is not None:
            merged[m] = yesterday_row[m]
            sources[m] = "yesterday"
    merged["_source_by_metric"] = sources
    return merged