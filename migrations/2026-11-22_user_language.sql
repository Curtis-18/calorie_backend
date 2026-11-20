-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- Languages: the language each person last used the app in, so a push
-- notification can be written in it. No row = English. Its own table, so a
-- backend deployed before this is run only means notifications stay in English.

create table if not exists public.user_language (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  language text not null,
  updated_at timestamptz not null default now()
);

alter table public.user_language enable row level security;

-- Check: should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relname = 'user_language';
