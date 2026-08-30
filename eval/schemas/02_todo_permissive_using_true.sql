-- todo app, vibe-coded
-- RLS was "turned on" because the platform nagged about it, but the
-- policies were copied from a tutorial and never adjusted.

create table if not exists public.todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  completed boolean default false,
  created_at timestamptz default now()
);

alter table public.todos enable row level security;

create policy "Allow all access"
  on public.todos
  for select
  using (true);

create policy "Allow all insert"
  on public.todos
  for insert
  with check (true);

-- RLS is technically "on" but both policies are unconditionally true, so
-- every row is readable and any row can be inserted regardless of caller.
