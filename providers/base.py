"""
MIR-3 · OAuth framework — core abstractions.

The whole point of this layer: **adding an integration is a config change**, and
connecting an account feels identical across providers (issue #24).

A concrete provider (Oura, Spotify, Whoop, …) subclasses `OAuthProvider` and
implements the handshake (authorize → exchange → refresh → revoke), a cheap
identity `validate()`, and a `sync()` that maps its own API into normalized rows.
Everything provider-agnostic — token bundles, expiry math, error taxonomy,
connection state — lives here so the UI and the token store never special-case a
vendor.

This module is pure Python: no Streamlit, no Supabase imports. That keeps
providers unit-testable and reusable outside the app shell.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────
class AuthType(str, Enum):
    """How a stored credential was obtained."""
    OAUTH = "oauth"   # authorization-code flow, refreshable
    PAT = "pat"       # personal access token, single-user, no expiry


class ConnectionState(str, Enum):
    """What the Connections page shows for a provider (issue #29)."""
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"
    NEEDS_REAUTH = "needs_reauth"   # token present but refresh failed / revoked


# ── Error taxonomy ────────────────────────────────────────────────────────────
# Providers raise these instead of leaking `requests` exceptions or raw callback
# dumps. The UI maps them to human-readable messages (AC: "Failed auth returns a
# human-readable error, not a stack trace").
class ProviderError(Exception):
    """Base class for all provider errors."""


class ProviderAuthError(ProviderError):
    """Token invalid/expired/revoked or refresh failed. Caller should re-auth."""


class ProviderRateLimitError(ProviderError):
    """429 from the vendor. Caller should back off and retry later."""


class ProviderConfigError(ProviderError):
    """Client credentials missing/malformed — a setup problem, not a user problem."""


# ── Value objects ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OAuthClientConfig:
    """
    Per-provider client credentials, injected at construction so providers stay
    decoupled from where secrets live (st.secrets, env, vault…).

    `redirect_uri` is the single app callback; the provider key is carried
    through OAuth `state`, so one redirect URI serves every provider.
    """
    client_id: str
    client_secret: str
    redirect_uri: str

    def require(self) -> "OAuthClientConfig":
        """Raise ProviderConfigError if anything is blank. Returns self for chaining."""
        missing = [n for n in ("client_id", "client_secret", "redirect_uri")
                   if not getattr(self, n)]
        if missing:
            raise ProviderConfigError(f"Missing OAuth config: {', '.join(missing)}")
        return self


@dataclass(frozen=True)
class ProviderMeta:
    """Static, display-and-routing metadata. Doubles as the registry key source."""
    key: str                       # stable id: "oura", "spotify", "whoop"
    label: str                     # human label: "Oura Ring"
    default_scopes: str            # space-delimited scopes requested by default
    color: str = "#3dab7a"         # brand accent for the Connections card
    icon: str = "🔗"               # emoji/placeholder until real assets land
    supports_pat: bool = False     # Oura=True; most vendors OAuth-only
    docs_url: str = ""             # where to get a client id/secret


@dataclass(frozen=True)
class TokenBundle:
    """
    Normalized token payload. Every provider's exchange/refresh returns one of
    these, so the token store and refresh scheduler never parse vendor JSON.
    """
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None      # tz-aware UTC; None ⇒ non-expiring (PAT)
    scopes: Optional[str] = None
    token_type: str = "Bearer"
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_oauth_response(cls, payload: dict, *,
                            fallback_refresh: Optional[str] = None) -> "TokenBundle":
        """
        Build from a standard OAuth2 token response.

        `expires_in` (seconds) is converted to an absolute UTC `expires_at` at
        parse time — storing an absolute instant avoids clock-skew bugs that
        creep in when you persist a relative TTL and compare later.

        `fallback_refresh` handles vendors that omit `refresh_token` on refresh
        (you keep reusing the original) — pass the previous refresh token.
        """
        expires_at = None
        if "expires_in" in payload:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload["expires_in"]))
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token") or fallback_refresh,
            expires_at=expires_at,
            scopes=payload.get("scope"),
            token_type=payload.get("token_type", "Bearer"),
            raw=payload,
        )

    def needs_refresh(self, skew_seconds: int = 300) -> bool:
        """
        True if the token is within `skew_seconds` of expiry (default 5 min).
        Non-expiring tokens (PAT) never need refresh.
        """
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)


# ── The interface every provider implements ──────────────────────────────────
class OAuthProvider(ABC):
    """
    Provider-agnostic OAuth + sync contract.

    Concrete subclasses set a class-level `meta: ProviderMeta` and are constructed
    with an `OAuthClientConfig`. The registry (`providers.registry`) discovers
    them by `meta.key`.

    Lifecycle (mirrors the acceptance criteria in issue #24):
        authorize_url()  → user consents on the vendor site
        exchange_code()  → code → TokenBundle           (callback handler)
        refresh()        → refresh_token → TokenBundle  (auto, on expiry)
        revoke()         → best-effort token invalidation (disconnect)
        validate()       → cheap identity ping, proves a token works
        sync()           → pull data into normalized rows (no regression vs today)
    """

    #: Set by every subclass. Declared here for type-checkers.
    meta: ProviderMeta

    def __init__(self, config: OAuthClientConfig):
        self.config = config

    # ── OAuth handshake ──────────────────────────────────────────────────────
    @abstractmethod
    def authorize_url(self, *, state: str, scopes: Optional[str] = None) -> str:
        """
        Step 1: URL the user clicks to authorize.

        `state` is a random nonce the caller stores in session and re-checks on
        callback (CSRF protection — AC in #24). It also carries the provider key
        so one callback route can fan out to the right provider.
        """

    @abstractmethod
    def exchange_code(self, *, code: str) -> TokenBundle:
        """Step 2: exchange the callback `code` for a TokenBundle."""

    @abstractmethod
    def refresh(self, *, refresh_token: str) -> TokenBundle:
        """Refresh an expired access token. Raises ProviderAuthError on failure."""

    def revoke(self, *, access_token: str, refresh_token: Optional[str] = None) -> None:
        """
        Best-effort revoke on disconnect. Default is a no-op for vendors without
        a revoke endpoint — the caller deletes the local credential regardless.
        Override where the vendor supports RFC 7009 token revocation.
        """
        return None

    # ── Identity / validation ────────────────────────────────────────────────
    @abstractmethod
    def validate(self, *, access_token: str) -> dict:
        """
        Cheap authenticated call proving the token works (e.g. Oura /personal_info,
        Spotify /me). Returns the identity payload; raises ProviderAuthError if
        the token is rejected.
        """

    # ── Data sync ────────────────────────────────────────────────────────────
    @abstractmethod
    def sync(self, *, supabase, user_id: str, access_token: str,
             days_back: int = 7) -> int:
        """
        Pull the last `days_back` days from the vendor and upsert normalized rows.
        Returns the number of rows written. This is the one method that stays
        vendor-shaped internally — it's where each "model" (per the architecture
        doc) maps a raw API into Mirra's schema.
        """

    # ── Convenience ──────────────────────────────────────────────────────────
    @property
    def key(self) -> str:
        return self.meta.key

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{type(self).__name__} key={self.meta.key!r}>"
