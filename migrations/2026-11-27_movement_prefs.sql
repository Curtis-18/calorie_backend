-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- Roadmap R9 / D11 (decision made 26 Nov 2026: yes, as an opt-in choice):
-- a person may choose to add a share of their logged movement to today's
-- calorie plan. Off (0) for everyone until they turn it on. Its own table, so a
-- backend deployed before this is run simply treats everyone as "off".
create table if not exists public.movement_prefs (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  -- The share of the rough estimate added to today's plan: 0 (off) to 50.
  eat_back_percent smallint not null default 0 check (eat_back_percent between 0 and 50),
  updated_at timestamptz not null default now()
);

alter table public.movement_prefs enable row level security;

select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace and relname = 'movement_prefs';
