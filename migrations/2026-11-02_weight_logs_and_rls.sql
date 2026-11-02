-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.

-- 1. Weigh-ins: one per user per day.
create table if not exists public.weight_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  log_date date not null,
  weight_kg double precision not null check (weight_kg > 0 and weight_kg < 700),
  created_at timestamptz not null default now(),
  constraint weight_logs_user_day unique (user_id, log_date)
);
create index if not exists weight_logs_user_id_idx on public.weight_logs (user_id);

-- Existing users: seed their starting point from the weight they onboarded
-- with, so their progress chart isn't empty.
insert into public.weight_logs (user_id, log_date, weight_kg)
select user_id, coalesce(updated_at, now())::date, weight_kg
from public.targets
on conflict (user_id, log_date) do nothing;

-- 2. Row Level Security on every app table.
-- Supabase exposes the public schema through its REST API to anyone holding
-- the anon key, which ships inside the web app. Tables created by
-- create_tables.py had RLS off, so that API could read and write every
-- user's rows. The FastAPI backend connects as the postgres role, which
-- bypasses RLS, so enabling it with no policies changes nothing for the app
-- and closes the public API.
alter table public.profiles       enable row level security;
alter table public.targets        enable row level security;
alter table public.food_logs      enable row level security;
alter table public.insights_cache enable row level security;
alter table public.weight_logs    enable row level security;

-- 3. Check: every row should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('profiles', 'targets', 'food_logs', 'insights_cache', 'weight_logs')
order by relname;
