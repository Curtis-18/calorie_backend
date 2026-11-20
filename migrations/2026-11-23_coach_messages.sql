-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- R8.4 AI coach: the chat history with the coach. Its own table (the coach is
-- not a user, so it is not the friend `messages` table). Deleted with the
-- account. The backend keeps 90 days and has a "Clear conversation" route.
-- A backend deployed before this is run answers the coach routes with
-- "not available" and nothing else changes.

create table if not exists public.coach_messages (
  id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role text not null check (role in ('user', 'coach')),
  body text not null,
  created_at timestamptz not null default now(),
  tokens_in integer,
  tokens_out integer
);

create index if not exists coach_messages_user_created on public.coach_messages (user_id, created_at);

alter table public.coach_messages enable row level security;

-- Check: should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relname = 'coach_messages';
