-- todo app, vibe-coded, "lists" feature added in iteration 2

create table if not exists public.todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  completed boolean default false,
  created_at timestamptz default now()
);
-- RLS never enabled on this table.

create table if not exists public.todo_lists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  name text not null,
  created_at timestamptz default now()
);

alter table public.todo_lists enable row level security;

create policy "select own lists"
  on public.todo_lists
  for select
  using (auth.uid() = user_id);

create policy "insert lists"
  on public.todo_lists
  for insert
  to authenticated;
  -- no WITH CHECK: any authenticated user can create a list under any
  -- user_id, not just their own.
