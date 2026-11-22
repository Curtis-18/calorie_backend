-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.

-- Roadmap R9 (the Workouts tab): one row each time someone moves, from a
-- guided session or logged by hand. Private to the person, never shown to
-- friends. The server treats a missing table as "nothing yet", so deploying
-- before this is run breaks nothing.
create table if not exists public.movement_logs (
  -- Chosen by the app, so a retry after a lost response cannot log twice.
  id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  -- The person's own (device-local) day, like food logs.
  log_date date not null,
  -- The slice of the weekly "Move plate" this fills.
  slice text not null check (slice in ('strength', 'cardio', 'mobility', 'fun')),
  activity text not null,
  minutes integer not null check (minutes between 1 and 600),
  intensity text not null check (intensity in ('easy', 'moderate', 'hard')),
  -- Set when it came from a guided routine.
  routine_id text,
  source text not null check (source in ('session', 'manual')),
  -- A rough estimate (never added to the day's target by default); null when
  -- the person's weight is not known.
  est_kcal integer check (est_kcal is null or est_kcal between 0 and 5000),
  created_at timestamptz not null default now()
);

create index if not exists movement_logs_user_day_idx on public.movement_logs (user_id, log_date desc);

-- Only the server (service role) reads and writes it.
alter table public.movement_logs enable row level security;

-- Check: should list 'movement_logs' with rls_enabled = true.
select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace and relname = 'movement_logs';
