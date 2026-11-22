-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the snaps and stories migrations.

-- Where a caption sits on a photo, as a fraction of the photo's height from
-- the top (0 = top edge, 1 = bottom edge): people drag the caption strip up or
-- down before they send. Own tables (like profile_avatars and message_quotes),
-- so an app or a server without them still works: the caption then sits at the
-- default spot.
create table if not exists public.snap_caption_positions (
  snap_id uuid primary key references public.snaps(id) on delete cascade,
  y real not null check (y >= 0 and y <= 1)
);

create table if not exists public.story_caption_positions (
  story_id uuid primary key references public.stories(id) on delete cascade,
  y real not null check (y >= 0 and y <= 1)
);

alter table public.snap_caption_positions enable row level security;
alter table public.story_caption_positions enable row level security;

-- Check: should list both with rls_enabled = true.
select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('snap_caption_positions', 'story_caption_positions');
