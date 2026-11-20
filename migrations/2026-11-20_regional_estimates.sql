-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- Roadmap R8.2 (regional dishes):
--  * user_prefs: where the person mostly eats, as context for photo scans.
--    No row = no hint, so nothing changes for anyone who doesn't pick one.
--  * food_log_estimates: marks a logged entry whose numbers are an estimate
--    (a dish with no database match). Its own table, like food_log_nutrients,
--    so a backend deployed before this is run can still log food.

create table if not exists public.user_prefs (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  region text,
  updated_at timestamptz not null default now()
);

alter table public.user_prefs enable row level security;

create table if not exists public.food_log_estimates (
  log_id text primary key references public.food_logs(id) on delete cascade,
  basis text not null
);

alter table public.food_log_estimates enable row level security;

-- Check: both should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relname in ('user_prefs', 'food_log_estimates');
