-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the messages migration (2026-11-14).

-- "Reply to this message": a message may quote one earlier message of the same
-- conversation. Its own table (like message_attachments), so an app or a
-- server without it still shows every message as plain text.
create table if not exists public.message_quotes (
  message_id uuid primary key references public.messages(id) on delete cascade,
  -- Set to null when the quoted message is unsent: the quote then reads
  -- "original message deleted" and no copy of the text is kept anywhere.
  quoted_id uuid references public.messages(id) on delete set null
);

-- Deleting a message looks up the quotes that point at it.
create index if not exists message_quotes_quoted_idx
  on public.message_quotes (quoted_id) where quoted_id is not null;

alter table public.message_quotes enable row level security;

-- Check: should list 'message_quotes' with rls_enabled = true.
select relname, relrowsecurity as rls_enabled from pg_class
where relnamespace = 'public'::regnamespace and relname = 'message_quotes';
