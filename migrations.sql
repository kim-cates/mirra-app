-- ──────────────────────────────────────────────────────────────────────────
--  Mirra: Oura integration migration
--  Run in the Supabase SQL editor.
--  Creates two tables, both with RLS scoped to auth.uid() = user_id.
-- ──────────────────────────────────────────────────────────────────────────

-- Daily Oura summary, one row per (user, date)
create table if not exists public.oura_daily (
  user_id              uuid        not null references auth.users(id) on delete cascade,
  entry_date           date        not null,

  -- Headline scores (0-100)
  sleep_score          int,
  readiness_score      int,
  activity_score       int,

  -- Useful detail metrics
  total_sleep_seconds  int,
  hrv_avg              float,
  resting_hr           int,
  steps                int,

  -- Full original payloads for future-proofing
  raw                  jsonb       default '{}'::jsonb,

  fetched_at           timestamptz default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_oura_daily_user_date
  on public.oura_daily (user_id, entry_date desc);


-- Per-user Oura credentials (PAT or OAuth)
create table if not exists public.oura_credentials (
  user_id            uuid        primary key references auth.users(id) on delete cascade,
  access_token       text        not null,
  refresh_token      text,
  token_expires_at   timestamptz,
  auth_type          text        not null check (auth_type in ('pat', 'oauth')),
  connected_at       timestamptz default now()
);


-- ── Row-Level Security ────────────────────────────────────────────────────
alter table public.oura_daily       enable row level security;
alter table public.oura_credentials enable row level security;

-- oura_daily: each user can only see/modify their own rows
drop policy if exists "oura_daily: select own"  on public.oura_daily;
drop policy if exists "oura_daily: insert own"  on public.oura_daily;
drop policy if exists "oura_daily: update own"  on public.oura_daily;
drop policy if exists "oura_daily: delete own"  on public.oura_daily;

create policy "oura_daily: select own"
  on public.oura_daily for select
  using (auth.uid() = user_id);

create policy "oura_daily: insert own"
  on public.oura_daily for insert
  with check (auth.uid() = user_id);

create policy "oura_daily: update own"
  on public.oura_daily for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "oura_daily: delete own"
  on public.oura_daily for delete
  using (auth.uid() = user_id);

-- oura_credentials: same shape
drop policy if exists "oura_credentials: select own"  on public.oura_credentials;
drop policy if exists "oura_credentials: insert own"  on public.oura_credentials;
drop policy if exists "oura_credentials: update own"  on public.oura_credentials;
drop policy if exists "oura_credentials: delete own"  on public.oura_credentials;

create policy "oura_credentials: select own"
  on public.oura_credentials for select
  using (auth.uid() = user_id);

create policy "oura_credentials: insert own"
  on public.oura_credentials for insert
  with check (auth.uid() = user_id);

create policy "oura_credentials: update own"
  on public.oura_credentials for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "oura_credentials: delete own"
  on public.oura_credentials for delete
  using (auth.uid() = user_id);


-- ──────────────────────────────────────────────────────────────────────────
--  MIR-1: Expand user profile data  (story #14, sub-issue #15)
--  Run in the Supabase SQL editor.
--
--  ⚠ DECISION NEEDED (Kim): the story says "profiles" table, but the app today
--  authenticates against the custom public.users table (auth.py) and reads
--  st.session_state["user_id"] from users.id — there is NO Supabase Auth
--  session, so a separate profiles table keyed on auth.users would not be
--  populated or read by the current code. This migration therefore extends the
--  EXISTING public.users table so the fields are functional immediately.
--  If we instead move to Supabase Auth + a profiles table, that is a larger
--  change (MIR-1 identity refactor) and this block should be revisited.
--  All fields are OPTIONAL — nothing here blocks account creation.
-- ──────────────────────────────────────────────────────────────────────────

alter table public.users
  add column if not exists email            text,
  add column if not exists phone            text,
  add column if not exists date_of_birth    date,
  add column if not exists sex              text,
  add column if not exists gender_identity  text,
  add column if not exists location         text,
  add column if not exists timezone         text  default 'Pacific/Honolulu',
  add column if not exists occupation       text,

  -- ── Onboarding state ────────────────────────────────────────────────────
  -- Without these the onboarding screens have nowhere to record "done", so
  -- every sign-in replays intro → profile → inquiry. Every profile field is
  -- optional, so completion cannot be inferred from the data itself —
  -- it needs explicit markers.
  add column if not exists has_seen_intro        boolean     default false,
  add column if not exists profile_completed_at  timestamptz,
  add column if not exists inquiry_completed_at  timestamptz,
  -- INTERIM: inquiry answers as jsonb until the goals schema (#20) lands;
  -- backfill into user_goals and drop this column once #20 is decided.
  add column if not exists inquiry_responses     jsonb;

-- Case-insensitive uniqueness on email, but only when an email is present
-- (fields are optional, so NULL/empty emails must not collide).
create unique index if not exists idx_users_email
  on public.users (lower(email))
  where email is not null and email <> '';

-- ── RLS review (sub-issue #15) ────────────────────────────────────────────
-- public.users currently has NO RLS policies in this file (the table pre-dates
-- migrations.sql). The oura_* tables above scope on auth.uid(), which assumes
-- Supabase Auth identities — but users.id is NOT an auth.users id. Enabling
-- auth.uid()-based RLS on public.users would lock the app out under the current
-- custom-auth model. Confirm the authoritative identity with Kim before adding
-- RLS here; leaving users RLS untouched for now to avoid breaking sign-in.
--   → see Transcripts/skills/supabase-tables.SKILL.md ("two identity systems").


-- ──────────────────────────────────────────────────────────────────────────
--  MIR-3: OAuth framework tables  (story #24, sub-issue #27)
--  Mirrors docs/migrations/MIR-3_connections.sql. DRAFT — NOT YET APPLIED.
--
--  ⚠ BLOCKED ON THE IDENTITY DECISION (same fork as the MIR-1 block above).
--  Keyed on public.users(id) because that is what the app actually writes:
--  auth.py sets st.session_state["user_id"] = public.users.id and there is NO
--  Supabase Auth session. The oura_* tables above declare auth.users(id), but
--  the running app stores public.users ids in them — these tables follow real
--  behavior, not the aspirational declaration. Confirm with Kim before running;
--  if we standardize on Supabase Auth instead, swap the FKs and add
--  auth.uid() RLS (see the auth.users variant in docs/migrations/).
--
--  RLS: intentionally NOT auth.uid()-based — under custom auth auth.uid() is
--  null and would lock the app out, exactly as noted for public.users above.
--  Per-user scoping is enforced in the app layer for now. Tighten before launch.
-- ──────────────────────────────────────────────────────────────────────────

-- Multi-provider credential store (generalizes oura_credentials)
create table if not exists public.connections (
  user_id           uuid        not null references public.users(id) on delete cascade,
  provider          text        not null,                     -- 'oura' | 'spotify' | 'whoop'
  access_token      text        not null,                     -- Fernet-encrypted, 'v1:' prefix
  refresh_token     text,                                      -- Fernet-encrypted, 'v1:' prefix
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
-- survive the redirect out to the provider and back (the callback lands on a
-- fresh session), so the `state` nonce must be persisted server-side or every
-- genuine connection is rejected. Generalizes oura_oauth_states.
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

  -- Audio-feature means — nullable: Spotify restricted /audio-features for apps
  -- created after 2024-11-27, so these stay NULL unless the app has access.
  valence         float,
  energy          float,
  tempo           float,

  raw             jsonb       default '{}'::jsonb,
  fetched_at      timestamptz default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_spotify_daily_user_date
  on public.spotify_daily (user_id, entry_date desc);

-- ── One-time backfill of existing Oura credentials (run AFTER verifying) ────
-- insert into public.connections
--   (user_id, provider, access_token, refresh_token, token_expires_at, auth_type, connected_at)
-- select user_id, 'oura', access_token, refresh_token, token_expires_at, auth_type, connected_at
--   from public.oura_credentials
-- on conflict (user_id, provider) do nothing;
--   Existing tokens are plaintext; token_store treats untagged values as legacy
--   and re-wraps them as 'v1:' on the next write.
