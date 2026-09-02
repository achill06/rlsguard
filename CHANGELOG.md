# Improvement Changelog

| Stage | What was tried | Evidence | Decision |
|---|---|---|---|
| Baseline | Single prompt to Gemini, no tools, no verification. | Initially refused ("can't analyze this"). Fixed by reframing the prompt and lowering the safety threshold. After that, correct on both a broken and a clean schema. | Kept. Naive prompts are brittle to refusals before accuracy even matters. |
| 1. Detector | Regex-based, no model, five fixed issue patterns. | 18/18 true positives, 0 false positives across all seeded schemas. | Kept. Perfect on its pattern set, structurally blind to anything outside it. |
| 2. Fixer | Infers ownership column via FK trace to `auth.users`, not a name guess. | Correct on every table with a direct FK. Correctly declined `note_tags` (no FK). On `tasks`, picked the only FK available, `assignee_id`. | Kept, with a known limitation: single-column heuristic breaks on team-owned resources. |
| 3. Sandbox | Disposable Postgres container replicating Supabase's `auth.uid()` and roles. | First run: every probe denied, including the owner. Root cause: no default grants, so requests failed before RLS even ran. | Added `ALTER DEFAULT PRIVILEGES` to match Supabase's real defaults. Fixed. |
| 4. Verifier | Three-role SELECT probes proving access by real query execution. | First run: seeding failed, FK violation, fake identities were never inserted into `auth.users`. | Fixed by seeding `auth.users` first. First full verified run succeeded after. |
| 5. Orchestrator | Chains detect → fix → apply → verify, originally planned with a uniform 3x retry. | The fixer is deterministic: a failed verification would retry into the identical failure. | Changed design: retry only applies to transient apply errors; a verification failure escalates straight to manual review. |
| 6. Removed | Early fixer version assumed a fixed `user_id` column name. | Would silently break on any other naming convention. | Replaced by the FK-tracing approach (Iteration 2) before it ever shipped. |
| 7. Write probes | Extended verification beyond SELECT to INSERT/UPDATE isolation. | First run: 5 previously-verified findings failed, writes were probed against every table regardless of whether a matching policy existed, testing INSERT where no INSERT policy was ever present. | Scoped probes to only test operations with an actual policy (checked via `pg_policies`). Back to 17/18, now proving reads and writes, not just reads. |
| Final | Full eval, all 11 schemas. | Detector: 1.0 precision/recall. Agent: 17/18 fixes independently verified by real read and write execution, 1 correctly declined. | Headline result: fixes aren't just claimed, they're proven end to end, and the one exception is a correct refusal, not a miss. |

## Main failure mode

The fixer's ownership inference is single-column and FK-based, correct
for personally-owned tables, wrong for team-shared ones. `tasks` is the
concrete case: it picked `assignee_id` (the only FK available), passed
verification, but doesn't reflect a real team access model.

Narrower detector limitation: `permissive_policy` only matches a literal
`USING (true)`. A logically equivalent bypass written differently
(`OR true`, `1=1`) would slip through. A deliberate scope boundary, not
a hidden gap.

## Hot take

Verification proves a fix is internally consistent, not that it's the
right ownership model. `tasks` verified successfully, reads and writes
both, while still being semantically wrong. Proof-by-execution is
necessary but not sufficient, getting the fixer's judgment right for
relational ownership is the harder half of this project, and the honest
answer to "what's next."