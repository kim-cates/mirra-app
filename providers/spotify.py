"""
MIR-3 · Spotify provider — issue #28 (second provider, proves the abstraction).

Full cycle implemented: authorization-code handshake (Basic-auth token endpoint),
identity `validate()`, and a real `sync()` that pulls recently-played tracks and
rolls them up into one normalized row per local day in `spotify_daily`.

Data signal — reality check: the founder spec wanted valence/energy/tempo, which
come from Spotify's `/audio-features`. Spotify **restricted `/audio-features` (and
`/audio-analysis`, recommendations) for apps created after 2024-11-27**. So the
reliable baseline here is *listening activity* (track_count, unique_artists,
listening_ms) from `/me/player/recently-played`, which needs only
`user-read-recently-played`. Audio features are fetched opportunistically and
degrade to NULL if the app lacks access — see `_fetch_audio_features`.

Caveat: `/me/player/recently-played` returns at most the last ~50 plays, so
`days_back` is a best-effort window, not a true backfill — meaningful history
comes from syncing regularly and accumulating rows.

Spotify OAuth refs:
    authorize:  https://accounts.spotify.com/authorize
    token:      https://accounts.spotify.com/api/token   (HTTP Basic client auth)
    identity:   https://api.spotify.com/v1/me
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
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
    ProviderMeta,
    ProviderRateLimitError,
    TokenBundle,
)
from .registry import register

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
REQUEST_TIMEOUT = 15
# `/me/player/recently-played` returns 50 items per call, so a multi-week
# backfill has to page. Spotify retains ~50 plays for most accounts, so this is
# an upper bound we rarely reach — it just stops a pathological loop.
MAX_HISTORY_PAGES = 10

# Attribute a play to the user's local calendar day (matches oura.py convention).
DEFAULT_USER_TZ = "Pacific/Honolulu"


def _played_at_ms(played_at: Optional[str]) -> Optional[int]:
    """`played_at` (ISO-8601 UTC) as epoch milliseconds, or None if unparseable."""
    if not played_at:
        return None
    try:
        dt = datetime.fromisoformat(played_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _raise_for_token_resp(resp: requests.Response) -> None:
    if resp.status_code in (400, 401):
        raise ProviderAuthError(f"Spotify token request rejected: {resp.text[:200]}")
    if resp.status_code == 429:
        raise ProviderRateLimitError("Spotify rate limit (429). Back off and retry.")
    if not resp.ok:
        raise ProviderError(f"Spotify {resp.status_code}: {resp.text[:200]}")


# ── Pure aggregation (unit-tested, no network) ────────────────────────────────
def aggregate_recently_played(items: list[dict],
                              tz_name: str = DEFAULT_USER_TZ,
                              features_by_id: Optional[dict[str, dict]] = None
                              ) -> dict[str, dict]:
    """
    Roll a `/me/player/recently-played` `items` list into per-local-day rows.

    Each item has `played_at` (ISO-8601 UTC) and a `track` object
    (`id`, `duration_ms`, `artists[].id`). Returns {entry_date -> row dict}.
    If `features_by_id` is given, adds mean valence/energy/tempo for that day's
    tracks; otherwise those keys are omitted (stored as NULL downstream).
    """
    tz = ZoneInfo(tz_name)
    acc: dict[str, dict] = {}
    for it in items:
        played_at = it.get("played_at")
        track = it.get("track") or {}
        if not played_at:
            continue
        try:
            dt = datetime.fromisoformat(played_at.replace("Z", "+00:00")).astimezone(tz)
        except ValueError:
            continue
        day = dt.date().isoformat()
        row = acc.setdefault(day, {"track_count": 0, "listening_ms": 0,
                                   "_track_ids": [], "_artist_ids": set()})
        row["track_count"] += 1
        row["listening_ms"] += track.get("duration_ms") or 0
        tid = track.get("id")
        if tid:
            row["_track_ids"].append(tid)
        for artist in track.get("artists") or []:
            if artist.get("id"):
                row["_artist_ids"].add(artist["id"])

    out: dict[str, dict] = {}
    for day, row in acc.items():
        rec = {
            "entry_date": day,
            "track_count": row["track_count"],
            "unique_artists": len(row["_artist_ids"]),
            "listening_ms": row["listening_ms"],
        }
        if features_by_id:
            feats = [features_by_id[t] for t in row["_track_ids"] if t in features_by_id]
            for key in ("valence", "energy", "tempo"):
                nums = [f[key] for f in feats if f.get(key) is not None]
                rec[key] = round(sum(nums) / len(nums), 4) if nums else None
        out[day] = rec
    return out


@register
class SpotifyProvider(OAuthProvider):
    meta = ProviderMeta(
        key="spotify",
        label="Spotify",
        default_scopes="user-read-recently-played user-top-read",
        color="#1DB954",
        icon="🎵",
        supports_pat=False,
        docs_url="https://developer.spotify.com/dashboard",
        data_table="spotify_daily",
    )

    # ── Handshake ────────────────────────────────────────────────────────────
    def authorize_url(self, *, state: str, scopes: Optional[str] = None) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": scopes or self.meta.default_scopes,
            "state": state,
        }
        return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str) -> TokenBundle:
        resp = requests.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            },
            auth=(self.config.client_id, self.config.client_secret),
            timeout=REQUEST_TIMEOUT,
        )
        _raise_for_token_resp(resp)
        return TokenBundle.from_oauth_response(resp.json())

    def refresh(self, *, refresh_token: str) -> TokenBundle:
        resp = requests.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(self.config.client_id, self.config.client_secret),
            timeout=REQUEST_TIMEOUT,
        )
        _raise_for_token_resp(resp)
        # Spotify frequently omits a new refresh_token — reuse the current one.
        return TokenBundle.from_oauth_response(resp.json(), fallback_refresh=refresh_token)

    def validate(self, *, access_token: str) -> dict:
        resp = requests.get(
            f"{SPOTIFY_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ProviderAuthError("Spotify token rejected (401). Reconnect required.")
        if not resp.ok:
            raise ProviderError(f"Spotify /me {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # ── Data sync ────────────────────────────────────────────────────────────
    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """Pull recently-played, roll up per day, upsert into spotify_daily."""
        items = self._fetch_recently_played(access_token, days_back)
        features = self._fetch_audio_features(access_token, items)  # None if unavailable
        by_day = aggregate_recently_played(items, DEFAULT_USER_TZ, features)

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for rec in by_day.values():
            rec["user_id"] = user_id
            rec["fetched_at"] = now
            rows.append(rec)

        if rows:
            supabase.table("spotify_daily").upsert(
                rows, on_conflict="user_id,entry_date").execute()
        return len(rows)

    def _fetch_recently_played(self, access_token: str, days_back: int,
                               *, max_pages: int = MAX_HISTORY_PAGES) -> list[dict]:
        """
        Every play inside the last `days_back` days that Spotify will still hand
        back, walking backwards with the `before` cursor.

        Paging matters for the "Sync last 30 days" button: one call caps at 50
        items, which for an active listener is barely two days. Spotify still
        only retains ~50 plays for most accounts, so the loop usually ends on the
        first empty page — it just no longer *guarantees* a two-day window.
        """
        cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp() * 1000)
        before = int(datetime.now(timezone.utc).timestamp() * 1000)

        items: list[dict] = []
        seen: set[tuple] = set()
        for _ in range(max_pages):
            payload = self._recently_played_page(access_token, before=before)
            page = payload.get("items") or []
            if not page:
                break

            oldest_ms = None
            hit_cutoff = False
            for it in page:
                played_ms = _played_at_ms(it.get("played_at"))
                if played_ms is None:
                    continue
                if played_ms < cutoff_ms:
                    hit_cutoff = True
                    continue
                oldest_ms = played_ms if oldest_ms is None else min(oldest_ms, played_ms)
                dedupe_key = (it.get("played_at"), (it.get("track") or {}).get("id"))
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                items.append(it)

            if hit_cutoff or oldest_ms is None:
                break
            # `cursors.before` is Spotify's own "give me the next older page"
            # timestamp; fall back to the oldest play we just saw.
            cursor = (payload.get("cursors") or {}).get("before")
            next_before = int(cursor) if cursor else oldest_ms
            if next_before >= before:   # no progress — stop rather than loop
                break
            before = next_before
        return items

    def _recently_played_page(self, access_token: str, *, before: int) -> dict:
        resp = requests.get(
            f"{SPOTIFY_API_BASE}/me/player/recently-played",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": 50, "before": before},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ProviderAuthError("Spotify token rejected (401). Reconnect required.")
        if resp.status_code == 403:
            raise ProviderAuthError(
                "Spotify refused the listening history (403). Reconnect to grant "
                "the `user-read-recently-played` scope."
            )
        if resp.status_code == 429:
            raise ProviderRateLimitError("Spotify rate limit (429). Back off and retry.")
        if not resp.ok:
            raise ProviderError(f"Spotify recently-played {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _fetch_audio_features(self, access_token: str,
                              items: list[dict]) -> Optional[dict[str, dict]]:
        """
        Best-effort audio features keyed by track id. Returns None (not an error)
        if the endpoint is unavailable to this app — Spotify locked it down for
        apps created after 2024-11-27, so valence/energy/tempo degrade to NULL.
        """
        ids = list({(it.get("track") or {}).get("id")
                    for it in items if (it.get("track") or {}).get("id")})
        if not ids:
            return None
        features: dict[str, dict] = {}
        for i in range(0, len(ids), 100):  # API caps at 100 ids per call
            resp = requests.get(
                f"{SPOTIFY_API_BASE}/audio-features",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"ids": ",".join(ids[i:i + 100])},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code in (401, 403, 404):
                return None  # not granted to this app — skip enrichment silently
            if not resp.ok:
                return None
            for feat in resp.json().get("audio_features") or []:
                if feat and feat.get("id"):
                    features[feat["id"]] = feat
        return features or None
