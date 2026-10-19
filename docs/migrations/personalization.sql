-- Personalization settings on public.users, edited in Profile → Personalization.
--   insight_style — how insights are presented (read/written by insight_style.py)
--   focus_areas   — which areas Simples leads with (read/written by focus_areas.py)
-- Until this runs, the app falls back to session state and defaults, so it is
-- safe to deploy first.
--
-- Run in the Supabase SQL editor. Existing users-table RLS policies already
-- cover select/update of a user's own row, so no new policy is needed.

alter table public.users
  add column if not exists insight_style text not null default 'hybrid';

alter table public.users drop constraint if exists users_insight_style_check;
alter table public.users
  add constraint users_insight_style_check
  check (insight_style in ('data_driven', 'hybrid', 'insight_focused'));

-- Empty means "not chosen yet": the app then infers areas from the inquiry
-- answers and the data the user has. No check constraint, because the list of
-- areas is expected to grow.
alter table public.users
  add column if not exists focus_areas text[] not null default '{}';

-- Verification -------------------------------------------------------------
select column_name, data_type, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'users'
  and column_name in ('insight_style', 'focus_areas');
