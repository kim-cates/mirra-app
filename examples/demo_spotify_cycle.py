"""
MIR-3 · End-to-end Spotify cycle demo — no real Spotify, no real DB.

Walks the whole framework the way the app will:

    connect  → authorize_url (CSRF state) → callback → exchange_code
    store    → tokens encrypted at rest (Fernet) in `connections`
    refresh  → token expired → get_valid_token() auto-refreshes + persists
    sync     → recently-played → per-day rows upserted into `spotify_daily`
    reauth   → refresh rejected → connection flagged NEEDS_REAUTH
    disconnect

Spotify's HTTP endpoints are mocked with `requests`-level stubs; Supabase is a
tiny in-memory fake with the same fluent API the code calls. Run:

    python3 examples/demo_spotify_cycle.py

This is a *reader's* demo for reviewing the design — it is not a test fixture
(tests live in tests/).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from providers import registry, token_store  # noqa: E402
from providers.base import ConnectionState, ProviderAuthError  # noqa: E402
from providers.token_store import get_valid_token  # noqa: E402

from cryptography.fernet import Fernet  # noqa: E402  (venv/requirements)


# ── Fake Supabase (just enough of the fluent API) ─────────────────────────────
class _Query:
    def __init__(self, table):
        self.t = table
        self.filters = []
        self.op = None
        self.payload = None
        self.on_conflict = None

    def select(self, *_):            self.op = "select"; return self
    def eq(self, k, v):              self.filters.append((k, v)); return self
    def upsert(self, rows, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", rows, on_conflict; return self
    def update(self, patch):         self.op, self.payload = "update", patch; return self
    def delete(self):                self.op = "delete"; return self

    def _match(self, row):
        return all(row.get(k) == v for k, v in self.filters)

    def execute(self):
        rows = self.t.rows
        if self.op == "select":
            return SimpleNamespace(data=[r for r in rows if self._match(r)])
        if self.op == "upsert":
            keys = tuple(self.on_conflict.split(","))
            for new in (self.payload if isinstance(self.payload, list) else [self.payload]):
                k = tuple(new[c] for c in keys)
                rows[:] = [r for r in rows if tuple(r[c] for c in keys) != k]
                rows.append(dict(new))
            return SimpleNamespace(data=self.payload)
        if self.op == "update":
            for r in rows:
                if self._match(r):
                    r.update(self.payload)
            return SimpleNamespace(data=None)
        if self.op == "delete":
            rows[:] = [r for r in rows if not self._match(r)]
            return SimpleNamespace(data=None)
        raise RuntimeError("no op")


class FakeTable:
    def __init__(self): self.rows = []


class FakeSupabase:
    def __init__(self): self._t = {}
    def table(self, name):
        return _Query(self._t.setdefault(name, FakeTable()))
    def dump(self, name):
        return self._t.get(name, FakeTable()).rows


# ── Fake Spotify HTTP ────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body
        self.ok = 200 <= status < 300
        self.text = str(body)
    def json(self): return self._b


STATE = {"refresh_should_fail": False, "refresh_calls": 0}
NOW = datetime.now(timezone.utc)


def _iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_post(url, data=None, auth=None, timeout=None, **_):
    assert url.endswith("/api/token"), url
    assert auth == ("demo-client-id", "demo-client-secret"), "client creds via HTTP Basic"
    if data["grant_type"] == "authorization_code":
        assert data["code"] == "CODE-123"
        return _Resp(200, {"access_token": "ACCESS-1", "refresh_token": "REFRESH-1",
                           "expires_in": 3600, "token_type": "Bearer",
                           "scope": "user-read-recently-played"})
    if data["grant_type"] == "refresh_token":
        STATE["refresh_calls"] += 1
        if STATE["refresh_should_fail"]:
            return _Resp(400, {"error": "invalid_grant"})
        # Spotify commonly omits refresh_token on refresh → framework must reuse old
        return _Resp(200, {"access_token": "ACCESS-2", "expires_in": 3600})
    raise AssertionError(data)


def fake_get(url, headers=None, params=None, timeout=None, **_):
    tok = headers["Authorization"].split()[1]
    if url.endswith("/me"):
        return _Resp(200, {"id": "user_igor", "display_name": "Igor"}) if tok.startswith("ACCESS") \
            else _Resp(401, {})
    if url.endswith("/me/player/recently-played"):
        # 4 plays: 2 land yesterday (HST), 2 today (HST) — same shape as the tests
        items = [
            {"played_at": _iso(NOW - timedelta(hours=26)), "track": {"id": "t1", "duration_ms": 180000, "artists": [{"id": "a1"}]}},
            {"played_at": _iso(NOW - timedelta(hours=25)), "track": {"id": "t2", "duration_ms": 200000, "artists": [{"id": "a1"}, {"id": "a2"}]}},
            {"played_at": _iso(NOW - timedelta(hours=2)),  "track": {"id": "t3", "duration_ms": 150000, "artists": [{"id": "a3"}]}},
            {"played_at": _iso(NOW - timedelta(hours=1)),  "track": {"id": "t1", "duration_ms": 180000, "artists": [{"id": "a1"}]}},
        ]
        return _Resp(200, {"items": items})
    if url.endswith("/audio-features"):
        # Simulate a post-2024 app: Spotify denies audio features → 403.
        return _Resp(403, {"error": "forbidden"})
    raise AssertionError(url)


requests.post = fake_post
requests.get = fake_get


# ── The cycle ────────────────────────────────────────────────────────────────
def step(n, title): print(f"\n[{n}] {title}\n" + "-" * 60)


def main():
    supabase = FakeSupabase()
    enc_key = Fernet.generate_key().decode()   # in prod: st.secrets["TOKEN_ENC_KEY"]
    user_id = "00000000-0000-0000-0000-000000000042"   # public.users.id
    secrets = {"SPOTIFY_CLIENT_ID": "demo-client-id",
               "SPOTIFY_CLIENT_SECRET": "demo-client-secret",
               "OAUTH_REDIRECT_URI": "https://mirra.app/oauth/callback"}

    step(1, "CONNECT — build authorize URL with CSRF state")
    spotify = registry.build_from_secrets("spotify", secrets)
    nonce = "n0nc3"
    state = f"{spotify.key}:{nonce}"
    url = spotify.authorize_url(state=state)
    print("redirect user to:", url[:80] + "…")
    print("state carries provider + nonce:", state)

    step(2, "CALLBACK — vendor returns ?code=CODE-123&state=…; verify nonce, exchange")
    cb_state = "spotify:n0nc3"
    assert cb_state.partition(":")[2] == nonce, "CSRF nonce mismatch would abort here"
    bundle = spotify.exchange_code(code="CODE-123")
    print("access_token:", bundle.access_token, "| refresh:", bundle.refresh_token,
          "| expires_at:", bundle.expires_at.isoformat(timespec="seconds"))

    step(3, "STORE — persist encrypted; show what actually sits in the DB row")
    token_store.save_oauth(supabase, user_id, "spotify", bundle, enc_key=enc_key)
    row = supabase.dump("connections")[0]
    print("db access_token :", row["access_token"][:24] + "…  (Fernet, v1: prefix)")
    print("db refresh_token:", row["refresh_token"][:24] + "…")
    print("status          :", row["status"], "| auth_type:", row["auth_type"])
    assert row["access_token"] != "ACCESS-1", "must never be plaintext"

    step(4, "VALIDATE — cheap identity ping with the decrypted token")
    tok = get_valid_token(supabase, spotify, user_id, enc_key=enc_key)
    print("decrypted for use:", tok, "→ /me =", spotify.validate(access_token=tok))

    step(5, "SYNC — recently-played → per-day rows in spotify_daily")
    n = spotify.sync(supabase=supabase, user_id=user_id, access_token=tok, days_back=7)
    print(f"upserted {n} day-rows:")
    for r in sorted(supabase.dump("spotify_daily"), key=lambda r: r["entry_date"]):
        print(f"  {r['entry_date']}  plays={r['track_count']}  artists={r['unique_artists']}"
              f"  listening_ms={r['listening_ms']}  valence={r.get('valence')}"
              "  (audio-features 403 → NULL, as designed)")

    step(6, "AUTO-REFRESH — expire the token; get_valid_token() refreshes silently")
    # Fake time passing: rewrite expiry to the past.
    supabase.table("connections").update(
        {"token_expires_at": (NOW - timedelta(minutes=1)).isoformat()}
    ).eq("user_id", user_id).eq("provider", "spotify").execute()
    tok2 = get_valid_token(supabase, spotify, user_id, enc_key=enc_key)
    row = supabase.dump("connections")[0]
    print("new access token :", tok2, f"(refresh calls: {STATE['refresh_calls']})")
    print("refresh kept old :", token_store.crypto.decrypt(row["refresh_token"], enc_key),
          "← vendor omitted refresh_token; framework reused it")
    assert tok2 == "ACCESS-2"

    step(7, "NEEDS-REAUTH — vendor rejects refresh; connection flagged, UI shows 🟡")
    STATE["refresh_should_fail"] = True
    supabase.table("connections").update(
        {"token_expires_at": (NOW - timedelta(minutes=1)).isoformat()}
    ).eq("user_id", user_id).eq("provider", "spotify").execute()
    try:
        get_valid_token(supabase, spotify, user_id, enc_key=enc_key)
    except ProviderAuthError as e:
        print("ProviderAuthError:", e)
    print("state now:", token_store.connection_state(supabase, user_id, "spotify").value)
    assert token_store.connection_state(supabase, user_id, "spotify") == ConnectionState.NEEDS_REAUTH

    step(8, "DISCONNECT — one click drops the credential")
    token_store.delete_connection(supabase, user_id, "spotify")
    print("state now:", token_store.connection_state(supabase, user_id, "spotify").value)
    assert token_store.connection_state(supabase, user_id, "spotify") == ConnectionState.NOT_CONNECTED

    print("\n✅ full cycle OK — connect → encrypted store → validate → sync → auto-refresh → reauth → disconnect")


if __name__ == "__main__":
    main()
