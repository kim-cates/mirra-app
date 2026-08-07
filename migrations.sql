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
--  Run in the Supabase SQL editor. DRAFT — not yet applied (awaiting creds).
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
  -- Onboarding completion markers: all profile fields are optional, so
  -- completion can't be inferred from data — explicit timestamps gate the
  -- once-per-user onboarding screens (profile form, insight inquiry).
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
