-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the movement migration (2026-11-26_movement.sql).

-- How many reps someone did of each move in a guided workout, so the player can
-- show "Last time: 12" next time (NEXT_STEPS step 9b). Private to the person,
-- never shown to friends. Its own table: until this is run, workouts save and
-- play exactly as before, just without "Last time".
create table if not exists public.movement_sets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  -- Deleted with the session it belongs to.
  log_id uuid not null references public.movement_logs(id) on delete cascade,
  -- A move id from the server's library (app/services/workouts.py EXERCISES).
  move text not null,
  reps integer not null check (reps between 1 and 500),
  created_at timestamptz not null default now()
);

create index if not exists movement_sets_user_idx on public.movement_sets (user_id, created_at desc);
create index if not exists movement_sets_log_idx on public.movement_sets (log_id);

-- Only the server (service role) reads and writes it.
alter table public.movement_sets enable row level security;

-- Check: should list movement_sets with rls_enabled = true.
select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace and relname = 'movement_sets';
