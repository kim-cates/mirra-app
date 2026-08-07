"""
MIR-3 · Spotify provider — issue #28 (second provider, proves the abstraction).

The OAuth handshake is implemented for real (standard authorization-code flow
with Basic-auth token endpoint). `sync()` is a documented skeleton: the data
model — per-day aggregates of audio features (valence / energy / tempo) over
recently-played tracks, per the product spec — is sketched but not wired, since
this branch does not touch the DB and Spotify client credentials aren't
provisioned yet.

Spotify OAuth refs:
    authorize:  https://accounts.spotify.com/authorize
    token:      https://accounts.spotify.com/api/token   (HTTP Basic client auth)
    identity:   https://api.spotify.com/v1/me
"""
from __future__ import annotations

from typing import Optional
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

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
REQUEST_TIMEOUT = 15


def _raise_for_token_resp(resp: requests.Response) -> None:
    if resp.status_code in (400, 401):
        raise ProviderAuthError(f"Spotify token request rejected: {resp.text[:200]}")
    if resp.status_code == 429:
        raise ProviderRateLimitError("Spotify rate limit (429). Back off and retry.")
    if not resp.ok:
        raise ProviderError(f"Spotify {resp.status_code}: {resp.text[:200]}")


@register
class SpotifyProvider(OAuthProvider):
    meta = ProviderMeta(
        key="spotify",
        label="Spotify",
        # Recently-played + top tracks drive the valence/energy/tempo signal.
        default_scopes="user-read-recently-played user-top-read",
        color="#1DB954",
        icon="🎵",
        supports_pat=False,
        docs_url="https://developer.spotify.com/dashboard",
    )

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

    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """
        SKELETON — not wired (no DB on this branch, #27/#28 follow-up).

        Planned pipeline:
          1. GET /me/player/recently-played?limit=50 (cursor back `days_back` days)
          2. Collect unique track ids → GET /audio-features?ids=… (batched ≤100)
          3. Group by local calendar day → mean(valence), mean(energy), mean(tempo),
             track_count → one row per (user_id, entry_date) in `spotify_daily`.
          4. upsert on (user_id, entry_date), mirroring the Oura row pattern.

        The `spotify_daily` table + RLS are drafted in docs/MIR-3_oauth_framework.md
        and must be applied via the Supabase SQL editor before this is enabled.
        """
        raise NotImplementedError(
            "Spotify.sync() is a skeleton — enable after spotify_daily migration (#28)."
        )
