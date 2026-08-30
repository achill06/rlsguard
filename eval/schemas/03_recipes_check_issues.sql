-- recipe sharing app, vibe-coded
-- SELECT policy looks correct. INSERT and UPDATE were added later, in a
-- rush.

create table if not exists public.recipes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  ingredients text,
  instructions text,
  created_at timestamptz default now()
);

alter table public.recipes enable row level security;

create policy "Users can view own recipes"
  on public.recipes
  for select
  using (auth.uid() = user_id);

create policy "Users can insert own recipes"
  on public.recipes
  for insert
  to authenticated;
  -- INSERT policies have no USING clause to fall back on, so omitting
  -- WITH CHECK here defaults to unrestricted: any authenticated user can
  -- insert a row claiming any user_id, not just their own.

create policy "Users can update own recipes"
  on public.recipes
  for update
  using (auth.uid() = user_id)
  with check (true);
  -- USING correctly restricts which rows can be touched to the caller's
  -- own rows. But note: for UPDATE policies, Postgres would automatically
  -- reuse the USING expression as WITH CHECK if this clause were left out
  -- entirely, which would have been safe. Writing an explicit
  -- WITH CHECK (true) overrides that safe default and reopens the hole,
  -- an owner can update their own row and reassign user_id to someone
  -- else. This is a case where writing something explicit is worse than
  -- writing nothing.
