-- ──────────────────────────────────────────────────────────────────────────
--  MIR-56 · Fresh start on Supabase Auth
--
--  Replaces the re-key path in MIR-56_supabase_auth.sql for the decision taken
--  on 2026-08-28: the handful of tester accounts re-register instead of being
--  migrated (no password-reset round, scripts/migrate_users_to_auth.py unused).
--
--  Nothing is deleted. The pre-Auth tables move to a `legacy` schema, which
--  PostgREST does not expose — so the anon key stops seeing them, which closes
--  the same hole RLS closes for the new tables. Old rows can be re-attached to
--  a re-registered account with one UPDATE (see the end of this file).
--
--  Run in the Supabase SQL editor as ONE script. Before running:
--    1. Authentication → URL Configuration: Site URL =
--       https://mirra-reflections.streamlit.app ; Redirect URLs +=
--       https://mirra-reflections.streamlit.app/** and http://localhost:8501/**
--    2. Authentication → Providers → Email → "Confirm email" OFF (tester round;
--       Streamlit can't read the token fragment on the confirmation link, so the
--       link only ever brings people back to the sign-in screen)
--  Safe to re-run: the archive step is skipped once public.users has no
--  password_hash column; everything else is `if not exists`.
-- ──────────────────────────────────────────────────────────────────────────

begin;

-- ── STEP 1 — archive the pre-Auth tables ───────────────────────────────────
create schema if not exists legacy;
revoke all on schema legacy from anon, authenticated;

do $$
declare t text;
begin
  -- password_hash only exists on the custom-auth users table: its presence
  -- means the archive hasn't happened yet.
  if exists (select 1 from information_schema.columns
             where table_schema = 'public' and table_name = 'users'
               and column_name = 'password_hash') then
    foreach t in array array['users', 'reflections', 'oura_daily', 'oura_credentials',
                             'oura_oauth_states', 'oura_tokens']
    loop
      if to_regclass('public.' || t) is not null then
        execute format('alter table public.%I set schema legacy', t);
      end if;
    end loop;
  end if;
end $$;


-- ── STEP 2 — profile table keyed on auth.users ─────────────────────────────
-- Includes the MIR-1 profile + onboarding columns (story #14, PR #53) that
-- were drafted against the old table and never applied.
create table if not exists public.users (
  id                    uuid        primary key references auth.users(id) on delete cascade,
  username              text        not null,                 -- display name; email is the login
  email                 text,
  created_at            timestamptz not null default now(),

  -- Profile (all optional — nothing here blocks account creation)
  phone                 text,
  date_of_birth         date,
  sex                   text,
  gender_identity       text,
  location              text,
  timezone              text        default 'Pacific/Honolulu',
  occupation            text,

  -- Onboarding state: every profile field is optional, so completion can't be
  -- inferred from the data — it needs explicit markers.
  has_seen_intro        boolean     not null default false,
  profile_completed_at  timestamptz,
  inquiry_completed_at  timestamptz,
  -- INTERIM: inquiry answers as jsonb until the goals schema (#20) lands.
  inquiry_responses     jsonb
);

create unique index if not exists idx_users_email
  on public.users (lower(email))
  where email is not null and email <> '';

-- Create the profile row the moment an auth account exists. The app cannot do
-- this itself while "Confirm email" is on (sign-up returns no session, and RLS
-- needs auth.uid()); without the row every onboarding marker update matches
-- nothing and the user is walked through onboarding on every sign-in.
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


-- ── STEP 3 — per-user tables, empty, same shape as production ──────────────
-- `like legacy.<table> including all` copies columns, defaults, NOT NULL/CHECK
-- constraints and indexes exactly as they exist in production (the oura tables
-- were created by hand and have columns migrations.sql never listed). Foreign
-- keys are not copied, so they are re-added against the new users table. The
-- explicit DDL is the fallback for a project with no legacy tables.
do $$
begin
  if to_regclass('public.reflections') is null then
    if to_regclass('legacy.reflections') is not null then
      execute 'create table public.reflections (like legacy.reflections including all)';
    else
      -- Derived from app.py save_reflection(); the legacy copy is authoritative.
      execute $ddl$
        create table public.reflections (
          id          uuid        primary key default gen_random_uuid(),
          user_id     uuid        not null,
          entry_date  date        not null,
          content     text,
          mood        real,
          keywords    jsonb       default '[]'::jsonb,
          feelings    jsonb       default '[]'::jsonb,
          created_at  timestamptz default now(),
          updated_at  timestamptz,
          unique (user_id, entry_date)
        )
      $ddl$;
    end if;
  end if;

  if to_regclass('public.oura_daily') is null then
    if to_regclass('legacy.oura_daily') is not null then
      execute 'create table public.oura_daily (like legacy.oura_daily including all)';
    else
      execute $ddl$
        create table public.oura_daily (
          user_id              uuid        not null,
          entry_date           date        not null,
          sleep_score          int,
          readiness_score      int,
          activity_score       int,
          total_sleep_seconds  int,
          hrv_avg              float,
          resting_hr           int,
          steps                int,
          raw                  jsonb       default '{}'::jsonb,
          fetched_at           timestamptz default now(),
          primary key (user_id, entry_date)
        )
      $ddl$;
      execute 'create index idx_oura_daily_user_date on public.oura_daily (user_id, entry_date desc)';
    end if;
  end if;

  if to_regclass('public.oura_credentials') is null then
    if to_regclass('legacy.oura_credentials') is not null then
      execute 'create table public.oura_credentials (like legacy.oura_credentials including all)';
    else
      execute $ddl$
        create table public.oura_credentials (
          user_id            uuid        primary key,
          access_token       text        not null,
          refresh_token      text,
          token_expires_at   timestamptz,
          auth_type          text        not null check (auth_type in ('pat', 'oauth')),
          connected_at       timestamptz default now()
        )
      $ddl$;
    end if;
  end if;

  if to_regclass('public.oura_oauth_states') is null then
    if to_regclass('legacy.oura_oauth_states') is not null then
      execute 'create table public.oura_oauth_states (like legacy.oura_oauth_states including all)';
    else
      execute $ddl$
        create table public.oura_oauth_states (
          state       text        primary key,
          user_id     uuid        not null,
          created_at  timestamptz not null default now()
        )
      $ddl$;
    end if;
  end if;
end $$;

alter table public.reflections       drop constraint if exists reflections_user_id_fkey;
alter table public.oura_daily        drop constraint if exists oura_daily_user_id_fkey;
alter table public.oura_credentials  drop constraint if exists oura_credentials_user_id_fkey;
alter table public.oura_oauth_states drop constraint if exists oura_oauth_states_user_id_fkey;

alter table public.reflections
  add constraint reflections_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;
alter table public.oura_daily
  add constraint oura_daily_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;
alter table public.oura_credentials
  add constraint oura_credentials_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;
alter table public.oura_oauth_states
  add constraint oura_oauth_states_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;


-- ── STEP 4 — MIR-3 tables on the auth identity (same as MIR-56 step 3) ─────
create table if not exists public.connections (
  user_id           uuid        not null references public.users(id) on delete cascade,
  provider          text        not null,
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

create table if not exists public.oauth_states (
  state       text        primary key,
  provider    text        not null,
  user_id     uuid        not null references public.users(id) on delete cascade,
  created_at  timestamptz not null default now()
);
create index if not exists idx_oauth_states_created on public.oauth_states (created_at);

create table if not exists public.spotify_daily (
  user_id         uuid        not null references public.users(id) on delete cascade,
  entry_date      date        not null,
  track_count     int,
  unique_artists  int,
  listening_ms    bigint,
  valence         float,
  energy          float,
  tempo           float,
  raw             jsonb       default '{}'::jsonb,
  fetched_at      timestamptz default now(),
  primary key (user_id, entry_date)
);
create index if not exists idx_spotify_daily_user_date
  on public.spotify_daily (user_id, entry_date desc);


-- ── STEP 5 — RLS on every per-user table (same as MIR-56 step 4) ───────────
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


-- ── STEP 6 — accounts created before this script ran ───────────────────────
-- Anyone who signed up on the new auth.py while the schema was still the old
-- one has an auth account but no profile row; and if "Confirm email" was on
-- with the broken Site URL, they could never confirm. Fix both.
insert into public.users (id, username, email)
select id,
       coalesce(nullif(raw_user_meta_data ->> 'username', ''), split_part(email, '@', 1)),
       email
  from auth.users
on conflict (id) do nothing;

update auth.users
   set email_confirmed_at = now()
 where email_confirmed_at is null;

commit;


-- ── STEP 7 — verify ────────────────────────────────────────────────────────
--   select count(*) from public.users;                       -- one row per auth account
--   select tablename, rowsecurity from pg_tables where schemaname = 'public';   -- all true
-- With the anon key and no session, every public table must return 0 rows.


-- ── Later, by hand: re-attach a tester's old data to their new account ─────
-- (column order is identical because the new tables were created with LIKE)
--   update legacy.reflections set user_id = '<new auth id>' where user_id = '<old users.id>';
--   insert into public.reflections select * from legacy.reflections where user_id = '<new auth id>';
