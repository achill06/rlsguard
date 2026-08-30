-- todo app, RLS configured correctly, no planted issues

create table if not exists public.todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  completed boolean default false,
  created_at timestamptz default now()
);

alter table public.todos enable row level security;

create policy "select own todos"
  on public.todos
  for select
  using (auth.uid() = user_id);

create policy "insert own todos"
  on public.todos
  for insert
  with check (auth.uid() = user_id);

create policy "update own todos"
  on public.todos
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "delete own todos"
  on public.todos
  for delete
  using (auth.uid() = user_id);

revoke all on public.todos from anon;
