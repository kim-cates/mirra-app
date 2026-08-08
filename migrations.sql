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


-- Temporary OAuth state store to survive login redirects. Stores the
-- authorization `state` nonce and (optionally) token_payload after the
-- code exchange so the app can finish association once the user signs in.
create table if not exists public.oura_oauth_states (
  state text primary key,
  user_id uuid references auth.users(id),
  token_payload jsonb,
  created_at timestamptz default now()
);

alter table public.oura_oauth_states enable row level security;
drop policy if exists "oura_oauth_states: insert" on public.oura_oauth_states;
create policy "oura_oauth_states: insert" on public.oura_oauth_states for insert
  with check (true);
