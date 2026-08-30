-- small team dashboard, vibe-coded
-- the policies are actually fine. But an early scaffolding step granted
-- broad table access to `anon` for local testing, and it was never revoked
-- before shipping.

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) not null,
  name text not null,
  created_at timestamptz default now()
);

alter table public.projects enable row level security;

create policy "Owners can view their projects"
  on public.projects
  for select
  using (auth.uid() = owner_id);

create policy "Owners can manage their projects"
  on public.projects
  for all
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- leftover from early local testing, never revoked:
grant select, insert, update, delete on public.projects to anon;
-- table-level GRANTs are checked before RLS policies are evaluated in
-- Postgres. This grant doesn't bypass the policies' row filtering, but it
-- does mean anon can attempt any operation the policies would otherwise
-- correctly deny only after connecting, which is unnecessary exposure for
-- a table with no legitimate anonymous use case.
