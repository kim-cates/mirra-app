"""
MIR-3 · Token storage + refresh scheduler — issue #27.

Generalizes the single-provider `oura_credentials` table into a multi-provider
`connections` table keyed on (user_id, provider). Tokens are encrypted at rest
via `providers.crypto`. `get_valid_token()` is the generalized descendant of
`oura.get_valid_token()`: it transparently refreshes an expiring OAuth token
through the provider object and persists the new bundle — "refresh happens
automatically on expiry without user action".

⚠ NOT WIRED ON THIS BRANCH. The `connections` table doesn't exist yet and this
module intentionally does not run against the live DB. The DDL (and the open
identity question — auth.users vs public.users, see migrations.sql) is drafted
in docs/MIR-3_oauth_framework.md and must be applied via the Supabase SQL editor
before any of this is imported by the app. Written now so #27's shape is
reviewable alongside the interface.

There is a deliberate zero-downtime migration path: `_TABLE` can point at the
legacy `oura_credentials` for Oura-only reads while the new table is populated
(see design doc, "Migration").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .base import (
    AuthType,
    ConnectionState,
    OAuthProvider,
    ProviderAuthError,
    TokenBundle,
)
from . import crypto

_TABLE = "connections"  # proposed multi-provider table (see design doc)


@dataclass(frozen=True)
class StoredConnection:
    user_id: str
    provider: str
    access_token: str            # decrypted for use by the caller
    refresh_token: Optional[str]
    token_expires_at: Optional[datetime]
    auth_type: AuthType
    scopes: Optional[str] = None

    def as_bundle(self) -> TokenBundle:
        return TokenBundle(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=self.token_expires_at,
            scopes=self.scopes,
        )


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Reads ─────────────────────────────────────────────────────────────────────
def load_connection(supabase, user_id: str, provider: str, *,
                    enc_key: str) -> Optional[StoredConnection]:
    """Load and decrypt one connection, or None if the user hasn't connected it."""
    res = (supabase.table(_TABLE).select("*")
           .eq("user_id", user_id).eq("provider", provider).execute())
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    return StoredConnection(
        user_id=user_id,
        provider=provider,
        access_token=crypto.decrypt(row["access_token"], enc_key),
        refresh_token=crypto.decrypt(row.get("refresh_token"), enc_key),
        token_expires_at=_parse_ts(row.get("token_expires_at")),
        auth_type=AuthType(row.get("auth_type", "oauth")),
        scopes=row.get("scopes"),
    )


# ── Writes ────────────────────────────────────────────────────────────────────
def save_oauth(supabase, user_id: str, provider: str, bundle: TokenBundle, *,
               enc_key: str) -> None:
    """Upsert an OAuth connection, encrypting tokens at rest."""
    supabase.table(_TABLE).upsert({
        "user_id": user_id,
        "provider": provider,
        "access_token": crypto.encrypt(bundle.access_token, enc_key),
        "refresh_token": crypto.encrypt(bundle.refresh_token, enc_key),
        "token_expires_at": bundle.expires_at.isoformat() if bundle.expires_at else None,
        "auth_type": AuthType.OAUTH.value,
        "scopes": bundle.scopes,
        "status": ConnectionState.CONNECTED.value,
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "last_refresh_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,provider").execute()


def save_pat(supabase, user_id: str, provider: str, token: str, *,
             enc_key: str) -> None:
    """Upsert a PAT connection (Oura single-user path)."""
    supabase.table(_TABLE).upsert({
        "user_id": user_id,
        "provider": provider,
        "access_token": crypto.encrypt(token, enc_key),
        "refresh_token": None,
        "token_expires_at": None,
        "auth_type": AuthType.PAT.value,
        "status": ConnectionState.CONNECTED.value,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,provider").execute()


def mark_needs_reauth(supabase, user_id: str, provider: str) -> None:
    """Flag a connection so the Connections page shows 'Needs reauth'."""
    supabase.table(_TABLE).update({"status": ConnectionState.NEEDS_REAUTH.value}) \
        .eq("user_id", user_id).eq("provider", provider).execute()


def delete_connection(supabase, user_id: str, provider: str) -> None:
    """One-click disconnect — drop the stored credential."""
    supabase.table(_TABLE).delete() \
        .eq("user_id", user_id).eq("provider", provider).execute()


# ── The scheduler seam: a valid token, refreshed on demand ────────────────────
def get_valid_token(supabase, provider_obj: OAuthProvider, user_id: str, *,
                    enc_key: str) -> Optional[str]:
    """
    Return a usable access token for (user, provider), refreshing if within the
    expiry skew. Generalized form of `oura.get_valid_token`.

    Returns None if the user hasn't connected this provider. Raises
    ProviderAuthError (after flagging status) if a refresh is required but fails —
    the caller surfaces this as "Needs reauth".
    """
    conn = load_connection(supabase, user_id, provider_obj.key, enc_key=enc_key)
    if conn is None:
        return None

    if conn.auth_type == AuthType.PAT:
        return conn.access_token

    if not conn.as_bundle().needs_refresh():
        return conn.access_token

    if not conn.refresh_token:
        mark_needs_reauth(supabase, user_id, provider_obj.key)
        raise ProviderAuthError(f"{provider_obj.meta.label}: no refresh token — reconnect.")

    try:
        new_bundle = provider_obj.refresh(refresh_token=conn.refresh_token)
    except ProviderAuthError:
        mark_needs_reauth(supabase, user_id, provider_obj.key)
        raise
    save_oauth(supabase, user_id, provider_obj.key, new_bundle, enc_key=enc_key)
    return new_bundle.access_token


def connection_state(supabase, user_id: str, provider: str) -> ConnectionState:
    """
    Cheap status lookup for the Connections page (no token decryption).
    Reads the persisted `status` column; absent row ⇒ NOT_CONNECTED.
    """
    res = (supabase.table(_TABLE).select("status")
           .eq("user_id", user_id).eq("provider", provider).execute())
    rows = res.data or []
    if not rows:
        return ConnectionState.NOT_CONNECTED
    return ConnectionState(rows[0].get("status") or ConnectionState.CONNECTED.value)
