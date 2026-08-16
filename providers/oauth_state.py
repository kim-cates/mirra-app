"""
MIR-3 · Persistent OAuth `state` store (CSRF nonces).

Why this exists: Streamlit's `st.session_state` does NOT survive a full-page
redirect out to the vendor and back — the callback arrives on a fresh session,
so a nonce stashed in session is gone and every legitimate connection is
rejected with "state did not match". (Found the hard way during the first live
Spotify connect; the repo's existing `oura_oauth_states` table shows the Oura
flow hit the same wall.)

So the nonce is persisted server-side, keyed by the random value itself:

    issue()   → mint nonce, store (nonce, provider, user_id, created_at)
    consume() → look it up, delete it, return whether it was valid

Properties that make this a real CSRF defence rather than theatre:
  - **single use** — the row is deleted on consume, so a replayed callback fails
  - **expiring** — rows older than TTL are rejected and swept
  - **bound to the user and provider** it was issued for

Table `oauth_states` (same shape as the existing oura_oauth_states):
    state text primary key, provider text, user_id uuid, created_at timestamptz
"""
from __future__ import annotations

import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

_TABLE = "oauth_states"
DEFAULT_TTL_SECONDS = 600  # 10 min — plenty for a consent screen, short for an attacker


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def issue(db, *, provider: str, user_id: str) -> str:
    """Mint a nonce, persist it, and return it for the authorize URL."""
    nonce = _secrets.token_urlsafe(24)
    db.table(_TABLE).upsert({
        "state": nonce,
        "provider": provider,
        "user_id": user_id,
        "created_at": _now().isoformat(),
    }, on_conflict="state").execute()
    return nonce


def consume(db, *, nonce: str, provider: str,
            ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[str]:
    """
    Validate and burn a nonce. Returns the `user_id` it was issued for, or None
    if unknown / expired / for a different provider. Always deletes the row it
    found, so a nonce can never be reused.
    """
    res = db.table(_TABLE).select("*").eq("state", nonce).execute()
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    db.table(_TABLE).delete().eq("state", nonce).execute()  # single use

    if row.get("provider") != provider:
        return None
    created = _parse(row.get("created_at"))
    if created is None or _now() - created > timedelta(seconds=ttl_seconds):
        return None
    return row.get("user_id")


def sweep(db, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
    """Delete expired nonces. Cheap to call opportunistically; returns count."""
    res = db.table(_TABLE).select("*").execute()
    stale = [r for r in (res.data or [])
             if (c := _parse(r.get("created_at"))) is None
             or _now() - c > timedelta(seconds=ttl_seconds)]
    for r in stale:
        db.table(_TABLE).delete().eq("state", r["state"]).execute()
    return len(stale)
