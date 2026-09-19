"""
MIR-3 · Strava provider — fifth connector.

Why Strava next: registering a developer app needs nothing but a free Strava
account — no device, no membership (unlike Whoop) and no pending shared-mailbox
step (unlike Fitbit) — so it is the first connector that can go live end-to-end
today. It also covers the "workouts / training load" column of
docs/plans/data-sources-map.md that the sleep-first vendors only graze.

Signals pulled, one row per calendar day in `strava_daily`:
    activities  /api/v3/athlete/activities?after&before   scope: activity:read_all

A day's row is a rollup of every activity that STARTED that day (athlete-local
`start_date_local`, so no timezone math on our side): count, moving/elapsed
minutes, distance, elevation, Relative Effort (`suffer_score`), plus the heart
rate of the day's main (longest) activity.

`raw` keeps a TRIMMED copy of each activity: name, sport, durations, HR,
effort. The map polyline and start/end GPS coordinates are deliberately
dropped — routes are home-address-grade location data and nothing in Mirra
needs them (HIPAA-grade rule in CLAUDE.md).

Strava OAuth refs (https://developers.strava.com/docs/authentication/):
    authorize:   https://www.strava.com/oauth/authorize
    token:       https://www.strava.com/oauth/token      (creds in the body, no Basic)
    deauthorize: https://www.strava.com/oauth/deauthorize
    identity:    https://www.strava.com/api/v3/athlete

Vendor quirks worth knowing:
  * scopes are COMMA-delimited (`read,activity:read_all`), not space-delimited.
  * the consent screen lets the athlete UNTICK "private activities"
    (activity:read_all -> activity:read). That is not an error: sync still
    works, it just skips private activities. The granted scope arrives in the
    callback query string, not in the token response, so TokenBundle.scopes is
    None here.
  * access tokens live 6 hours; refresh responses carry a refresh_token that
    may rotate — always store the returned one (fallback_refresh covers the
    rare omission).
  * the app registration form wants a bare "Authorization Callback Domain"
    (host only); the full OAUTH_REDIRECT_URI is passed at authorize time.
"""
from __future__ import annotations

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

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_DEAUTH_URL = "https://www.strava.com/oauth/deauthorize"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
REQUEST_TIMEOUT = 15

MAX_DAYS_BACK = 90     # activities is a cheap list endpoint; 90 days is plenty
PER_PAGE = 200         # Strava's per_page ceiling
MAX_PAGES = 5          # 1000 activities per window — a runaway-loop backstop

# What survives into `raw`. No `map`, no `start_latlng`/`end_latlng` — see the
# module docstring.
_RAW_KEEP = (
    "id", "name", "sport_type", "type", "start_date_local",
    "moving_time", "elapsed_time", "distance", "total_elevation_gain",
    "average_heartrate", "max_heartrate", "suffer_score", "kilojoules",
    "trainer", "commute", "manual",
)


def _trim(activity: dict) -> dict:
    return {k: activity[k] for k in _RAW_KEEP if k in activity}


def aggregate_strava_daily(activities: list[dict]) -> dict[str, dict]:
    """
    Roll a list of Strava SummaryActivity dicts into
    {entry_date -> row dict for `strava_daily`}.

    Pure and offline. An activity lands on the athlete-local day it started.
    Sums (minutes, distance, elevation) treat a missing field as 0; nullable
    extras (suffer_score, kilojoules) stay NULL when no activity has them.
    Heart rate comes from the day's main activity — the one with the longest
    moving time — because averaging averages across a run and a stroll says
    nothing.
    """
    by_day: dict[str, list[dict]] = {}
    for act in activities:
        day = str(act.get("start_date_local") or "")[:10]
        if len(day) != 10:
            continue
        by_day.setdefault(day, []).append(act)

    def _sum_present(acts: list[dict], key: str) -> Optional[float]:
        vals = [act[key] for act in acts if act.get(key) is not None]
        return sum(vals) if vals else None

    days: dict[str, dict] = {}
    for day, acts in by_day.items():
        main = max(acts, key=lambda a: a.get("moving_time") or 0)
        sports: list[str] = []
        for act in acts:
            sport = act.get("sport_type") or act.get("type")
            if sport and sport not in sports:
                sports.append(sport)

        moving_s = sum(int(act.get("moving_time") or 0) for act in acts)
        elapsed_s = sum(int(act.get("elapsed_time") or 0) for act in acts)
        distance_m = sum(float(act.get("distance") or 0.0) for act in acts)
        elevation_m = sum(float(act.get("total_elevation_gain") or 0.0) for act in acts)

        days[day] = {
            "entry_date": day,
            "activity_count": len(acts),
            "moving_minutes": round(moving_s / 60),
            "elapsed_minutes": round(elapsed_s / 60),
            "distance_km": round(distance_m / 1000, 2),
            "elevation_gain_m": round(elevation_m, 1),
            "relative_effort": _sum_present(acts, "suffer_score"),
            "kilojoules": _sum_present(acts, "kilojoules"),
            "main_sport_type": main.get("sport_type") or main.get("type"),
            "sport_types": ",".join(sports) if sports else None,
            "average_heartrate": main.get("average_heartrate"),
            "max_heartrate": main.get("max_heartrate"),
            "raw": {"activities": [_trim(act) for act in acts]},
        }
    return days


@register
class StravaProvider(OAuthProvider):
    meta = ProviderMeta(
        key="strava",
        label="Strava",
        default_scopes="read,activity:read_all",   # comma-delimited (Strava quirk)
        color="#FC4C02",
        icon="🏃",
        supports_pat=False,
        docs_url="https://developers.strava.com/docs/getting-started/",
    )

    # ── OAuth handshake ──────────────────────────────────────────────────────
    def authorize_url(self, *, state: str, scopes: Optional[str] = None) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": scopes or self.meta.default_scopes,
            "state": state,
            "approval_prompt": "auto",
        }
        return f"{STRAVA_AUTH_URL}?{urlencode(params)}"

    def _token_request(self, data: dict,
                       fallback_refresh: Optional[str] = None) -> TokenBundle:
        # Strava wants client credentials in the form body, not HTTP Basic.
        resp = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                **data,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code in (400, 401):
            raise ProviderAuthError(f"Strava token request rejected: {resp.text[:200]}")
        if resp.status_code == 429:
            raise ProviderRateLimitError("Strava rate limit (429). Back off and retry.")
        if not resp.ok:
            raise ProviderError(f"Strava {resp.status_code}: {resp.text[:200]}")
        return TokenBundle.from_oauth_response(resp.json(),
                                               fallback_refresh=fallback_refresh)

    def exchange_code(self, *, code: str) -> TokenBundle:
        # The exchange response also carries the athlete object (kept in raw).
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
        })

    def refresh(self, *, refresh_token: str) -> TokenBundle:
        return self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, fallback_refresh=refresh_token)

    def revoke(self, *, access_token: str,
               refresh_token: Optional[str] = None) -> None:
        """Best-effort deauthorize on disconnect; failures are not the user's problem."""
        try:
            requests.post(
                STRAVA_DEAUTH_URL,
                data={"access_token": access_token},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            return None

    # ── Identity ─────────────────────────────────────────────────────────────
    def validate(self, *, access_token: str) -> dict:
        return self._get("/athlete", access_token)

    # ── Data sync ────────────────────────────────────────────────────────────
    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """Pull the window's activities and upsert daily rollups into `strava_daily`."""
        window = min(max(days_back, 1), MAX_DAYS_BACK)
        # `after` filters on UTC start time while rows key on the athlete-local
        # day, so an activity started late on the window's edge day (UTC) can
        # fall out — acceptable for a rolling sync that re-covers the window.
        after = int((datetime.now(timezone.utc) - timedelta(days=window)).timestamp())

        activities: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            batch = self._get("/athlete/activities", access_token,
                              params={"after": after, "per_page": PER_PAGE,
                                      "page": page})
            if not isinstance(batch, list) or not batch:
                break
            activities.extend(batch)
            if len(batch) < PER_PAGE:
                break

        by_day = aggregate_strava_daily(activities)

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for rec in by_day.values():
            rec["user_id"] = user_id
            rec["fetched_at"] = now
            rows.append(rec)

        if rows:
            supabase.table("strava_daily").upsert(
                rows, on_conflict="user_id,entry_date").execute()
        return len(rows)

    def _get(self, path: str, access_token: str,
             params: Optional[dict[str, Any]] = None) -> Any:
        resp = requests.get(
            f"{STRAVA_API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ProviderAuthError("Strava token rejected (401). Reconnect required.")
        if resp.status_code == 429:
            raise ProviderRateLimitError(
                "Strava rate limit (429) — default app allowance is 100 read "
                "requests per 15 minutes. Retry later.")
        if not resp.ok:
            raise ProviderError(f"Strava {path} {resp.status_code}: {resp.text[:200]}")
        return resp.json()
