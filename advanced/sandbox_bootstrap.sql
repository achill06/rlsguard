-- Minimal replica of what Supabase actually provisions: an auth schema,
-- a users table for foreign keys to reference, the auth.uid() function
-- (matches Supabase's real implementation), the anon/authenticated roles,
-- and Supabase's default table grants so that RLS, not missing grants,
-- is what's actually being tested.

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key,
  email text
);

create or replace function auth.uid() returns uuid
language sql stable
as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end
$$;

grant usage on schema public to anon, authenticated;
grant usage on schema auth to anon, authenticated;
grant select on auth.users to anon, authenticated;

-- Matches Supabase's real default: broad table grants to anon and
-- authenticated on every table created afterward, so RLS policies are
-- what actually restrict access, not table-level permission errors.
alter default privileges in schema public
  grant select, insert, update, delete on tables to anon, authenticated;
alter default privileges in schema public
  grant usage, select on sequences to anon, authenticated;