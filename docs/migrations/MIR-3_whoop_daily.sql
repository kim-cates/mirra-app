-- ---------------------------------------------------------------------------
--  Mirra: Whoop daily rollup (third connector)
--  Run in the Supabase SQL editor. Idempotent. ASCII-only on purpose: pasting
--  box-drawing characters through the clipboard into the SQL editor garbles.
--
--  Identity: keyed on auth.users(id), like oura_daily and everything else after
--  the MIR-56 Supabase Auth migration. The app writes with the member's own
--  session, so RLS on auth.uid() is what actually protects the row.
-- ---------------------------------------------------------------------------

create table if not exists public.whoop_daily (
  user_id     uuid  not null references auth.users(id) on delete cascade,
  entry_date  date  not null,

  -- Recovery (the headline Whoop number, 0-100) and its inputs
  recovery_score       int,
  hrv_rmssd_milli      float,
  resting_heart_rate   int,
  spo2_percentage      float,
  skin_temp_celsius    float,

  -- Sleep performance. Stage totals are milliseconds, as Whoop returns them.
  sleep_performance_percentage   float,
  sleep_efficiency_percentage    float,
  sleep_consistency_percentage   float,
  respiratory_rate               float,
  total_in_bed_time_milli        bigint,
  total_awake_time_milli         bigint,
  total_light_sleep_time_milli   bigint,
  total_slow_wave_sleep_time_milli bigint,
  total_rem_sleep_time_milli     bigint,
  sleep_cycle_count              int,
  disturbance_count              int,
  nap_count                      int,

  -- Day strain, from the physiological cycle that starts on this day
  strain              float,
  kilojoule           float,
  average_heart_rate  int,
  max_heart_rate      int,

  -- Original payloads (sleep / recovery / cycle / naps), for future metrics
  raw         jsonb       default '{}'::jsonb,
  fetched_at  timestamptz default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_whoop_daily_user_date
  on public.whoop_daily (user_id, entry_date desc);

-- Row-Level Security -------------------------------------------------------
alter table public.whoop_daily enable row level security;

drop policy if exists "whoop_daily: select own" on public.whoop_daily;
drop policy if exists "whoop_daily: insert own" on public.whoop_daily;
drop policy if exists "whoop_daily: update own" on public.whoop_daily;
drop policy if exists "whoop_daily: delete own" on public.whoop_daily;

create policy "whoop_daily: select own"
  on public.whoop_daily for select
  using (auth.uid() = user_id);

create policy "whoop_daily: insert own"
  on public.whoop_daily for insert
  with check (auth.uid() = user_id);

create policy "whoop_daily: update own"
  on public.whoop_daily for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "whoop_daily: delete own"
  on public.whoop_daily for delete
  using (auth.uid() = user_id);

-- Verification -------------------------------------------------------------
select tablename, rowsecurity from pg_tables where tablename = 'whoop_daily';
select policyname, cmd from pg_policies where tablename = 'whoop_daily' order by policyname;
