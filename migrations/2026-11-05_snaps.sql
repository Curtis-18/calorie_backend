-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the usernames and friends migrations (2026-11-04) to have been run.

-- 1. A snap: one food photo sent to one or more friends, gone after 24 hours.
create table if not exists public.snaps (
  id uuid primary key,                       -- chosen by the app, so a retry can't send twice
  sender_id uuid not null references public.profiles(id) on delete cascade,
  storage_path text not null,                -- <sender>/<id>.jpg inside the private 'snaps' bucket
  caption text check (caption is null or char_length(caption) <= 120),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index if not exists snaps_sender_idx on public.snaps (sender_id);
create index if not exists snaps_expires_idx on public.snaps (expires_at);

-- 2. Who received it, whether they opened it, and how they reacted.
create table if not exists public.snap_recipients (
  snap_id uuid not null references public.snaps(id) on delete cascade,
  recipient_id uuid not null references public.profiles(id) on delete cascade,
  viewed_at timestamptz,
  reaction text,
  reacted_at timestamptz,
  primary key (snap_id, recipient_id)
);
create index if not exists snap_recipients_recipient_idx on public.snap_recipients (recipient_id);

-- 3. Streak history. One tiny row per sender, recipient and day, kept after
--    the snap itself is deleted, because a pair streak outlives the 24 hours.
--    'day' is the sender's own (device-local) date.
create table if not exists public.snap_days (
  sender_id uuid not null references public.profiles(id) on delete cascade,
  recipient_id uuid not null references public.profiles(id) on delete cascade,
  day date not null,
  primary key (sender_id, recipient_id, day)
);
create index if not exists snap_days_recipient_idx on public.snap_days (recipient_id, sender_id);

-- 4. Reports (App Store guideline 1.2). Deliberately no foreign key to snaps:
--    the report must outlive the snap's 24 hours.
create table if not exists public.snap_reports (
  id uuid primary key default gen_random_uuid(),
  reporter_id uuid not null references public.profiles(id) on delete cascade,
  reported_user_id uuid not null,
  snap_id uuid,
  reason text,
  created_at timestamptz not null default now()
);

-- 5. Row Level Security, as on every other table (the backend bypasses it).
alter table public.snaps           enable row level security;
alter table public.snap_recipients enable row level security;
alter table public.snap_days       enable row level security;
alter table public.snap_reports    enable row level security;

-- 6. The private bucket the photos live in. 'public = false' means nobody can
--    open a photo without a short-lived signed link from the backend.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('snaps', 'snaps', false, 2097152, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update
  set public = false, file_size_limit = 2097152,
      allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp'];

-- Check: four tables with rls_enabled = t, and the bucket with public = false.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('snaps', 'snap_recipients', 'snap_days', 'snap_reports')
order by relname;
select id, public from storage.buckets where id = 'snaps';
