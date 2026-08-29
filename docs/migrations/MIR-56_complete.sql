-- ──────────────────────────────────────────────────────────────────────────
--  MIR-56 · Complete the Supabase Auth move
--
--  Written against production as found on 2026-08-28 (evening HST), after Kim
--  ran steps 1–3 of MIR-56_supabase_auth.sql: public.users is keyed on
--  auth.users (no password_hash), the MIR-3 tables exist — but
--    * the MIR-1 profile / onboarding columns were never added, so every
--      onboarding marker update in the app matches nothing;
--    * nothing creates the profile row when an account signs up;
--    * RLS is still OFF (the anon key reads oura_daily / oura_oauth_states).
--  This script finishes the job. Idempotent — safe to run twice. It does not
--  touch foreign keys or existing rows.
-- ──────────────────────────────────────────────────────────────────────────

begin;

-- ── 1. Profile + onboarding columns (MIR-1 story #14 / PR #53) ─────────────
alter table public.users
  add column if not exists email                 text,
  add column if not exists phone                 text,
  add column if not exists date_of_birth         date,
  add column if not exists sex                   text,
  add column if not exists gender_identity       text,
  add column if not exists location              text,
  add column if not exists timezone              text        default 'Pacific/Honolulu',
  add column if not exists occupation            text,
  -- every profile field is optional, so completion needs explicit markers
  add column if not exists has_seen_intro        boolean     not null default false,
  add column if not exists profile_completed_at  timestamptz,
  add column if not exists inquiry_completed_at  timestamptz,
  -- INTERIM: inquiry answers as jsonb until the goals schema (#20) lands
  add column if not exists inquiry_responses     jsonb;

create unique index if not exists idx_users_email
  on public.users (lower(email))
  where email is not null and email <> '';

-- ── 2. Profile row is created by the database, not the app ─────────────────
-- With "Confirm email" on, sign-up returns no session, so the app has nothing
-- to write public.users with (RLS needs auth.uid()). Do it server-side.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.users (id, username, email)
  values (
    new.id,
    coalesce(nullif(new.raw_user_meta_data ->> 'username', ''), split_part(new.email, '@', 1)),
    new.email
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Accounts that signed up before the trigger existed: give them their row,
-- and fill in email on rows that already exist.
insert into public.users (id, username, email)
select id,
       coalesce(nullif(raw_user_meta_data ->> 'username', ''), split_part(email, '@', 1)),
       email
  from auth.users
on conflict (id) do update set email = excluded.email
                          where public.users.email is null;

-- Accounts created while "Confirm email" was on and the link pointed at
-- localhost could never confirm. Confirmation is off now; let them in.
update auth.users
   set email_confirmed_at = now()
 where email_confirmed_at is null;

-- ── 3. RLS on every per-user table (MIR-56 step 4, unchanged) ──────────────
alter table public.users             enable row level security;
alter table public.reflections       enable row level security;
alter table public.oura_daily        enable row level security;
alter table public.oura_credentials  enable row level security;
alter table public.oura_oauth_states enable row level security;
alter table public.connections       enable row level security;
alter table public.oauth_states      enable row level security;
alter table public.spotify_daily     enable row level security;

drop policy if exists "users: select own" on public.users;
drop policy if exists "users: update own" on public.users;
drop policy if exists "users: insert own" on public.users;
create policy "users: select own" on public.users for select using (auth.uid() = id);
create policy "users: update own" on public.users for update using (auth.uid() = id) with check (auth.uid() = id);
create policy "users: insert own" on public.users for insert with check (auth.uid() = id);

do $$
declare t text;
begin
  foreach t in array array['reflections','oura_daily','oura_credentials',
                           'oura_oauth_states','connections','oauth_states','spotify_daily']
  loop
    execute format('drop policy if exists "%s: select own" on public.%I', t, t);
    execute format('drop policy if exists "%s: insert own" on public.%I', t, t);
    execute format('drop policy if exists "%s: update own" on public.%I', t, t);
    execute format('drop policy if exists "%s: delete own" on public.%I', t, t);
    execute format('create policy "%s: select own" on public.%I for select using (auth.uid() = user_id)', t, t);
    execute format('create policy "%s: insert own" on public.%I for insert with check (auth.uid() = user_id)', t, t);
    execute format('create policy "%s: update own" on public.%I for update using (auth.uid() = user_id) with check (auth.uid() = user_id)', t, t);
    execute format('create policy "%s: delete own" on public.%I for delete using (auth.uid() = user_id)', t, t);
  end loop;
end $$;

-- Legacy table from the first Oura spike: RLS on, no policies, nothing reads it.
alter table if exists public.oura_tokens enable row level security;

commit;

-- ── Verify ─────────────────────────────────────────────────────────────────
--   select tablename, rowsecurity from pg_tables where schemaname = 'public';  -- all true
--   select count(*) from public.users;   -- = select count(*) from auth.users
-- With the anon key and no session, every table must return 0 rows.
