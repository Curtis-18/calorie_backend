-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the friends migration (2026-11-04) and the avatars/stories one
-- (2026-11-14), which creates content_reports.

-- Direct messages between two friends. Text only.
create table if not exists public.messages (
  id uuid primary key,                       -- chosen by the app, so a retry can't send twice
  sender_id uuid not null references public.profiles(id) on delete cascade,
  recipient_id uuid not null references public.profiles(id) on delete cascade,
  body text not null check (char_length(body) between 1 and 1000),
  created_at timestamptz not null default now(),
  read_at timestamptz,                       -- when the recipient opened the conversation
  check (sender_id <> recipient_id)
);

-- A conversation, newest first (looked up once per direction).
create index if not exists messages_thread_idx
  on public.messages (sender_id, recipient_id, created_at desc);
-- "How many unread do I have?" only ever looks at the unread ones.
create index if not exists messages_unread_idx
  on public.messages (recipient_id, sender_id) where read_at is null;

-- Reports of a message go in the same table as story and picture reports,
-- which only allowed those two kinds until now.
alter table public.content_reports drop constraint if exists content_reports_kind_check;
alter table public.content_reports
  add constraint content_reports_kind_check check (kind in ('story', 'avatar', 'message'));

-- Row Level Security, as on every other table (the backend bypasses it).
alter table public.messages enable row level security;

-- Check: should list 'messages' with rls_enabled = true.
select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace and relname = 'messages';
