-- Run once in the Supabase SQL editor. Safe to re-run.
--
-- House recipes (roadmap P3.1): a person's own recipes, the ingredients
-- their nutrition is computed from, and a quiet event log. Private to the
-- owner. Until this is run the recipe routes answer "couldn't save" and
-- nothing else in the app is affected.

create table if not exists public.recipes (
  id uuid primary key,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  title text not null,
  description text,
  servings numeric(7,2) not null default 1 check (servings > 0),
  visibility text not null default 'private' check (visibility in ('private', 'friends', 'public')),
  region text,
  tags jsonb not null default '[]'::jsonb,
  steps jsonb not null default '[]'::jsonb,
  calories_per_serving integer not null check (calories_per_serving >= 0),
  protein_g double precision not null default 0,
  carbs_g double precision not null default 0,
  fat_g double precision not null default 0,
  nutrients jsonb,
  basis text not null default 'ingredients' check (basis in ('ingredients', 'manual', 'ai_estimate')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);
create index if not exists recipes_owner_idx on public.recipes (owner_id);

create table if not exists public.recipe_ingredients (
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  position smallint not null,
  name text not null,
  grams numeric(9,2) not null check (grams > 0),
  fdc_id bigint,
  source text not null check (source in ('usda', 'manual')),
  calories_per_100g double precision not null,
  protein_g_per_100g double precision not null default 0,
  carbs_g_per_100g double precision not null default 0,
  fat_g_per_100g double precision not null default 0,
  nutrients_per_100g jsonb,
  is_baseline boolean not null default false,
  primary key (recipe_id, position)
);

create table if not exists public.recipe_events (
  id uuid primary key default gen_random_uuid(),
  recipe_id uuid not null references public.recipes(id) on delete cascade,
  actor_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null check (kind in ('save', 'log', 'share', 'cook')),
  log_entry_id text,
  created_at timestamptz not null default now()
);
create index if not exists recipe_events_recipe_kind_idx on public.recipe_events (recipe_id, kind, created_at);

-- The app talks to the backend, never to these tables directly.
alter table public.recipes enable row level security;
alter table public.recipe_ingredients enable row level security;
alter table public.recipe_events enable row level security;

-- Check: all three should say rls_enabled = true.
select relname as table_name, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('recipes', 'recipe_ingredients', 'recipe_events');

-- For sizing the creator program later (roadmap P8): logs per recipe per week
-- and how many different people logged it.
-- select recipe_id, date_trunc('week', created_at) as week,
--        count(*) as logs, count(distinct actor_id) as distinct_loggers
-- from public.recipe_events where kind = 'log' group by 1, 2 order by 2 desc, 3 desc;
