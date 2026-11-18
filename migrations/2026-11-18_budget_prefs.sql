-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- Weekly calorie budget choices (roadmap P2). No row = the plain daily target,
-- so until this is run (or for anyone who never opts in) nothing changes.

create table if not exists public.budget_prefs (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  mode text not null default 'daily' check (mode in ('daily', 'weekly')),
  week_start_day smallint not null default 0 check (week_start_day between 0 and 6),
  weights jsonb,
  nudges boolean not null default false,
  dismissed_weeks jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.budget_prefs enable row level security;

-- Check: should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relname = 'budget_prefs';
