"""
MIR-3 · Fitbit provider — fourth connector.

Why Fitbit next: after Oura and Whoop it is the third device people in the test
group actually own, and unlike Apple Watch or Android it has a real server-side
Web API, so it fits this framework without a mobile app (see
docs/plans/data-sources-map.md).

Signals pulled, one row per calendar day in `fitbit_daily`:
    sleep      /1.2/user/-/sleep/date/{start}/{end}.json      scope: sleep
    resting HR /1/user/-/activities/heart/date/{start}/{end}  scope: heartrate
    HRV        /1/user/-/hrv/date/{start}/{end}.json          scope: heartrate
    steps      /1/user/-/activities/steps/date/{start}/{end}  scope: activity

Deliberately not requested: `oxygen_saturation`, `respiratory_rate`,
`temperature`. Each is another consent checkbox for a signal Oura and Whoop
already provide, so they stay off until a real user asks for them.

Day attribution is simpler than Whoop's: every one of these endpoints is already
keyed by calendar date in the member's own timezone, and a sleep log carries
`dateOfSleep` (the day you wake). No timezone math on our side.

Fitbit OAuth refs:
    authorize:  https://www.fitbit.com/oauth2/authorize
    token:      https://api.fitbit.com/oauth2/token    (HTTP Basic client auth)
    revoke:     https://api.fitbit.com/oauth2/revoke
    identity:   https://api.fitbit.com/1/user/-/profile.json

Two vendor quirks worth knowing:
  * access tokens live 8 hours, and every refresh **rotates** the refresh token —
    the new one must be stored or the connection dies at the next refresh.
  * the HRV endpoint caps a request at 30 days, which is what clamps `days_back`.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from .base import (
    OAuthProvider,
    ProviderAuthError,
    ProviderError,
    ProviderMeta,
    ProviderRateLimitError,
    TokenBundle,
)
from .registry import register

FITBIT_AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"
FITBIT_REVOKE_URL = "https://api.fitbit.com/oauth2/revoke"
FITBIT_API_BASE = "https://api.fitbit.com"
REQUEST_TIMEOUT = 15

MAX_DAYS_BACK = 30      # the HRV endpoint's ceiling; the others allow more


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _minutes(summary: dict, stage: str) -> Optional[int]:
    """Minutes for one sleep stage, or None for classic (non-stages) logs."""
    entry = summary.get(stage)
    return entry.get("minutes") if isinstance(entry, dict) else None


def aggregate_fitbit_daily(sleep_logs: list[dict], heart: list[dict],
                           hrv: list[dict], steps: list[dict]) -> dict[str, dict]:
    """
    Roll Fitbit's four series into {entry_date -> row dict for `fitbit_daily`}.

    Pure and offline. The main sleep of a day wins its metrics; any further sleep
    logs that day are counted as naps. Classic sleep logs (no stage breakdown)
    still contribute duration and efficiency, with stage minutes left NULL.
    """
    days: dict[str, dict] = {}
    raw: dict[str, dict] = {}

    def _day(entry_date: str) -> dict:
        raw.setdefault(entry_date, {})
        return days.setdefault(entry_date, {"entry_date": entry_date})

    for log in sleep_logs:
        day = log.get("dateOfSleep")
        if not day:
            continue
        row = _day(day)
        row.setdefault("nap_count", 0)
        if not log.get("isMainSleep", False):
            row["nap_count"] += 1
            raw[day].setdefault("naps", []).append(log)
            continue

        summary = ((log.get("levels") or {}).get("summary")) or {}
        row.update({
            "minutes_asleep": log.get("minutesAsleep"),
            "minutes_awake": log.get("minutesAwake"),
            "time_in_bed_minutes": log.get("timeInBed"),
            "sleep_efficiency": log.get("efficiency"),
            "minutes_deep": _minutes(summary, "deep"),
            "minutes_light": _minutes(summary, "light"),
            "minutes_rem": _minutes(summary, "rem"),
            "minutes_wake": _minutes(summary, "wake"),
        })
        raw[day]["sleep"] = log

    for entry in heart:
        day = entry.get("dateTime")
        if not day:
            continue
        value = entry.get("value") or {}
        rhr = value.get("restingHeartRate")
        if rhr is None:
            continue                       # a day with zones but no RHR adds nothing
        _day(day)["resting_heart_rate"] = rhr
        raw[day]["heart"] = value

    for entry in hrv:
        day = entry.get("dateTime")
        if not day:
            continue
        value = entry.get("value") or {}
        row = _day(day)
        row["hrv_daily_rmssd"] = value.get("dailyRmssd")
        row["hrv_deep_rmssd"] = value.get("deepRmssd")
        raw[day]["hrv"] = value

    for entry in steps:
        day = entry.get("dateTime")
        if not day:
            continue
        try:
            count = int(entry.get("value"))    # the series returns strings
        except (TypeError, ValueError):
            continue
        _day(day)["steps"] = count

    for day, row in days.items():
        row["raw"] = raw.get(day, {})
    return days


@register
class FitbitProvider(OAuthProvider):
    meta = ProviderMeta(
        key="fitbit",
        label="Fitbit",
        default_scopes="sleep heartrate activity profile",
        color="#00B0B9",
        icon="⌚",
        supports_pat=False,
        docs_url="https://dev.fitbit.com/build/reference/web-api/",
    )

    # ── OAuth handshake ──────────────────────────────────────────────────────
    def authorize_url(self, *, state: str, scopes: Optional[str] = None) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": scopes or self.meta.default_scopes,
            "state": state,
        }
        return f"{FITBIT_AUTH_URL}?{urlencode(params)}"

    def _token_request(self, data: dict,
                       fallback_refresh: Optional[str] = None) -> TokenBundle:
        resp = requests.post(
            FITBIT_TOKEN_URL,
            data=data,
            headers={
                "Authorization": _basic_auth(self.config.client_id,
                                             self.config.client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code in (400, 401):
            raise ProviderAuthError(f"Fitbit token request rejected: {resp.text[:200]}")
        if resp.status_code == 429:
            raise ProviderRateLimitError("Fitbit rate limit (429). Back off and retry.")
        if not resp.ok:
            raise ProviderError(f"Fitbit {resp.status_code}: {resp.text[:200]}")
        return TokenBundle.from_oauth_response(resp.json(),
                                              fallback_refresh=fallback_refresh)

    def exchange_code(self, *, code: str) -> TokenBundle:
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
        })

    def refresh(self, *, refresh_token: str) -> TokenBundle:
        # Fitbit rotates the refresh token on every refresh; `fallback_refresh`
        # is only a safety net if a response ever omits it.
        return self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, fallback_refresh=refresh_token)

    def revoke(self, *, access_token: str,
               refresh_token: Optional[str] = None) -> None:
        """Best-effort revoke on disconnect; failures are not the user's problem."""
        try:
            requests.post(
                FITBIT_REVOKE_URL,
                data={"token": refresh_token or access_token},
                headers={"Authorization": _basic_auth(self.config.client_id,
                                                      self.config.client_secret)},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            return None

    # ── Identity ─────────────────────────────────────────────────────────────
    def validate(self, *, access_token: str) -> dict:
        return self._get("/1/user/-/profile.json", access_token)

    # ── Data sync ────────────────────────────────────────────────────────────
    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """Pull sleep / RHR / HRV / steps for the window into `fitbit_daily`."""
        window = min(max(days_back, 1), MAX_DAYS_BACK)
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=window)
        span = f"{start.isoformat()}/{end.isoformat()}"

        sleep_logs = self._get(f"/1.2/user/-/sleep/date/{span}.json",
                               access_token).get("sleep") or []
        heart = self._get(f"/1/user/-/activities/heart/date/{span}.json",
                          access_token).get("activities-heart") or []
        hrv = self._get(f"/1/user/-/hrv/date/{span}.json",
                        access_token).get("hrv") or []
        steps = self._get(f"/1/user/-/activities/steps/date/{span}.json",
                          access_token).get("activities-steps") or []

        by_day = aggregate_fitbit_daily(sleep_logs, heart, hrv, steps)

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for rec in by_day.values():
            rec["user_id"] = user_id
            rec["fetched_at"] = now
            rows.append(rec)

        if rows:
            supabase.table("fitbit_daily").upsert(
                rows, on_conflict="user_id,entry_date").execute()
        return len(rows)

    def _get(self, path: str, access_token: str,
             params: Optional[dict[str, Any]] = None) -> dict:
        resp = requests.get(
            f"{FITBIT_API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}",
                     "Accept-Language": "en_US"},   # metric-vs-imperial units
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ProviderAuthError("Fitbit token rejected (401). Reconnect required.")
        if resp.status_code == 429:
            raise ProviderRateLimitError(
                "Fitbit rate limit (429) — 150 requests/hour per user. Retry later.")
        if not resp.ok:
            raise ProviderError(f"Fitbit {path} {resp.status_code}: {resp.text[:200]}")
        return resp.json()
