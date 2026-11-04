-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
--
-- Usernames are how friends find each other. They are optional in the
-- database so existing users keep working; the app asks each of them to pick
-- one the next time they sign in.

alter table public.profiles add column if not exists username text;
alter table public.profiles add column if not exists username_changed_at timestamptz;

-- Unique ignoring case, so "Sam" and "sam" can't both exist. Format rules
-- live in the backend; this only guards against races.
create unique index if not exists profiles_username_lower_key
  on public.profiles (lower(username));

-- Check: how many users still need to pick one.
select count(*) filter (where username is null) as without_username,
       count(*) as total
from public.profiles;
