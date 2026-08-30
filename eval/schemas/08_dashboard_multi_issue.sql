-- small team dashboard, vibe-coded

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) not null,
  name text not null,
  created_at timestamptz default now()
);

alter table public.projects enable row level security;

create policy "Owners can manage their projects"
  on public.projects
  for all
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

create table if not exists public.tasks (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references public.projects(id) not null,
  assignee_id uuid references auth.users(id),
  title text not null,
  status text default 'todo',
  created_at timestamptz default now()
);
-- no ALTER TABLE ... ENABLE ROW LEVEL SECURITY for tasks at all.

create table if not exists public.team_members (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references public.projects(id) not null,
  user_id uuid references auth.users(id) not null,
  role text default 'member',
  created_at timestamptz default now()
);

alter table public.team_members enable row level security;

create policy "members can view"
  on public.team_members
  for select
  using (auth.uid() = user_id);

create policy "members can insert"
  on public.team_members
  for insert
  to authenticated;
  -- no WITH CHECK: any authenticated user can add themselves (or anyone)
  -- to any project's team_members with any role, including "admin".

grant select, insert on public.team_members to anon;
-- team membership has no legitimate anonymous use case; this grant was
-- never revoked after local testing.
