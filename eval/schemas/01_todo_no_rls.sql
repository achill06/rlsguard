-- todo app, vibe-coded, single afternoon build
-- reviewed: never

create table if not exists public.todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) not null,
  title text not null,
  completed boolean default false,
  created_at timestamptz default now()
);

-- no ALTER TABLE ... ENABLE ROW LEVEL SECURITY anywhere for this table.
-- Supabase's auto-generated REST API exposes it directly, so it's fully
-- public: any anon or authenticated caller can read/write every row.
