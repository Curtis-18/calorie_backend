-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- Recipe collections, Highlights and sharing a recipe with a friend
-- (roadmap P3.4 / P3.5). Needs 2026-11-18_recipes.sql to have been run.
-- Until this is run: collections and sharing answer "couldn't save", and chat
-- shows a shared recipe as plain text. Nothing else is affected.

create table if not exists public.collections (
  id uuid primary key,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  name text not null,
  is_default boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists collections_owner_idx on public.collections (owner_id);

create table if not exists public.collection_items (
  collection_id uuid not null references public.collections(id) on delete cascade,
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  added_at timestamptz not null default now(),
  primary key (collection_id, recipe_id)
);

create table if not exists public.recipe_pins (
  user_id uuid not null references public.profiles(id) on delete cascade,
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  position smallint not null,
  primary key (user_id, recipe_id)
);

create table if not exists public.recipe_shares (
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  friend_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (recipe_id, friend_id)
);
create index if not exists recipe_shares_friend_idx on public.recipe_shares (friend_id);

create table if not exists public.message_attachments (
  message_id uuid primary key references public.messages(id) on delete cascade,
  attachment jsonb not null
);

alter table public.collections enable row level security;
alter table public.collection_items enable row level security;
alter table public.recipe_pins enable row level security;
alter table public.recipe_shares enable row level security;
alter table public.message_attachments enable row level security;

-- Check: all five should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('collections', 'collection_items', 'recipe_pins', 'recipe_shares', 'message_attachments');
