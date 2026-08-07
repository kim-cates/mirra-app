"""
MIR-3 · Whoop provider — third connector (queued after Spotify).

Skeleton at the same fidelity as Spotify: real authorization-code handshake,
`sync()` left as a documented stub. Included now to stress-test the interface
with a *second OAuth-only vendor* — if Oura + Spotify + Whoop all fit
`OAuthProvider` without special-casing, the abstraction generalizes (the whole
point of issue #24).

Whoop OAuth refs (v2 developer platform):
    authorize:  https://api.prod.whoop.com/oauth/oauth2/auth
    token:      https://api.prod.whoop.com/oauth/oauth2/token   (creds in body)
    identity:   https://api.prod.whoop.com/developer/v1/user/profile/basic

Note: Whoop only returns a refresh token when the `offline` scope is requested.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

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
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v1"
REQUEST_TIMEOUT = 15


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


@register
class WhoopProvider(OAuthProvider):
    meta = ProviderMeta(
        key="whoop",
        label="Whoop",
        # `offline` is required for a refresh token; the rest map to daily summaries.
        default_scopes="offline read:recovery read:sleep read:cycles read:workout",
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

    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """
        SKELETON — not wired. Planned: pull /recovery, /activity/sleep, /cycle over
        the window, map recovery score / HRV / resting HR / sleep performance into
        one row per (user_id, entry_date) in `whoop_daily` (drafted in the design
        doc). Enable after that migration is applied.
        """
        raise NotImplementedError(
            "Whoop.sync() is a skeleton — enable after whoop_daily migration."
        )
