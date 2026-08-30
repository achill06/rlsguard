-- recipe sharing app, vibe-coded, second pass after "make it work"

create table if not exists public.recipes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  created_at timestamptz default now()
);

alter table public.recipes enable row level security;

create policy "public read"
  on public.recipes
  for select
  using (true);
  -- unconditionally true: every recipe is readable by anyone, including
  -- ones the user may have expected to be private.

create policy "update recipes"
  on public.recipes
  for update
  using (title is not null)
  with check (title is not null);
  -- checks that a title exists, never checks who the caller is. Any
  -- authenticated user can update any recipe's title.
