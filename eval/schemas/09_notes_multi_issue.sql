-- personal notes app, vibe-coded over a weekend

create table if not exists public.notes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  body text,
  created_at timestamptz default now()
);

alter table public.notes enable row level security;

create policy "select notes"
  on public.notes
  for select
  using (true);
  -- unconditionally true: every user's notes are readable by anyone.

create policy "update notes"
  on public.notes
  for update
  using (body is not null)
  with check (body is not null);
  -- checks the note has content, never checks who owns it.

create table if not exists public.note_tags (
  id uuid primary key default gen_random_uuid(),
  note_id uuid references public.notes(id) not null,
  tag text not null
);
-- no RLS enabled on note_tags at all.
