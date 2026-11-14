-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
--
-- Fibre, sugar, sodium, iron and calcium for each logged food, as eaten.
-- Stored per entry so past days never change when USDA updates its data.
-- No row = unknown (not zero): manual entries and anything logged before
-- this existed. Until this is run the app works as before, without nutrients.

create table if not exists public.food_log_nutrients (
  log_id text primary key references public.food_logs(id) on delete cascade,
  nutrients jsonb not null     -- e.g. {"fiber_g": 2.4, "iron_mg": 0.3}; a missing key = unknown
);

alter table public.food_log_nutrients enable row level security;

-- Check: should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relname = 'food_log_nutrients';
