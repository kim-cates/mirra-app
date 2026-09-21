"""
MIR-3 · End-to-end Strava cycle demo — fake user, no real Strava, no real DB.

Same walk as demo_fitbit_cycle.py, for the first connector that can go live
end-to-end today (registration needs nothing but a free Strava account):

    connect  -> authorize_url (CSRF state, COMMA-delimited scopes)
    store    -> tokens encrypted at rest (Fernet) in `connections`
    validate -> /athlete with the decrypted token
    sync     -> activities -> daily rollups in `strava_daily`
    refresh  -> token expired (Strava's live 6h) -> get_valid_token() refreshes
                and stores the returned refresh token (Strava may rotate it)
    reauth   -> refresh rejected -> connection flagged NEEDS_REAUTH
    disconnect -> POST /oauth/deauthorize

The Strava HTTP surface is stubbed at the `requests` level and Supabase is a
tiny in-memory fake, so this runs offline:

    python3 examples/demo_strava_cycle.py

The activity payload deliberately mixes the shapes a real account produces: a
run with HR, an evening trainer ride with power (kilojoules) but weaker HR, and
a hand-logged yoga session with nothing but a duration. Every activity carries
a map polyline and GPS coordinates in the fake response — and the demo asserts
they never reach the stored row.

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

from cryptography.fernet import Fernet  # noqa: E402


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


# ── Fake Strava HTTP ─────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body
        self.ok = 200 <= status < 300
        self.text = str(body)
    def json(self): return self._b


STATE = {"refresh_should_fail": False, "refresh_calls": 0, "deauthorized": False}
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


def fake_post(url, data=None, headers=None, timeout=None, **_):
    if url.endswith("/oauth/deauthorize"):
        STATE["deauthorized"] = True
        return _Resp(200, {})
    assert url.endswith("/oauth/token"), url
    # Strava difference vs Fitbit: client creds travel in the BODY, no Basic.
    assert data["client_id"] == "demo-client-id"
    assert data["client_secret"] == "demo-client-secret"
    assert not (headers or {}).get("Authorization")
    if data["grant_type"] == "authorization_code":
        assert data["code"] == "CODE-123"
        return _Resp(200, {"access_token": "ACCESS-1", "refresh_token": "REFRESH-1",
                           "expires_in": 21600, "token_type": "Bearer",
                           # the exchange response also carries the athlete
                           "athlete": {"id": 424242, "firstname": "Test",
                                       "lastname": "Tester"}})
    if data["grant_type"] == "refresh_token":
        STATE["refresh_calls"] += 1
        if STATE["refresh_should_fail"]:
            return _Resp(400, {"errors": [{"code": "invalid", "field": "refresh_token"}]})
        return _Resp(200, {"access_token": "ACCESS-2", "refresh_token": "REFRESH-2",
                           "expires_in": 21600, "token_type": "Bearer"})
    raise AssertionError(data)


def _activities_payload() -> list:
    gps = {"map": {"summary_polyline": "kxl~F|natOl@..."},
           "start_latlng": [21.30, -157.85], "end_latlng": [21.31, -157.84]}
    return [
        # Yesterday morning: a run with HR — the day's main activity.
        {"id": 1, "name": "Morning Run", "sport_type": "Run", "type": "Run",
         "start_date": f"{YESTERDAY}T17:31:12Z",
         "start_date_local": f"{YESTERDAY}T07:31:12Z",
         "moving_time": 3604, "elapsed_time": 3812, "distance": 10012.3,
         "total_elevation_gain": 118.0, "average_heartrate": 152.4,
         "max_heartrate": 181.0, "suffer_score": 64.0, **gps},
        # Yesterday evening: a shorter trainer ride with power but calmer HR.
        {"id": 2, "name": "Zwift Spin", "sport_type": "VirtualRide", "type": "VirtualRide",
         "start_date": f"{YESTERDAY}T04:02:00Z",
         "start_date_local": f"{YESTERDAY}T18:02:00Z",
         "moving_time": 1800, "elapsed_time": 1800, "distance": 15200.0,
         "total_elevation_gain": 96.0, "average_heartrate": 121.0,
         "max_heartrate": 139.0, "suffer_score": 18.0, "kilojoules": 402.5,
         "trainer": True, **gps},
        # Today: a hand-logged yoga session — no distance, no HR, no effort.
        {"id": 3, "name": "Evening Yoga", "sport_type": "Yoga", "type": "Yoga",
         "start_date": f"{TODAY}T05:00:00Z",
         "start_date_local": f"{TODAY}T19:00:00Z",
         "moving_time": 2700, "elapsed_time": 2700, "distance": 0.0,
         "total_elevation_gain": 0.0, "manual": True},
    ]


def fake_get(url, headers=None, params=None, timeout=None, **_):
    tok = headers["Authorization"].split()[1]
    if not tok.startswith("ACCESS"):
        return _Resp(401, {})
    if url.endswith("/athlete"):
        return _Resp(200, {"id": 424242, "firstname": "Test", "lastname": "Tester",
                           "measurement_preference": "meters"})
    if url.endswith("/athlete/activities"):
        # One page is enough; the connector stops when a page comes back short.
        return _Resp(200, _activities_payload() if params.get("page", 1) == 1 else [])
    raise AssertionError(url)


def fake_delete(url, headers=None, timeout=None, **_):
    raise AssertionError("the connector never deletes anything: " + url)


requests.post = fake_post
requests.get = fake_get
requests.delete = fake_delete


# ── The cycle ────────────────────────────────────────────────────────────────
def step(n, title): print(f"\n[{n}] {title}\n" + "-" * 68)


def main():
    supabase = FakeSupabase()
    enc_key = Fernet.generate_key().decode()          # in prod: st.secrets["TOKEN_ENC_KEY"]
    user_id = "00000000-0000-0000-0000-000000000042"  # auth.users.id after MIR-56
    secrets = {"STRAVA_CLIENT_ID": "demo-client-id",
               "STRAVA_CLIENT_SECRET": "demo-client-secret",
               "OAUTH_REDIRECT_URI": "https://mirra-reflections.streamlit.app/"}

    print(f"fake user: {user_id}   (nothing here touches a real account)")

    step(1, "CONNECT — build the authorize URL with a CSRF state")
    strava = registry.build_from_secrets("strava", secrets)
    nonce = "n0nc3"
    state = f"{strava.key}:{nonce}"
    url = strava.authorize_url(state=state)
    print("redirect user to:", url[:96] + "…")
    print("scopes requested:", strava.meta.default_scopes,
          "(comma-delimited — Strava quirk)")

    step(2, "CALLBACK — vendor returns ?code=CODE-123&state=…; verify nonce, exchange")
    assert "strava:n0nc3".partition(":")[2] == nonce, "CSRF nonce mismatch would abort here"
    bundle = strava.exchange_code(code="CODE-123")
    print("access_token:", bundle.access_token, "| refresh:", bundle.refresh_token,
          "| expires_at:", bundle.expires_at.isoformat(timespec="seconds"), "(6h, Strava's max)")
    print("athlete in the exchange response:", bundle.raw["athlete"]["firstname"],
          bundle.raw["athlete"]["lastname"])

    step(3, "STORE — persist encrypted; show what actually sits in the DB row")
    token_store.save_oauth(supabase, user_id, "strava", bundle, enc_key=enc_key)
    row = supabase.dump("connections")[0]
    print("db access_token :", row["access_token"][:28] + "…  (Fernet, v1: prefix)")
    print("db refresh_token:", row["refresh_token"][:28] + "…")
    print("status          :", row["status"], "| auth_type:", row["auth_type"])
    assert row["access_token"] != "ACCESS-1", "must never be plaintext"

    step(4, "VALIDATE — cheap identity ping with the decrypted token")
    tok = get_valid_token(supabase, strava, user_id, enc_key=enc_key)
    who = strava.validate(access_token=tok)
    print("decrypted for use:", tok, "→ /athlete =",
          who["firstname"], who["lastname"], f"({who['id']})")

    step(5, "SYNC — activities → daily rollups in strava_daily")
    n = strava.sync(supabase=supabase, user_id=user_id, access_token=tok, days_back=7)
    print(f"upserted {n} day-rows:\n")
    for r in sorted(supabase.dump("strava_daily"), key=lambda r: r["entry_date"]):
        print(f"  {r['entry_date']}"
              f"  acts={r.get('activity_count')}"
              f"  moving={r.get('moving_minutes')}m"
              f"  dist={r.get('distance_km')}km"
              f"  effort={r.get('relative_effort')}"
              f"  main={r.get('main_sport_type')}"
              f"  hr={r.get('average_heartrate')}"
              f"  sports={r.get('sport_types')}")
    day = next(r for r in supabase.dump("strava_daily")
               if r["entry_date"] == YESTERDAY.isoformat())
    for kept in day["raw"]["activities"]:
        assert "map" not in kept and "start_latlng" not in kept, "GPS must never be stored"
    print("\n  note: two activities rolled into one day (effort summed, HR from the")
    print("  longest one), the manual yoga day has no HR/effort at all, and the")
    print("  stored raw is asserted free of map polylines and GPS coordinates.")

    step(6, "AUTO-REFRESH — expire the token; the returned refresh token is stored")
    supabase.table("connections").update(
        {"token_expires_at": (NOW - timedelta(minutes=1)).isoformat()}
    ).eq("user_id", user_id).eq("provider", "strava").execute()
    tok2 = get_valid_token(supabase, strava, user_id, enc_key=enc_key)
    row = supabase.dump("connections")[0]
    stored_refresh = token_store.crypto.decrypt(row["refresh_token"], enc_key)
    print("new access token :", tok2, f"(refresh calls: {STATE['refresh_calls']})")
    print("stored refresh   :", stored_refresh, "← whatever Strava returned; it may rotate")
    assert (tok2, stored_refresh) == ("ACCESS-2", "REFRESH-2")

    step(7, "NEEDS-REAUTH — vendor rejects the refresh; connection flagged, UI shows it")
    STATE["refresh_should_fail"] = True
    supabase.table("connections").update(
        {"token_expires_at": (NOW - timedelta(minutes=1)).isoformat()}
    ).eq("user_id", user_id).eq("provider", "strava").execute()
    try:
        get_valid_token(supabase, strava, user_id, enc_key=enc_key)
    except ProviderAuthError as e:
        print("ProviderAuthError:", e)
    print("state now:", token_store.connection_state(supabase, user_id, "strava").value)
    assert token_store.connection_state(supabase, user_id, "strava") == ConnectionState.NEEDS_REAUTH

    step(8, "DISCONNECT — deauthorize at the vendor, then drop the credential")
    strava.revoke(access_token="ACCESS-2", refresh_token="REFRESH-2")
    token_store.delete_connection(supabase, user_id, "strava")
    print("deauthorize called at vendor:", STATE["deauthorized"])
    print("state now:", token_store.connection_state(supabase, user_id, "strava").value)
    assert token_store.connection_state(supabase, user_id, "strava") == ConnectionState.NOT_CONNECTED

    print("\nOK — connect → encrypted store → validate → sync → refresh → reauth → disconnect")
    print("The only thing missing before this runs for real: STRAVA_CLIENT_ID/SECRET.")


if __name__ == "__main__":
    main()
