-- ---------------------------------------------------------------------------
--  Mirra: Fitbit daily rollup (fourth connector)
--  Run in the Supabase SQL editor. Idempotent. ASCII-only on purpose: pasting
--  box-drawing characters through the clipboard into the SQL editor garbles.
--
--  Identity: keyed on auth.users(id) with auth.uid() RLS, same as whoop_daily
--  and oura_daily after the MIR-56 Supabase Auth migration.
--
--  Units are Fitbit's own: sleep in minutes (not milliseconds like Whoop),
--  efficiency 0-100, HRV in milliseconds RMSSD.
-- ---------------------------------------------------------------------------

create table if not exists public.fitbit_daily (
  user_id     uuid  not null references auth.users(id) on delete cascade,
  entry_date  date  not null,

  -- Sleep (main sleep of the day; extra logs counted as naps)
  minutes_asleep       int,
  minutes_awake        int,
  time_in_bed_minutes  int,
  sleep_efficiency     int,
  -- NULL on classic (non-stages) sleep logs from older trackers
  minutes_deep         int,
  minutes_light        int,
  minutes_rem          int,
  minutes_wake         int,
  nap_count            int,

  -- Heart
  resting_heart_rate   int,
  hrv_daily_rmssd      float,
  hrv_deep_rmssd       float,

  -- Activity
  steps                int,

  raw         jsonb       default '{}'::jsonb,
  fetched_at  timestamptz default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_fitbit_daily_user_date
  on public.fitbit_daily (user_id, entry_date desc);

-- Row-Level Security -------------------------------------------------------
alter table public.fitbit_daily enable row level security;

drop policy if exists "fitbit_daily: select own" on public.fitbit_daily;
drop policy if exists "fitbit_daily: insert own" on public.fitbit_daily;
drop policy if exists "fitbit_daily: update own" on public.fitbit_daily;
drop policy if exists "fitbit_daily: delete own" on public.fitbit_daily;

create policy "fitbit_daily: select own"
  on public.fitbit_daily for select
  using (auth.uid() = user_id);

create policy "fitbit_daily: insert own"
  on public.fitbit_daily for insert
  with check (auth.uid() = user_id);

create policy "fitbit_daily: update own"
  on public.fitbit_daily for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "fitbit_daily: delete own"
  on public.fitbit_daily for delete
  using (auth.uid() = user_id);

-- Verification -------------------------------------------------------------
select tablename, rowsecurity from pg_tables where tablename = 'fitbit_daily';
select policyname, cmd from pg_policies where tablename = 'fitbit_daily' order by policyname;
