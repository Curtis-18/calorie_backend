-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
--
-- A per-person, per-day counter for each AI feature (photo scans first).
-- It only measures for now: nothing is limited until the Pro tier exists
-- (handover: PRODUCT ROADMAP P0.5 / P6). Until this is run the app works as
-- before and usage is simply not counted.

create table if not exists public.ai_usage (
  user_id uuid not null references public.profiles(id) on delete cascade,
  day date not null,                 -- the person's own (device-local) date
  feature text not null,             -- e.g. 'photo_scan'
  count integer not null default 0,
  primary key (user_id, day, feature)
);

alter table public.ai_usage enable row level security;

-- Check: should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relname = 'ai_usage';
