# MIR-3 — Generalized OAuth Framework (design + skeleton)

> Story [#24](https://github.com/kim-cates/mirra-app/issues/24) · sub-issues
> [#25](https://github.com/kim-cates/mirra-app/issues/25)–[#29](https://github.com/kim-cates/mirra-app/issues/29)
> Branch `feature/mir-3-oauth-framework` (worktree `../mirra-oauth`, off `main`).
> **Status: DESIGN + SKELETON.** No DB changes applied. Not wired into `app.py`.
> Not for merge — hand to Kim for review.

## 1. Goal

Make **adding an integration a config change**, and make connecting any account
feel identical across providers. Today Oura auth + sync logic lives inline in
`oura.py` / `oura_ui.py`; every new source would copy that shape. This layer
extracts the shape once.

## 2. Module map

```
providers/
  base.py         OAuthProvider ABC · TokenBundle · ProviderMeta · errors · enums
  registry.py     @register decorator · build_from_secrets() · configured_keys()
  __init__.py     imports providers for side-effect registration (display order)
  (oura.py)       OuraProvider — #26, OWNED BY KIM (o-auth-testing), not shipped here
  spotify.py      SpotifyProvider — full cycle: handshake + real sync()      (#28)
  _template.py    copy-paste starter for the next app (Strava, Fitbit…)
  whoop.py        WhoopProvider — real handshake, sync() skeleton   (3rd)
  crypto.py       Fernet encrypt/decrypt for tokens at rest                   (#27)
  token_store.py  connections table CRUD · get_valid_token() refresh seam     (#27)
connections_ui.py Connections page + CSRF-safe generalized callback           (#29)
tests/test_providers.py     11 offline tests — registry, TTL, CSRF state, errors
tests/test_spotify_sync.py   7 offline tests — recently-played → per-day rows
examples/demo_spotify_cycle.py  runnable e2e (mock Spotify + in-memory DB)
docs/migrations/MIR-3_connections.sql  ready-to-run DDL (public.users)
docs/MIR-3_oauth_framework.md   ← this file
```

Design rules honored: connectors are **isolated "models"** (one module each,
per the founder architecture doc §5); `base/registry/token_store` are pure
Python (no Streamlit/Supabase imports) so providers are unit-testable.

## 3. The interface (`OAuthProvider`) — #25

Every provider implements:

| Method | Purpose | AC (#24) |
|---|---|---|
| `authorize_url(state, scopes?)` | build consent URL | auth URL builder |
| `exchange_code(code)` → `TokenBundle` | code → tokens | token exchange |
| `refresh(refresh_token)` → `TokenBundle` | renew access token | refresh |
| `revoke(access_token, refresh_token?)` | best-effort revoke on disconnect | revoke |
| `validate(access_token)` → dict | cheap identity ping | — |
| `sync(supabase, user_id, access_token, days_back)` → int | pull → normalized rows | no-regression pulls |

`TokenBundle` normalizes vendor JSON once (absolute UTC `expires_at`, not a
relative TTL — avoids clock-skew bugs) so the store/scheduler never parse vendor
payloads. Errors are a fixed taxonomy — `ProviderAuthError` /
`ProviderRateLimitError` / `ProviderConfigError` — so the UI maps them to
human-readable text instead of leaking stack traces or raw callback dumps.

## 4. Registry — “config change” — #25

A provider registers itself:

```python
@register
class SpotifyProvider(OAuthProvider):
    meta = ProviderMeta(key="spotify", label="Spotify", default_scopes="…")
```

To add a provider: drop `providers/<name>.py`, subclass, `@register`, add one
import line in `providers/__init__.py`. The Connections page and callback iterate
the registry — **no vendor names hard-coded in the UI.**

Secrets convention (per KEY, uppercased): `{KEY}_CLIENT_ID`,
`{KEY}_CLIENT_SECRET`, plus one shared `OAUTH_REDIRECT_URI` (legacy
`OURA_REDIRECT_URI` still honored). The provider key travels in OAuth `state`,
so a single callback route serves every provider.

### 4.1 Add a provider (recipe)

Everything below the core is shared; a new app (Strava, Fitbit, Apple Health…)
is one small file. Start from `providers/_template.py`:

1. `cp providers/_template.py providers/strava.py`
2. Rename the class, fill in `ProviderMeta` (key/label/scopes) + the 3 vendor URLs.
3. Uncomment `@register`.
4. Add `from . import strava as _strava` to `providers/__init__.py`.
5. Add `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` to secrets (shared `OAUTH_REDIRECT_URI`).
6. Implement `sync()` + add a `strava_daily` table migration (mirror `oura_daily`).

Steps 1–5 are ~20 min (OAuth is boilerplate). Step 6 — the API→row mapping — is
the only real per-connector work and belongs to whoever owns that task. The
provider then appears on the Connections page automatically.

## 5. Oura refactor — #26 · **owned by Kim** (not in this branch)

⚠ #26 is assigned to **kim-cates** and is in progress on her `o-auth-testing`
branch. To avoid duplicating/colliding with her work, this branch does **not**
ship an Oura provider. The interface reserves the slot; the proposed shape below
is a reference for her #26, not committed code.

Proposed `OuraProvider` delegates straight into the production `oura.py`
(`build_oauth_authorize_url`, `exchange_code_for_token`, `refresh_access_token`,
`validate_token`, `sync_oura`) and maps `OuraError → ProviderError`, so the
refactor is **behavior-preserving** — change the seam, not the Oura logic, no
regression in data pulls. Registering it is one line in `providers/__init__.py`
(marked there). Spotify + Whoop already prove the abstraction generalizes without
it.

## 6. Token storage, encryption, refresh — #27

- **Encryption** (`crypto.py`): Fernet (AES-128-CBC + HMAC), key from
  `st.secrets["TOKEN_ENC_KEY"]`. Stored values carry a `v1:` scheme tag; untagged
  values are treated as legacy plaintext so the Oura table migrates lazily.
- **Store** (`token_store.py`): `connections` table keyed `(user_id, provider)`.
- **Auto-refresh**: `get_valid_token()` (generalized `oura.get_valid_token`)
  refreshes within a 5-min skew, persists the new bundle, and flags
  `NEEDS_REAUTH` if refresh fails — no user action on the happy path.

### Identity decision — resolved from code: **`public.users`**

The question "auth.users vs public.users" is answered by how the app actually
runs, not by the schema declaration:

- `auth.py` sets `st.session_state["user_id"] = users.id` from the **custom
  `public.users` table** on sign-in/sign-up. There is **no Supabase Auth
  session** anywhere in the app.
- `migrations.sql` declares `oura_credentials`/`oura_daily`/`oura_oauth_states`
  against `auth.users` with `auth.uid()` RLS — but the app writes `public.users`
  ids into them. Since Oura works in production, that FK/RLS is not what's
  actually enforced. Kim's `o-auth-testing` branch does not change
  `migrations.sql`/`oura.py`/`auth.py`, so she is on the same runtime identity.

⇒ **`connections` and `spotify_daily` key on `public.users(id)`**, exactly the
identity Oura credentials really use today. This keeps Oura and Spotify tokens
stored the same way and avoids a second identity pattern.

**RLS:** not enabled with `auth.uid()` — it would be `null` and lock the app out.
App-level scoping for now (same as `public.users` today). Known, documented gap
to tighten before public launch (belongs to the identity/auth hardening story,
not MIR-3). Flag to Kim as FYI, no action needed.

**Ready-to-run migration:** [`docs/migrations/MIR-3_connections.sql`](migrations/MIR-3_connections.sql)
(connections + spotify_daily + commented Oura backfill). Apply via the Supabase
SQL editor, then mirror into `migrations.sql`.

<details><summary>Original auth.users variant (kept for reference if identity later moves to Supabase Auth)</summary>

```sql
-- Multi-provider credential store (generalizes oura_credentials)
create table if not exists public.connections (
  user_id           uuid        not null references auth.users(id) on delete cascade,
  provider          text        not null,                     -- 'oura' | 'spotify' | 'whoop'
  access_token      text        not null,                     -- Fernet-encrypted (v1:)
  refresh_token     text,                                      -- Fernet-encrypted (v1:)
  token_expires_at  timestamptz,
  auth_type         text        not null check (auth_type in ('pat','oauth')),
  scopes            text,
  status            text        not null default 'connected'
                                check (status in ('connected','not_connected','needs_reauth')),
  connected_at      timestamptz default now(),
  last_refresh_at   timestamptz,
  primary key (user_id, provider)
);
alter table public.connections enable row level security;
create policy "connections: select own" on public.connections
  for select using (auth.uid() = user_id);
create policy "connections: insert own" on public.connections
  for insert with check (auth.uid() = user_id);
create policy "connections: update own" on public.connections
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "connections: delete own" on public.connections
  for delete using (auth.uid() = user_id);

-- whoop_daily(user_id, entry_date, recovery_score, hrv_avg, resting_hr, sleep_performance, raw, fetched_at)
```
</details>

### Spotify data model — reality check (#28)

The spec wanted **valence / energy / tempo** (Spotify `/audio-features`).
**Spotify restricted `/audio-features` (+ audio-analysis, recommendations) for
apps created after 2024‑11‑27** — a new Mirra app very likely won't get it. So:

- **Reliable baseline** (only needs `user-read-recently-played`): per-local-day
  `track_count`, `unique_artists`, `listening_ms` from `/me/player/recently-played`.
- **Audio features are opportunistic**: fetched if the app has access, otherwise
  degrade to `NULL` (columns are nullable). No crash, no fake numbers.
- **History caveat:** `recently-played` returns ≤ ~50 plays — `days_back` is
  best-effort, not a backfill. Signal accumulates through regular syncs.
- Attribution to the user's **local calendar day** (HST default), matching the
  Oura convention so rows join cleanly on `entry_date`.

Verified end-to-end offline in `examples/demo_spotify_cycle.py`
(connect → encrypted store → validate → sync → auto-refresh → needs-reauth →
disconnect) and unit-tested in `tests/test_spotify_sync.py`.

### Migration path (zero downtime)

1. Apply `connections` DDL in the Supabase SQL editor; mirror into `migrations.sql`.
2. Backfill: copy `oura_credentials` rows → `connections` with `provider='oura'`
   (tokens re-wrapped as `v1:` on first write).
3. Point `token_store._TABLE` at `connections`; `OuraProvider` unchanged.
4. Drop `oura_credentials` once reads are verified.

## 7. Connections page — #29

`connections_ui.render_connections_page()` renders one card per registered
provider: **🟢 Connected / 🟡 Needs reauth / ⚪ Not connected**, one-click
Connect / Disconnect / Reconnect. Unconfigured providers show “Coming soon”.
`handle_oauth_callback()` validates the `state` nonce (CSRF), exchanges the code,
saves encrypted tokens, and backfills 30 days.

## 8. Scope of THIS branch

**Done:** interface, registry, crypto, token store + auto-refresh, Connections
UI, **Spotify full cycle** (handshake + real `sync()` + tests + runnable e2e
demo), Whoop handshake, `_template.py` + recipe, ready-to-run migration SQL,
`cryptography` dep, this doc.

**Kim's lane (excluded here):** #24 (parent) and #26 (Oura onto the interface)
are assigned to Kim, active on `o-auth-testing`. My branch stays in #25 / #27 /
#28 / #29 to avoid collision. Her files (`oura.py`, `oura_ui.py`) untouched.

**Go-live checklist (Igor, once Kim reviews):**
1. Create the Spotify app at developer.spotify.com → redirect URI = app callback.
2. Secrets: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`,
   `TOKEN_ENC_KEY` (Fernet key, generate once, never in chat/git).
3. Apply `docs/migrations/MIR-3_connections.sql` in Supabase → mirror into `migrations.sql`.
4. Wire `connections_ui.handle_oauth_callback` + `render_connections_page` into `app.py`.
5. Test with a real Spotify account; confirm `spotify_daily` rows land.

**Still deferred:** Whoop `sync()` + `whoop_daily`; register Oura when Kim's #26
lands (one import line); retire legacy `oura_ui` settings path.

## 9. For Kim — FYI / decisions

1. ✅ **Identity — resolved from code** (`public.users`, see §6). FYI only: the
   `auth.users` FK/RLS declared in `migrations.sql` doesn't match runtime;
   reconcile before public launch, not an MVP blocker.
2. **`TOKEN_ENC_KEY`** — one Fernet key in Streamlit secrets; rotation policy later.
3. **Connector priority after Spotify** — Whoop assumed; confirm.
4. Keep Oura **PAT** path, or OAuth-only once OAF is seamless?
5. **Review + merge PR #46** when ready — you own `main`.
