-- recipe sharing app, vibe-coded
-- comments feature bolted on later. The generated policies reference real
-- columns and look like access control at a glance, but neither one
-- actually checks who the caller is.

create table if not exists public.recipes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  created_at timestamptz default now()
);

alter table public.recipes enable row level security;

create policy "Users can view own recipes"
  on public.recipes
  for select
  using (auth.uid() = user_id);

create table if not exists public.recipe_comments (
  id uuid primary key default gen_random_uuid(),
  recipe_id uuid references public.recipes(id) not null,
  user_id uuid references auth.users(id) not null,
  comment text not null,
  created_at timestamptz default now()
);

alter table public.recipe_comments enable row level security;

create policy "select comments"
  on public.recipe_comments
  for select
  using (recipe_id is not null);
  -- always true for any existing row (recipe_id is NOT NULL constrained),
  -- reads like a check but enforces nothing about the caller.

create policy "insert comments"
  on public.recipe_comments
  for insert
  with check (comment is not null);
  -- checks that a comment has content, not who is allowed to post it.
  -- never references auth.uid(), so any authenticated user can comment
  -- as any other user_id.
