# Trajectory: building the sandbox and verifier

**Agent used**: Claude, via the claude.ai chat interface. (Not Claude Code
or an IDE agent, an earlier session using Antigravity hit a quota limit
mid-build and the rest of the project, including everything shown here,
was built directly in this chat instead. That switch is itself visible
earlier in the full conversation.)

**Why this excerpt is representative**: it's the stretch of the build
where the agent's proposed code was wrong twice, in different ways, and
both times the mistake was only caught by actually running it, not by
reading it. That's the core thesis of this whole project applied to its
own construction. A third excerpt below shows the fixer producing a
technically-passing but semantically questionable fix, discovered the
same way.

**Note on scope**: rlsguard's own advanced pipeline (`detector.py`,
`fixer.py`, `sandbox.py`, `verifier.py`, `agent.py`) makes no LLM calls
at runtime, this is disclosed in the main README. So there is no
separate "rlsguard trajectory" to show for its own execution, only for
the agent that built it. This file is that trajectory.

---

## Bug 1: missing default privileges

**Instruction to the agent** (paraphrased from context, full detail in
the main conversation): build `sandbox.py` and `sandbox_bootstrap.sql`,
a disposable Postgres container replicating Supabase's real `auth.uid()`
mechanism and role model, for the fixer's proposed policies to be tested
against.

**What the agent produced**: a bootstrap script creating an `auth` schema,
an `auth.users` table, an `auth.uid()` function matching Supabase's real
implementation (verified against Supabase's own GitHub issues before
writing it), and `anon`/`authenticated` roles. The agent flagged its own
uncertainty explicitly before handoff:

> "I can't run Docker myself to test this end to end, so be more careful
> watching the first run than you were with the detector... you're the
> first real test of Phase 4."

**Tool result** (user ran it against the first seeded schema):

```
python3 advanced/verifier.py eval/schemas/01_todo_no_rls.sql
starting sandbox...
  (seed warning: could not seed todos: insert or update on table "todos"
   violates foreign key constraint "todos_user_id_fkey"
DETAIL:  Key (user_id)=(11111111-1111-1111-1111-111111111111) is not
present in table "users".)
seeded rows for: []
[NOT VERIFIED] todos / rls_not_enabled: select probes failed: {'anon':
{'error': None, 'row_count': 0}, 'authenticated_non_owner': {'error':
None, 'row_count': 0}, 'authenticated_owner': {'error': None,
'row_count': 0}}
sandbox torn down
```

**Diagnosis**: every probe returned 0 rows, including the owner's, which
should never happen if the fix were correct, that pattern (universal
denial, not selective denial) was the signal that something upstream of
RLS itself was broken, not the policy logic. Root cause: the seed step
tried to insert a row referencing a fake owner UUID into `todos`, but
that UUID was never inserted into `auth.users` first, so the foreign key
constraint rejected it before RLS was ever evaluated.

**Correction applied**: added a `seed_auth_users()` step to insert rows
for the fake owner and non-owner identities into `auth.users` before
seeding any table with a foreign key to it.

**Re-run, after the fix**:

```
python3 advanced/verifier.py eval/schemas/01_todo_no_rls.sql
starting sandbox...
seeded rows for: ['todos']
[VERIFIED] todos / rls_not_enabled: select probes passed: anon and
non-owner denied, owner allowed
sandbox torn down
```

---

## Bug 2: missing default grants (caught before it shipped)

Earlier in the same phase, before the above bug was even reached, the
agent independently caught a second problem by reasoning through the
Supabase permission model rather than waiting for a failed run:

> "I caught a real problem in the sandbox setup itself that would have
> silently broken everything: my `sandbox_bootstrap.sql` never gives
> `anon`/`authenticated` any table-level grants beyond what's explicitly
> written in a schema file. Real Supabase applies broad default grants
> to those roles on every table automatically, RLS is what's supposed to
> do the actual restricting, not the grants. Without replicating that,
> even the legitimate owner probe would get rejected with a permission
> error before RLS is ever evaluated."

**Correction applied before the first real run**: added

```sql
alter default privileges in schema public
  grant select, insert, update, delete on tables to anon, authenticated;
alter default privileges in schema public
  grant usage, select on sequences to anon, authenticated;
```

to `sandbox_bootstrap.sql`, so every table created afterward gets
Supabase's real default grants automatically.

This one is included specifically because it's a case of catching an
error through reasoning about the target system's real behavior, before
any tool result forced the issue, the complement to Bug 1, which was
only caught by execution.

---

## Finding 3: a fix that verifies but is semantically wrong

Not a bug in this codebase, a limitation the verification step exposed
in its own output. Running the fixer against `08_dashboard_multi_issue.sql`:

```
python3 advanced/fixer.py eval/schemas/08_dashboard_multi_issue.sql
--- tasks / rls_not_enabled () ---
  Enabled RLS on tasks and added owner-scoped policies for
  select/insert/update/delete, keyed on assignee_id = auth.uid().
  > alter table public.tasks enable row level security;
  > create policy "tasks_select_own" on public.tasks for select using
    (auth.uid() = assignee_id);
  ...
```

The agent flagged this as a problem before it was ever run:

> "For the `tasks` table... it inferred `assignee_id` as the ownership
> column, since that's the only FK to `auth.users`. That's technically
> correct by the rule, but semantically shaky: `assignee_id` is
> nullable, so unassigned tasks would become invisible to everyone once
> this fix applies, and a task's 'owner' in a team context arguably
> should also include the project owner, not just whoever it's assigned
> to."

When actually run through the verifier, this fix **passed** verification
(`[VERIFIED] tasks / rls_not_enabled`), which the agent flagged as the
more interesting outcome, not a false pass, but evidence of what
read-isolation verification does and doesn't prove:

> "The verifier seeded exactly one task row, assigned to the owner
> identity, and confirmed anon and the non-owner can't see it, and the
> owner can. That's a completely true, correctly proven result, for
> that one row... it's not testing the policy design, only whether the
> policy consistently enforces whatever rule it encodes."

This became the project's main documented failure mode and hot take
(see `CHANGELOG.md`), a case where the same tool that catches most
mistakes by execution was shown, by that same execution, to have a real
limit on what it can catch.