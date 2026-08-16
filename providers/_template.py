"""
MIR-3 · Provider TEMPLATE — copy this to add a new integration.

This file is a starting point, NOT a live provider: the leading underscore means
`providers/__init__.py` does not import it, so it never registers. To add, e.g.,
Strava:

  1. Copy:      cp providers/_template.py providers/strava.py
  2. Rename:    _TemplateProvider → StravaProvider, fill in ProviderMeta + URLs.
  3. Register:  uncomment `@register`.
  4. Wire:      add `from . import strava as _strava` to providers/__init__.py.
  5. Secrets:   add STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET (+ shared OAUTH_REDIRECT_URI).
  6. Data:      implement sync() and add a `strava_daily` table migration
                (mirror oura_daily; apply via Supabase SQL editor + migrations.sql).

That's the whole "adding an integration = a config change". The core — registry,
token encryption/refresh, Connections UI, CSRF callback — is untouched.
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
# from .registry import register   # ← uncomment on the real provider

# TODO: fill these in from the vendor's OAuth docs.
AUTH_URL = "https://example.com/oauth/authorize"
TOKEN_URL = "https://example.com/oauth/token"
API_BASE = "https://api.example.com/v1"
REQUEST_TIMEOUT = 15


# @register   # ← uncomment on the real provider
class _TemplateProvider(OAuthProvider):
    meta = ProviderMeta(
        key="template",                       # TODO: unique key, e.g. "strava"
        label="Template",                     # TODO: display name
        default_scopes="read",                # TODO: vendor scopes
        color="#888888",                      # TODO: brand color
        icon="🔗",                            # TODO: emoji/icon
        supports_pat=False,
        docs_url="",                          # where to register a client app
    )

    def authorize_url(self, *, state: str, scopes: Optional[str] = None) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": scopes or self.meta.default_scopes,
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str) -> TokenBundle:
        # Many vendors use HTTP Basic client auth; some want creds in the body.
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            },
            auth=(self.config.client_id, self.config.client_secret),
            timeout=REQUEST_TIMEOUT,
        )
        self._raise_for_token(resp)
        return TokenBundle.from_oauth_response(resp.json())

    def refresh(self, *, refresh_token: str) -> TokenBundle:
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(self.config.client_id, self.config.client_secret),
            timeout=REQUEST_TIMEOUT,
        )
        self._raise_for_token(resp)
        return TokenBundle.from_oauth_response(resp.json(), fallback_refresh=refresh_token)

    def validate(self, *, access_token: str) -> dict:
        resp = requests.get(
            f"{API_BASE}/me",                 # TODO: vendor identity endpoint
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise ProviderAuthError(f"{self.meta.label} token rejected (401).")
        if not resp.ok:
            raise ProviderError(f"{self.meta.label} {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        # TODO: pull the vendor API over the window, map to one row per
        # (user_id, entry_date) in `<key>_daily`, upsert. Mirror providers/oura.py
        # once #26 lands, or the Spotify sync plan in the design doc.
        raise NotImplementedError(f"{self.meta.label}.sync() not implemented yet.")

    @staticmethod
    def _raise_for_token(resp: requests.Response) -> None:
        if resp.status_code in (400, 401):
            raise ProviderAuthError(f"Token request rejected: {resp.text[:200]}")
        if resp.status_code == 429:
            raise ProviderRateLimitError("Rate limit (429). Back off and retry.")
        if not resp.ok:
            raise ProviderError(f"{resp.status_code}: {resp.text[:200]}")
