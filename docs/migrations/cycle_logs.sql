-- ──────────────────────────────────────────────────────────────────────────
--  cycle_logs — period start dates, for the Personalized Insights cycle lens
--  Run in the Supabase SQL editor. Idempotent; safe to run twice.
--
--  WHY THIS TABLE EXISTS: nothing in Mirra's schema recorded a menstrual cycle.
--  public.users carries sex / date_of_birth / gender_identity and nothing else
--  relevant; oura_daily stores sleep, readiness, activity, HRV and resting HR —
--  Oura's own cycle features are not among the fields oura.py syncs. So the
--  "hormonal cycle as a category" lens had no possible input. This gives it the
--  smallest one that works: the days the user says a period started. Phase is
--  derived at read time (insights_data.cycle_day_and_phase), never stored, so
--  correcting a logged date immediately re-derives every phase that depends
--  on it.
--
--  One row per (user, start date). The table holds dates only — no symptoms, no
--  flow, no notes — because that is all the lens needs, and health data you
--  don't collect is health data you can't leak.
--
--  Identity + RLS follow MIR-56: keyed on public.users(id), which is now
--  auth.users(id), with auth.uid() policies matching every other per-user table.
-- ──────────────────────────────────────────────────────────────────────────

create table if not exists public.cycle_logs (
  user_id     uuid        not null references public.users(id) on delete cascade,
  entry_date  date        not null,          -- first day of a period
  created_at  timestamptz not null default now(),
  primary key (user_id, entry_date)
);

create index if not exists idx_cycle_logs_user_date
  on public.cycle_logs (user_id, entry_date desc);

alter table public.cycle_logs enable row level security;

drop policy if exists "cycle_logs: select own" on public.cycle_logs;
drop policy if exists "cycle_logs: insert own" on public.cycle_logs;
drop policy if exists "cycle_logs: update own" on public.cycle_logs;
drop policy if exists "cycle_logs: delete own" on public.cycle_logs;

create policy "cycle_logs: select own" on public.cycle_logs
  for select using (auth.uid() = user_id);
create policy "cycle_logs: insert own" on public.cycle_logs
  for insert with check (auth.uid() = user_id);
create policy "cycle_logs: update own" on public.cycle_logs
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "cycle_logs: delete own" on public.cycle_logs
  for delete using (auth.uid() = user_id);

-- Verify: with the anon key and no session this must return 0 rows.
--   select count(*) from public.cycle_logs;
