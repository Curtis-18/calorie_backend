-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the friends (2026-11-04) and snaps (2026-11-05) migrations to have
-- been run: the photos go in the same private 'snaps' bucket.

-- 1. Profile pictures: one row per person who has set one.
create table if not exists public.profile_avatars (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  storage_path text not null,                -- <user>/avatar-<random>.jpg in the 'snaps' bucket
  updated_at timestamptz not null default now()
);

-- 2. A story: one food photo all of a person's friends can see for 24 hours.
create table if not exists public.stories (
  id uuid primary key,                       -- chosen by the app, so a retry can't post twice
  user_id uuid not null references public.profiles(id) on delete cascade,
  storage_path text not null,                -- <user>/story-<id>.jpg in the 'snaps' bucket
  caption text check (caption is null or char_length(caption) <= 120),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index if not exists stories_user_idx on public.stories (user_id);
create index if not exists stories_expires_idx on public.stories (expires_at);

-- 3. Who has seen a story, and how they reacted.
create table if not exists public.story_views (
  story_id uuid not null references public.stories(id) on delete cascade,
  viewer_id uuid not null references public.profiles(id) on delete cascade,
  viewed_at timestamptz not null default now(),
  reaction text,
  reacted_at timestamptz,
  primary key (story_id, viewer_id)
);
create index if not exists story_views_viewer_idx on public.story_views (viewer_id);

-- 4. Reports of stories and profile pictures (App Store guideline 1.2).
--    Deliberately no foreign key to the content: a report must outlive it.
create table if not exists public.content_reports (
  id uuid primary key default gen_random_uuid(),
  reporter_id uuid not null references public.profiles(id) on delete cascade,
  reported_user_id uuid not null,
  kind text not null check (kind in ('story', 'avatar')),
  subject_id uuid,
  reason text,
  created_at timestamptz not null default now()
);

-- 5. Row Level Security, as on every other table (the backend bypasses it).
alter table public.profile_avatars enable row level security;
alter table public.stories         enable row level security;
alter table public.story_views     enable row level security;
alter table public.content_reports enable row level security;

-- Check: four tables, each with rls_enabled = t.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('profile_avatars', 'stories', 'story_views', 'content_reports')
order by relname;
