-- ──────────────────────────────────────────────────────────────────────────
--  MIR-56 · Move identity onto Supabase Auth and enable RLS  (Route B)
--
--  ⚠ DESTRUCTIVE, RUN ONCE, IN ORDER, AFTER A FULL BACKUP.
--  Export users / reflections / oura_* from Supabase before starting.
--
--  Context: the app authenticates against custom public.users (SHA256), so
--  auth.uid() is null and RLS matches nothing — which is why RLS is off and the
--  client-side anon key can currently read every user's data. This migration
--  makes auth.users the single identity and turns RLS on everywhere.
--
--  PREREQUISITE (done outside SQL, see scripts/migrate_users_to_auth.py):
--  every row in public.users must already have auth_id filled in, pointing at a
--  real auth.users row. Step 1 adds the column; the script fills it; then
--  continue from step 2.
-- ──────────────────────────────────────────────────────────────────────────

-- ── STEP 1 — add the link column, then STOP and run the script ─────────────
alter table public.users
  add column if not exists auth_id uuid references auth.users(id) on delete cascade;

create unique index if not exists idx_users_auth_id on public.users (auth_id);

-- Verify before continuing (must return 0):
--   select count(*) from public.users where auth_id is null;


-- ── STEP 2 — re-key every per-user table onto the auth id ──────────────────
-- Runs as one transaction: either the whole identity swap lands, or none of it.
begin;

-- Drop FKs so the ids can be rewritten.
alter table public.reflections        drop constraint if exists reflections_user_id_fkey;
alter table public.oura_daily         drop constraint if exists oura_daily_user_id_fkey;
alter table public.oura_credentials   drop constraint if exists oura_credentials_user_id_fkey;
alter table public.oura_oauth_states  drop constraint if exists oura_oauth_states_user_id_fkey;

-- Rewrite child rows: old users.id -> auth_id.
update public.reflections       t set user_id = u.auth_id from public.users u where t.user_id = u.id;
update public.oura_daily        t set user_id = u.auth_id from public.users u where t.user_id = u.id;
update public.oura_credentials  t set user_id = u.auth_id from public.users u where t.user_id = u.id;
update public.oura_oauth_states t set user_id = u.auth_id from public.users u where t.user_id = u.id;

-- Re-key the users table itself: id becomes the auth id.
alter table public.users drop constraint if exists users_pkey cascade;
update public.users set id = auth_id where id is distinct from auth_id;
alter table public.users add primary key (id);
alter table public.users
  add constraint users_id_fkey foreign key (id) references auth.users(id) on delete cascade;
alter table public.users drop column auth_id;

-- Passwords now live in auth.users; the local hash must not linger.
alter table public.users drop column if exists password_hash;

-- Restore FKs, now pointing at the auth-backed users table.
alter table public.reflections
  add constraint reflections_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;
alter table public.oura_daily
  add constraint oura_daily_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;
alter table public.oura_credentials
  add constraint oura_credentials_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;
alter table public.oura_oauth_states
  add constraint oura_oauth_states_user_id_fkey foreign key (user_id) references public.users(id) on delete cascade;

commit;


-- ── STEP 3 — MIR-3 tables, now on the auth identity ────────────────────────
-- Supersedes the public.users variant merged in #55.
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


-- ── STEP 4 — RLS on every per-user table ───────────────────────────────────
-- This is the point of the whole migration: the anon key can no longer read
-- another user's rows, because auth.uid() now resolves to a real identity.
alter table public.users             enable row level security;
alter table public.reflections       enable row level security;
alter table public.oura_daily        enable row level security;
alter table public.oura_credentials  enable row level security;
alter table public.oura_oauth_states enable row level security;
alter table public.connections       enable row level security;
alter table public.oauth_states      enable row level security;
alter table public.spotify_daily     enable row level security;

-- users: the row IS the identity, so scope on id.
drop policy if exists "users: select own" on public.users;
drop policy if exists "users: update own" on public.users;
drop policy if exists "users: insert own" on public.users;
create policy "users: select own" on public.users for select using (auth.uid() = id);
create policy "users: update own" on public.users for update using (auth.uid() = id) with check (auth.uid() = id);
create policy "users: insert own" on public.users for insert with check (auth.uid() = id);

-- Every other per-user table: identical shape on user_id.
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


-- ── STEP 5 — verify (run as an ordinary logged-in user, not service_role) ──
--   select count(*) from public.reflections;   -- only your own rows
--   select count(*) from public.users;         -- 1
-- With the anon key and no session, every one of these must return 0 rows.
