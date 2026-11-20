-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- Roadmap R8.3: recipe photos. Position 0 is the cover photo, 1-5 are the
-- carousel slides (ingredients, steps, the finished dish). Files live in the
-- private storage bucket and are only ever opened through short-lived signed
-- links. Until this is run, photo routes answer "not available" and recipes
-- work exactly as before. Also lets people report a recipe (App Store 1.2).

create table if not exists public.recipe_media (
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  position smallint not null check (position between 0 and 5),
  path text not null,
  caption text,
  created_at timestamptz not null default now(),
  primary key (recipe_id, position)
);

alter table public.recipe_media enable row level security;

alter table public.content_reports drop constraint if exists content_reports_kind_check;
alter table public.content_reports
  add constraint content_reports_kind_check check (kind in ('story', 'avatar', 'message', 'recipe'));
