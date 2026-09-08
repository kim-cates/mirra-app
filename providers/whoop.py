"""
MIR-3 · Whoop provider — third connector.

Full cycle now: authorization-code handshake, identity `validate()`, and a real
`sync()` that pulls recovery / sleep / cycle collections and rolls them up into
one normalized row per local day in `whoop_daily`.

Data signal: Whoop's headline numbers are *recovery* (recovery score, HRV, resting
HR) and *sleep performance*, plus day strain from the cycle. That is exactly the
"recovery / stress" axis the data-source map (docs/plans/data-sources-map.md) says
Oura also feeds, so the two are directly comparable per day.

Day attribution — the part worth knowing before reading the code:
  * Whoop timestamps are UTC, but every sleep and cycle record carries its own
    `timezone_offset` ("-05:00"), so a day is computed from the member's own
    offset rather than a single app-wide timezone (Oura/Spotify assume one).
  * A sleep is attributed to the day it **ends** — you wake up on the day the
    reflection is written about. Naps (`nap: true`) are counted, not merged.
  * A recovery has no offset of its own but carries `sleep_id`; it inherits the
    day of that sleep, falling back to its own `created_at` if the sleep fell
    outside the window.
  * A cycle is attributed to the day it **starts** (strain accumulates forward).

Whoop API refs (v2 — v1 was retired; base path changed and sleep ids became UUIDs):
    authorize:  https://api.prod.whoop.com/oauth/oauth2/auth
    token:      https://api.prod.whoop.com/oauth/oauth2/token   (creds in body)
    api base:   https://api.prod.whoop.com/developer/v2
    identity:   /user/profile/basic                              (scope read:profile)
    collections: /recovery, /activity/sleep, /cycle   — paged, `limit` <= 25,
                 `next_token` for the following page.

Note: Whoop only returns a refresh token when the `offline` scope is requested.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

import requests

from .base import (
    OAuthProvider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderMeta,
    TokenBundle,
)
from .registry import register

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"
REQUEST_TIMEOUT = 15

PAGE_LIMIT = 25        # vendor maximum
MAX_PAGES = 20         # backstop: 20 * 25 records covers far more than days_back

# Fallback only — used when a record carries no `timezone_offset` of its own.
DEFAULT_USER_TZ = "Pacific/Honolulu"


def _token_request(data: dict) -> TokenBundle:
    resp = requests.post(WHOOP_TOKEN_URL, data=data, timeout=REQUEST_TIMEOUT)
    if resp.status_code in (400, 401):
        raise ProviderAuthError(f"Whoop token request rejected: {resp.text[:200]}")
    if resp.status_code == 429:
        raise ProviderRateLimitError("Whoop rate limit (429). Back off and retry.")
    if not resp.ok:
        raise ProviderError(f"Whoop {resp.status_code}: {resp.text[:200]}")
    return TokenBundle.from_oauth_response(resp.json(),
                                          fallback_refresh=data.get("refresh_token"))


# ── Day attribution helpers (pure) ────────────────────────────────────────────
def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse a Whoop ISO-8601 UTC timestamp. Returns None on anything unusable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_day(ts: Optional[str], tz_offset: Optional[str],
               tz_name: str = DEFAULT_USER_TZ) -> Optional[str]:
    """
    ISO date of `ts` in the member's own timezone.

    `tz_offset` is Whoop's per-record offset ("-05:00"). When it is missing or
    malformed we fall back to the app-wide timezone, which keeps the row on a
    plausible day instead of dropping it.
    """
    dt = _parse_ts(ts)
    if dt is None:
        return None
    if tz_offset:
        try:
            sign = -1 if tz_offset.startswith("-") else 1
            digits = tz_offset.lstrip("+-").replace(":", "")     # "-05:00" and "-0500"
            delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
            return (dt.astimezone(timezone.utc) + sign * delta).date().isoformat()
        except (ValueError, TypeError):
            pass
    return dt.astimezone(ZoneInfo(tz_name)).date().isoformat()


def _scored(record: dict) -> Optional[dict]:
    """The `score` object of a record, or None unless Whoop finished scoring it."""
    if record.get("score_state") != "SCORED":
        return None
    score = record.get("score")
    return score if isinstance(score, dict) else None


def aggregate_whoop_daily(recoveries: list[dict], sleeps: list[dict],
                          cycles: list[dict],
                          tz_name: str = DEFAULT_USER_TZ) -> dict[str, dict]:
    """
    Roll Whoop's three collections into {entry_date -> row dict for whoop_daily}.

    Pure and offline: everything the tests care about lives here. Unscored records
    contribute their day (so the row exists) but no metrics; a day with several
    main sleeps keeps the longest one and counts the rest of the naps.
    """
    days: dict[str, dict] = {}
    raw: dict[str, dict] = {}

    def _day(entry_date: str) -> dict:
        raw.setdefault(entry_date, {})
        return days.setdefault(entry_date, {"entry_date": entry_date})

    # ── Sleep: longest non-nap sleep wins the day; naps are counted separately ──
    sleep_day_by_id: dict[str, str] = {}
    best_in_bed: dict[str, int] = {}
    for rec in sleeps:
        day = _local_day(rec.get("end"), rec.get("timezone_offset"), tz_name)
        if day is None:
            continue
        if rec.get("id") is not None:
            sleep_day_by_id[str(rec["id"])] = day
        row = _day(day)

        if rec.get("nap"):
            row["nap_count"] = (row.get("nap_count") or 0) + 1
            raw.setdefault(day, {}).setdefault("naps", []).append(rec)
            continue

        row.setdefault("nap_count", 0)
        score = _scored(rec)
        if score is None:
            continue
        stages = score.get("stage_summary") or {}
        in_bed = stages.get("total_in_bed_time_milli") or 0
        if day in best_in_bed and in_bed <= best_in_bed[day]:
            continue
        best_in_bed[day] = in_bed

        row.update({
            "sleep_performance_percentage": score.get("sleep_performance_percentage"),
            "sleep_efficiency_percentage": score.get("sleep_efficiency_percentage"),
            "sleep_consistency_percentage": score.get("sleep_consistency_percentage"),
            "respiratory_rate": score.get("respiratory_rate"),
            "total_in_bed_time_milli": stages.get("total_in_bed_time_milli"),
            "total_awake_time_milli": stages.get("total_awake_time_milli"),
            "total_light_sleep_time_milli": stages.get("total_light_sleep_time_milli"),
            "total_slow_wave_sleep_time_milli": stages.get("total_slow_wave_sleep_time_milli"),
            "total_rem_sleep_time_milli": stages.get("total_rem_sleep_time_milli"),
            "sleep_cycle_count": stages.get("sleep_cycle_count"),
            "disturbance_count": stages.get("disturbance_count"),
        })
        raw[day]["sleep"] = rec

    # ── Recovery: inherits its sleep's day, else its own created_at ────────────
    for rec in recoveries:
        sleep_id = rec.get("sleep_id")
        day = sleep_day_by_id.get(str(sleep_id)) if sleep_id is not None else None
        if day is None:
            day = _local_day(rec.get("created_at"), None, tz_name)
        if day is None:
            continue
        row = _day(day)
        score = _scored(rec)
        if score is None:
            continue
        row.update({
            "recovery_score": score.get("recovery_score"),
            "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
            "resting_heart_rate": score.get("resting_heart_rate"),
            "spo2_percentage": score.get("spo2_percentage"),
            "skin_temp_celsius": score.get("skin_temp_celsius"),
        })
        raw[day]["recovery"] = rec

    # ── Cycle: day strain, attributed to the day the cycle starts ─────────────
    for rec in cycles:
        day = _local_day(rec.get("start"), rec.get("timezone_offset"), tz_name)
        if day is None:
            continue
        row = _day(day)
        score = _scored(rec)
        if score is None:
            continue
        # Several cycles can touch one day; the highest-strain one is the day's.
        if row.get("strain") is not None and (score.get("strain") or 0) <= row["strain"]:
            continue
        row.update({
            "strain": score.get("strain"),
            "kilojoule": score.get("kilojoule"),
            "average_heart_rate": score.get("average_heart_rate"),
            "max_heart_rate": score.get("max_heart_rate"),
        })
        raw[day]["cycle"] = rec

    for day, row in days.items():
        row["raw"] = raw.get(day, {})
    return days


@register
class WhoopProvider(OAuthProvider):
    meta = ProviderMeta(
        key="whoop",
        label="Whoop",
        # `offline` is required for a refresh token; `read:profile` backs
        # validate(); the rest map to the daily summaries sync() pulls.
        default_scopes=("offline read:profile read:recovery read:sleep "
                        "read:cycles read:workout"),
        color="#000000",
        icon="🟢",
        supports_pat=False,
        docs_url="https://developer.whoop.com/",
    )

    def authorize_url(self, *, state: str, scopes: Optional[str] = None) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": scopes or self.meta.default_scopes,
            "state": state,
        }
        return f"{WHOOP_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str) -> TokenBundle:
        return _token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        })

    def refresh(self, *, refresh_token: str) -> TokenBundle:
        return _token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": "offline",
        })

    def validate(self, *, access_token: str) -> dict:
        resp = requests.get(
            f"{WHOOP_API_BASE}/user/profile/basic",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ProviderAuthError("Whoop token rejected (401). Reconnect required.")
        if not resp.ok:
            raise ProviderError(f"Whoop profile {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # ── sync ─────────────────────────────────────────────────────────────────
    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """Pull recovery/sleep/cycle for the window and upsert into `whoop_daily`."""
        start = (datetime.now(timezone.utc) - timedelta(days=days_back))
        params = {"start": start.isoformat().replace("+00:00", "Z")}

        sleeps = self._collection("/activity/sleep", access_token, params)
        recoveries = self._collection("/recovery", access_token, params)
        cycles = self._collection("/cycle", access_token, params)

        by_day = aggregate_whoop_daily(recoveries, sleeps, cycles)

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for rec in by_day.values():
            rec["user_id"] = user_id
            rec["fetched_at"] = now
            rows.append(rec)

        if rows:
            supabase.table("whoop_daily").upsert(
                rows, on_conflict="user_id,entry_date").execute()
        return len(rows)

    def _collection(self, path: str, access_token: str,
                    params: dict[str, Any]) -> list[dict]:
        """Follow `next_token` through a paged Whoop collection."""
        records: list[dict] = []
        next_token: Optional[str] = None
        for _ in range(MAX_PAGES):
            page_params = dict(params, limit=PAGE_LIMIT)
            if next_token:
                page_params["nextToken"] = next_token
            resp = requests.get(
                f"{WHOOP_API_BASE}{path}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=page_params,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 401:
                raise ProviderAuthError("Whoop token rejected (401). Reconnect required.")
            if resp.status_code == 429:
                raise ProviderRateLimitError("Whoop rate limit (429). Back off and retry.")
            if not resp.ok:
                raise ProviderError(f"Whoop {path} {resp.status_code}: {resp.text[:200]}")
            payload = resp.json()
            records.extend(payload.get("records") or [])
            next_token = payload.get("next_token")
            if not next_token:
                break
        return records
