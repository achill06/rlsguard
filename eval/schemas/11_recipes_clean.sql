-- recipe sharing app, RLS configured correctly, no planted issues

create table if not exists public.recipes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  ingredients text,
  instructions text,
  created_at timestamptz default now()
);

alter table public.recipes enable row level security;

create policy "select own recipes"
  on public.recipes
  for select
  using (auth.uid() = user_id);

create policy "insert own recipes"
  on public.recipes
  for insert
  with check (auth.uid() = user_id);

create policy "update own recipes"
  on public.recipes
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "delete own recipes"
  on public.recipes
  for delete
  using (auth.uid() = user_id);

revoke all on public.recipes from anon;
