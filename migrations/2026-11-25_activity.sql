-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.

-- The in-app Notifications list: a row each time a friend sends you a bite or
-- reacts to one of yours. Separate from push notifications (which only reach a
-- device that turned them on): this list exists for everybody.
-- The server treats a missing table as "nothing yet", so deploying before this
-- is run breaks nothing, it just shows an empty list.
create table if not exists public.activity (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  actor_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null check (kind in ('bite', 'reaction')),
  emoji text,
  -- The same event is never recorded twice for one person (a retry, a repeat).
  dedupe_key text,
  created_at timestamptz not null default now(),
  seen_at timestamptz
);

create index if not exists activity_user_recent_idx on public.activity (user_id, created_at desc);
create unique index if not exists activity_dedupe_idx on public.activity (user_id, dedupe_key) where dedupe_key is not null;

-- Only the server (service role) reads and writes it.
alter table public.activity enable row level security;

-- Check: should list 'activity' with rls_enabled = true.
select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace and relname = 'activity';
