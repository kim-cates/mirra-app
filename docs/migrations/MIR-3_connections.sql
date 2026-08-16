-- ──────────────────────────────────────────────────────────────────────────
--  MIR-3 · OAuth framework — connections + spotify_daily
--  Run in the Supabase SQL editor, then mirror into migrations.sql.
--
--  IDENTITY: keyed on the app's REAL identity — public.users(id) — because the
--  app authenticates against the custom public.users table (auth.py sets
--  st.session_state["user_id"] = users.id) and has NO Supabase Auth session.
--  This matches how oura_credentials is actually populated at runtime today
--  (migrations.sql declares oura_* against auth.users, but the app writes
--  public.users ids — the connections table follows real behavior, not the
--  aspirational declaration). See docs/MIR-3_oauth_framework.md §6.
--
--  RLS: NOT enabled with auth.uid() — there is no Supabase Auth session, so
--  auth.uid() is null and would lock the app out (same reason public.users has
--  no RLS today). App-level scoping enforces per-user access for now; tighten
--  before public launch. This is a known, documented gap (not new to MIR-3).
-- ──────────────────────────────────────────────────────────────────────────

-- Multi-provider credential store (generalizes oura_credentials)
create table if not exists public.connections (
  user_id           uuid        not null references public.users(id) on delete cascade,
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

-- OAuth CSRF nonces. REQUIRED, not optional: Streamlit's session_state does not
-- survive the redirect out to the vendor and back (the callback lands on a fresh
-- session), so the `state` nonce must be persisted server-side or every genuine
-- connection is rejected. Generalizes the existing oura_oauth_states table.
-- Rows are single-use (deleted on consume) and expire after 10 minutes.
create table if not exists public.oauth_states (
  state       text        primary key,
  provider    text        not null,
  user_id     uuid        not null references public.users(id) on delete cascade,
  created_at  timestamptz not null default now()
);

create index if not exists idx_oauth_states_created
  on public.oauth_states (created_at);

-- Spotify daily rollup, one row per (user, local day)
create table if not exists public.spotify_daily (
  user_id         uuid        not null references public.users(id) on delete cascade,
  entry_date      date        not null,

  track_count     int,                       -- plays counted in the window
  unique_artists  int,
  listening_ms    bigint,                    -- summed track durations (approx)

  -- Audio-feature means — nullable: Spotify restricted /audio-features for
  -- newer apps (see design doc). Populated only if the app has access.
  valence         float,
  energy          float,
  tempo           float,

  raw             jsonb       default '{}'::jsonb,
  fetched_at      timestamptz default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_spotify_daily_user_date
  on public.spotify_daily (user_id, entry_date desc);

-- ── Migration of existing Oura credentials (run once, after verifying) ──────
-- insert into public.connections
--   (user_id, provider, access_token, refresh_token, token_expires_at, auth_type, connected_at)
-- select user_id, 'oura', access_token, refresh_token, token_expires_at, auth_type, connected_at
--   from public.oura_credentials
-- on conflict (user_id, provider) do nothing;
--   NOTE: existing tokens are plaintext; they'll be re-wrapped as v1: on next
--   write (token_store treats untagged values as legacy plaintext).
