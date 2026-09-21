"""
MIR-3 · End-to-end Fitbit cycle demo — fake user, no real Fitbit, no real DB.

Same walk as demo_spotify_cycle.py, for the connector that is next to go live:

    connect  -> authorize_url (CSRF state) -> callback -> exchange_code
    store    -> tokens encrypted at rest (Fernet) in `connections`
    validate -> /profile.json with the decrypted token
    sync     -> sleep + resting HR + HRV + steps -> rows in `fitbit_daily`
    refresh  -> token expired -> get_valid_token() refreshes and stores the
                ROTATED refresh token (this is where Fitbit differs from Spotify:
                it issues a new refresh token every time, and losing it kills the
                connection at the next refresh)
    reauth   -> refresh rejected -> connection flagged NEEDS_REAUTH
    disconnect

The Fitbit HTTP surface is stubbed at the `requests` level and Supabase is a
tiny in-memory fake, so this runs offline:

    python3 examples/demo_fitbit_cycle.py

The sleep payload deliberately mixes the two shapes a real account produces: a
"stages" night from a modern tracker, a "classic" night (what a manually created
log looks like — no stage breakdown), and a nap. That is exactly what
scripts/fitbit_verify_cycle.py will produce against a real account before anyone
owns hardware.

This is a *reader's* demo for reviewing the design — it is not a test fixture
(tests live in tests/).
"""
from __future__ import annotations

import base64
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


# ── Fake Fitbit HTTP ─────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body
        self.ok = 200 <= status < 300
        self.text = str(body)
    def json(self): return self._b


STATE = {"refresh_should_fail": False, "refresh_calls": 0, "revoked": False}
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)

EXPECTED_BASIC = "Basic " + base64.b64encode(b"demo-client-id:demo-client-secret").decode()


def fake_post(url, data=None, headers=None, timeout=None, **_):
    if url.endswith("/oauth2/revoke"):
        STATE["revoked"] = True
        return _Resp(200, {})
    assert url.endswith("/oauth2/token"), url
    assert headers["Authorization"] == EXPECTED_BASIC, "client creds via HTTP Basic"
    if data["grant_type"] == "authorization_code":
        assert data["code"] == "CODE-123"
        return _Resp(200, {"access_token": "ACCESS-1", "refresh_token": "REFRESH-1",
                           "expires_in": 28800, "token_type": "Bearer",
                           "scope": "sleep heartrate activity profile",
                           "user_id": "FAKE7Z"})
    if data["grant_type"] == "refresh_token":
        STATE["refresh_calls"] += 1
        if STATE["refresh_should_fail"]:
            return _Resp(400, {"errors": [{"errorType": "invalid_grant"}]})
        # Fitbit ROTATES: a brand-new refresh token comes back every time.
        return _Resp(200, {"access_token": "ACCESS-2", "refresh_token": "REFRESH-2",
                           "expires_in": 28800, "token_type": "Bearer"})
    raise AssertionError(data)


def _sleep_payload() -> dict:
    return {"sleep": [
        # A modern tracker's night: stages present.
        {"dateOfSleep": YESTERDAY.isoformat(), "isMainSleep": True,
         "type": "stages", "logId": 111, "efficiency": 94,
         "minutesAsleep": 421, "minutesAwake": 39, "timeInBed": 460,
         "levels": {"summary": {
             "deep": {"minutes": 62, "count": 4},
             "light": {"minutes": 236, "count": 19},
             "rem": {"minutes": 123, "count": 8},
             "wake": {"minutes": 39, "count": 21}}}},
        # An afternoon nap the same day — counted, never merged into the night.
        {"dateOfSleep": YESTERDAY.isoformat(), "isMainSleep": False,
         "type": "classic", "logId": 112, "efficiency": 90,
         "minutesAsleep": 41, "minutesAwake": 4, "timeInBed": 45,
         "levels": {"summary": {"asleep": {"minutes": 41, "count": 1}}}},
        # Last night, entered by hand (what scripts/fitbit_verify_cycle.py makes):
        # Fitbit returns it as "classic", so stage minutes stay NULL.
        {"dateOfSleep": TODAY.isoformat(), "isMainSleep": True,
         "type": "classic", "logId": 113, "efficiency": 91,
         "minutesAsleep": 432, "minutesAwake": 28, "timeInBed": 460,
         "levels": {"summary": {"asleep": {"minutes": 432, "count": 1},
                                "restless": {"minutes": 24, "count": 6},
                                "awake": {"minutes": 4, "count": 2}}}},
    ]}


def fake_get(url, headers=None, params=None, timeout=None, **_):
    tok = headers["Authorization"].split()[1]
    if not tok.startswith("ACCESS"):
        return _Resp(401, {})
    if url.endswith("/profile.json"):
        return _Resp(200, {"user": {"encodedId": "FAKE7Z", "displayName": "Test Tester",
                                    "timezone": "Pacific/Honolulu"}})
    if "/sleep/date/" in url:
        return _Resp(200, _sleep_payload())
    if "/activities/heart/date/" in url:
        return _Resp(200, {"activities-heart": [
            {"dateTime": YESTERDAY.isoformat(),
             "value": {"restingHeartRate": 57, "heartRateZones": []}},
            {"dateTime": TODAY.isoformat(),
             "value": {"restingHeartRate": 59, "heartRateZones": []}}]})
    if "/hrv/date/" in url:
        # Only one day has HRV — a real account is full of holes like this.
        return _Resp(200, {"hrv": [
            {"dateTime": YESTERDAY.isoformat(),
             "value": {"dailyRmssd": 41.6, "deepRmssd": 46.2}}]})
    if "/activities/steps/date/" in url:
        return _Resp(200, {"activities-steps": [
            {"dateTime": YESTERDAY.isoformat(), "value": "8231"},
            {"dateTime": TODAY.isoformat(), "value": "2044"}]})
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
    secrets = {"FITBIT_CLIENT_ID": "demo-client-id",
               "FITBIT_CLIENT_SECRET": "demo-client-secret",
               "OAUTH_REDIRECT_URI": "https://mirra-reflections.streamlit.app/"}

    print(f"fake user: {user_id}   (nothing here touches a real account)")

    step(1, "CONNECT — build the authorize URL with a CSRF state")
    fitbit = registry.build_from_secrets("fitbit", secrets)
    nonce = "n0nc3"
    state = f"{fitbit.key}:{nonce}"
    url = fitbit.authorize_url(state=state)
    print("redirect user to:", url[:96] + "…")
    print("scopes requested:", fitbit.meta.default_scopes)

    step(2, "CALLBACK — vendor returns ?code=CODE-123&state=…; verify nonce, exchange")
    assert "fitbit:n0nc3".partition(":")[2] == nonce, "CSRF nonce mismatch would abort here"
    bundle = fitbit.exchange_code(code="CODE-123")
    print("access_token:", bundle.access_token, "| refresh:", bundle.refresh_token,
          "| expires_at:", bundle.expires_at.isoformat(timespec="seconds"), "(8h, Fitbit's max)")

    step(3, "STORE — persist encrypted; show what actually sits in the DB row")
    token_store.save_oauth(supabase, user_id, "fitbit", bundle, enc_key=enc_key)
    row = supabase.dump("connections")[0]
    print("db access_token :", row["access_token"][:28] + "…  (Fernet, v1: prefix)")
    print("db refresh_token:", row["refresh_token"][:28] + "…")
    print("status          :", row["status"], "| auth_type:", row["auth_type"])
    assert row["access_token"] != "ACCESS-1", "must never be plaintext"

    step(4, "VALIDATE — cheap identity ping with the decrypted token")
    tok = get_valid_token(supabase, fitbit, user_id, enc_key=enc_key)
    who = fitbit.validate(access_token=tok)["user"]
    print("decrypted for use:", tok, "→ /profile.json =", who["displayName"], f"({who['encodedId']})")

    step(5, "SYNC — sleep + resting HR + HRV + steps → rows in fitbit_daily")
    n = fitbit.sync(supabase=supabase, user_id=user_id, access_token=tok, days_back=7)
    print(f"upserted {n} day-rows:\n")
    for r in sorted(supabase.dump("fitbit_daily"), key=lambda r: r["entry_date"]):
        print(f"  {r['entry_date']}"
              f"  asleep={r.get('minutes_asleep')}m"
              f"  eff={r.get('sleep_efficiency')}"
              f"  deep={r.get('minutes_deep')}"
              f"  rem={r.get('minutes_rem')}"
              f"  naps={r.get('nap_count')}"
              f"  rhr={r.get('resting_heart_rate')}"
              f"  hrv={r.get('hrv_daily_rmssd')}"
              f"  steps={r.get('steps')}")
    print("\n  note the two shapes: the stages night has deep/rem, the hand-entered")
    print("  'classic' night keeps duration and efficiency with stages NULL, and the")
    print("  day with no HRV reading simply has none — no row is dropped for it.")

    step(6, "AUTO-REFRESH — expire the token; the ROTATED refresh token must be stored")
    supabase.table("connections").update(
        {"token_expires_at": (NOW - timedelta(minutes=1)).isoformat()}
    ).eq("user_id", user_id).eq("provider", "fitbit").execute()
    tok2 = get_valid_token(supabase, fitbit, user_id, enc_key=enc_key)
    row = supabase.dump("connections")[0]
    stored_refresh = token_store.crypto.decrypt(row["refresh_token"], enc_key)
    print("new access token :", tok2, f"(refresh calls: {STATE['refresh_calls']})")
    print("stored refresh   :", stored_refresh, "← rotated; keeping REFRESH-1 would")
    print("                     break the connection at the next refresh")
    assert (tok2, stored_refresh) == ("ACCESS-2", "REFRESH-2")

    step(7, "NEEDS-REAUTH — vendor rejects the refresh; connection flagged, UI shows it")
    STATE["refresh_should_fail"] = True
    supabase.table("connections").update(
        {"token_expires_at": (NOW - timedelta(minutes=1)).isoformat()}
    ).eq("user_id", user_id).eq("provider", "fitbit").execute()
    try:
        get_valid_token(supabase, fitbit, user_id, enc_key=enc_key)
    except ProviderAuthError as e:
        print("ProviderAuthError:", e)
    print("state now:", token_store.connection_state(supabase, user_id, "fitbit").value)
    assert token_store.connection_state(supabase, user_id, "fitbit") == ConnectionState.NEEDS_REAUTH

    step(8, "DISCONNECT — revoke at the vendor, then drop the credential")
    fitbit.revoke(access_token="ACCESS-2", refresh_token="REFRESH-2")
    token_store.delete_connection(supabase, user_id, "fitbit")
    print("revoke called at vendor:", STATE["revoked"])
    print("state now:", token_store.connection_state(supabase, user_id, "fitbit").value)
    assert token_store.connection_state(supabase, user_id, "fitbit") == ConnectionState.NOT_CONNECTED

    print("\nOK — connect → encrypted store → validate → sync → rotate → reauth → disconnect")
    print("The only thing missing before this runs for real: FITBIT_CLIENT_ID/SECRET.")


if __name__ == "__main__":
    main()
