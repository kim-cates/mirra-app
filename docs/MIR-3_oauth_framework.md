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
  spotify.py      SpotifyProvider — real handshake, sync() skeleton           (#28)
  whoop.py        WhoopProvider — real handshake, sync() skeleton   (3rd)
  crypto.py       Fernet encrypt/decrypt for tokens at rest                   (#27)
  token_store.py  connections table CRUD · get_valid_token() refresh seam     (#27)
connections_ui.py Connections page + CSRF-safe generalized callback           (#29)
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

### Proposed DDL — DRAFT, **not applied** (needs Kim + identity decision)

⚠ Depends on the unresolved **identity question** (custom `public.users` vs
`auth.users`; see `migrations.sql` MIR-1 note). The `oura_*` tables FK to
`auth.users` with `auth.uid()` RLS, but the app authenticates against
`public.users` with no Supabase Auth session. **`connections` must key on
whichever identity we standardize on** — decide before applying. DDL below shown
against `auth.users` to match the existing `oura_*` pattern; swap the FK +
policies if we go with `public.users`.

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

-- Per-provider daily rows follow the oura_daily shape:
-- spotify_daily(user_id, entry_date, valence, energy, tempo, track_count, raw, fetched_at)
-- whoop_daily(user_id, entry_date, recovery_score, hrv_avg, resting_hr, sleep_performance, raw, fetched_at)
```

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

**Done (design + skeleton):** interface, registry, Spotify + Whoop handshakes,
crypto, token store + refresh seam, Connections UI, this doc.

**Kim's lane (excluded here):** #24 (parent) and #26 (Oura onto the interface)
are assigned to Kim, active on `o-auth-testing`. My branch stays in #25 / #27 /
#28 / #29 to avoid collision.

**Deferred (need DB / secrets / Kim review):** apply `connections` migration;
implement `spotify_daily` / `whoop_daily` sync; add `cryptography` to
`requirements.txt`; provision Spotify/Whoop client apps; wire
`connections_ui` into `app.py`; delete legacy `oura_ui` settings path.

## 9. Open decisions for Kim

1. **Identity** — `auth.users` vs `public.users` for `connections` (blocks RLS).
2. **`TOKEN_ENC_KEY`** — generate once, store in Streamlit secrets; rotation policy?
3. **Connector priority after Spotify** — Whoop assumed here; confirm.
4. Keep Oura **PAT** path, or OAuth-only once OAF is seamless?
