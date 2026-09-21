-- ---------------------------------------------------------------------------
--  Mirra: Strava daily rollup (fifth connector)
--  Run in the Supabase SQL editor. Idempotent. ASCII-only on purpose: pasting
--  box-drawing characters through the clipboard into the SQL editor garbles.
--
--  Identity: keyed on auth.users(id) with auth.uid() RLS, same as whoop_daily
--  and fitbit_daily.
--
--  One row = every activity STARTED that athlete-local day, rolled up.
--  Heart rate columns describe the day's main (longest) activity, not an
--  average of averages. `raw` holds trimmed activities: the map polyline and
--  GPS coordinates are deliberately never stored.
-- ---------------------------------------------------------------------------

create table if not exists public.strava_daily (
  user_id     uuid  not null references auth.users(id) on delete cascade,
  entry_date  date  not null,

  -- Volume
  activity_count    int,
  moving_minutes    int,
  elapsed_minutes   int,
  distance_km       float,
  elevation_gain_m  float,

  -- Load
  relative_effort   float,   -- sum of Strava suffer_score; NULL without HR data
  kilojoules        float,   -- rides with power only

  -- What it was
  main_sport_type   text,    -- sport of the longest activity
  sport_types       text,    -- comma-joined distinct sports that day

  -- Heart (main activity only)
  average_heartrate float,
  max_heartrate     float,

  raw         jsonb       default '{}'::jsonb,
  fetched_at  timestamptz default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_strava_daily_user_date
  on public.strava_daily (user_id, entry_date desc);

-- Row-Level Security -------------------------------------------------------
alter table public.strava_daily enable row level security;

drop policy if exists "strava_daily: select own" on public.strava_daily;
drop policy if exists "strava_daily: insert own" on public.strava_daily;
drop policy if exists "strava_daily: update own" on public.strava_daily;
drop policy if exists "strava_daily: delete own" on public.strava_daily;

create policy "strava_daily: select own"
  on public.strava_daily for select
  using (auth.uid() = user_id);

create policy "strava_daily: insert own"
  on public.strava_daily for insert
  with check (auth.uid() = user_id);

create policy "strava_daily: update own"
  on public.strava_daily for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "strava_daily: delete own"
  on public.strava_daily for delete
  using (auth.uid() = user_id);

-- Verification -------------------------------------------------------------
select tablename, rowsecurity from pg_tables where tablename = 'strava_daily';
select policyname, cmd from pg_policies where tablename = 'strava_daily' order by policyname;
