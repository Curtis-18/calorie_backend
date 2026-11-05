-- Run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Safe to re-run: every statement is idempotent.
-- Needs the usernames and friends migrations (2026-11-04) to have been run.

-- 1. Each person's notification choices. No row means "all defaults".
create table if not exists public.notification_prefs (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  friend_snaps boolean not null default true,
  reactions boolean not null default true,
  streak_reminders boolean not null default true,
  milestones boolean not null default true,
  meal_nudge_hour smallint check (meal_nudge_hour between 0 and 23),  -- local hour; null = off
  quiet_start smallint not null default 22 check (quiet_start between 0 and 23),
  quiet_end smallint not null default 8 check (quiet_end between 0 and 23),
  utc_offset_minutes integer not null default 0 check (utc_offset_minutes between -840 and 840),
  paused_until timestamptz,
  updated_at timestamptz not null default now()
);

-- 2. Phones that can receive a push (a token from Apple/Firebase). One person
--    can have several; a token that moves to another account is reassigned.
create table if not exists public.device_tokens (
  token text primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  platform text not null check (platform in ('ios', 'android')),
  created_at timestamptz not null default now(),
  last_seen timestamptz not null default now()
);
create index if not exists device_tokens_user_idx on public.device_tokens (user_id);

-- 3. What was sent (or would have been, in dry-run mode). Used for the daily
--    cap and to stop the same reminder going out twice. Old rows are cleaned up.
create table if not exists public.notification_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null,
  title text not null,
  body text not null,
  status text not null,            -- sent | dry_run | failed
  dedupe_key text,
  created_at timestamptz not null default now()
);
create index if not exists notification_log_user_idx on public.notification_log (user_id, created_at desc);
create unique index if not exists notification_log_dedupe_idx
  on public.notification_log (user_id, dedupe_key) where dedupe_key is not null;

alter table public.notification_prefs enable row level security;
alter table public.device_tokens      enable row level security;
alter table public.notification_log   enable row level security;
