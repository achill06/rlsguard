# Improvement Changelog

| Stage | What was tried and why | Evidence | Decision / learning |
|---|---|---|---|
| Baseline | Single unstructured prompt to Gemini 3.6 Flash, no tools, no sandbox, given a schema file and asked to spot RLS issues in plain text. | On the first attempt, the model refused outright ("Sorry, I cannot analyze the provided code snippet..."), even though this is a benign self-review task. | The prompt was reframed from "identify vulnerabilities" to "check whether RLS correctly restricts access," and the safety threshold for the dangerous-content category was explicitly lowered via the API. After that, it correctly flagged the one planted issue in a no-RLS schema and correctly returned nothing on a clean one. Kept as the baseline. Worth noting as a finding on its own: a naive single-prompt approach is brittle to refusals before you even get to accuracy. |
| Iteration 1 | Regex-based detector parsing schema files directly for the five planted issue classes, no model involved. | Tested against all 11 seeded schemas against hand-written ground truth: 18/18 true positives, 0 false positives, 0 false negatives. | Kept as-is. Purely mechanical pattern matching, perfect on the fixed pattern set it was built for, structurally unable to catch anything outside those five patterns. |
| Iteration 2 | Fixer that infers the ownership column by tracing the actual foreign key to `auth.users`, rather than assuming a column name, and generates corrected policy SQL. | Ran against all 11 schemas. Correctly inferred `user_id` everywhere it existed as a direct FK. Correctly declined to fix `note_tags` (no FK to `auth.users` at all) rather than guessing. On `tasks`, inferred `assignee_id` as the ownership column since it was the only FK present. | Kept, with a documented limitation: the fixer's single-column heuristic works for personally-owned resources and breaks down for team/shared resources, where "ownership" is really a relationship (project membership), not one column. `tasks` is the concrete example. |
| Iteration 3 | Sandbox: disposable Postgres container replicating Supabase's real `auth.uid()` implementation and role model. | First integration test failed: every probe returned 0 rows for every role, including the owner. Root cause was that the bootstrap script never granted `anon`/`authenticated` any table-level access, so requests were rejected before RLS was ever evaluated. Real Supabase grants broad table access by default and lets RLS do the actual restricting. | Added `ALTER DEFAULT PRIVILEGES` to the bootstrap so every future table gets Supabase's real default grants automatically. After that fix, the todos schema verified correctly on the first real run. |
| Iteration 4 | Verifier: three-role SELECT probes (anon, authenticated non-owner, authenticated owner) against a seeded row, proving access by executing real queries rather than reading policy SQL. | Second integration bug found immediately: seeding failed with a foreign key violation, because the fake owner/other identities were never inserted into `auth.users`. | Fixed by seeding `auth.users` before seeding any table with a FK to it. After the fix, `01_todo_no_rls.sql` verified end to end for the first time: detect, fix, apply, and three real query results proving the fix worked. |
| Iteration 5 | Orchestrator (`agent.py`) chaining detect → fix → apply → verify → report, originally planned with a uniform 3x retry on any failure. | On review, the fixer is deterministic: a fix that applies cleanly but fails verification will produce the exact same SQL and the exact same failure on a second attempt. A uniform retry would be pure looping with no chance of a different outcome. | Changed the design: apply failures (transient, e.g. a dropped connection) retry up to 3 times; verification failures escalate straight to manual review after one attempt. This differs from the original plan, and is called out here rather than silently changed, because testing showed the original plan didn't fit how this specific fixer works. |
| Iteration 6 | Removed: attempted using a fixed `user_id` column name assumption instead of tracing the actual foreign key, as an earlier, simpler version of the fixer. | Would have silently mis-fixed or skipped any table using a different naming convention. | Removed before it was ever the checked-in version, replaced directly by the FK-tracing approach in Iteration 2. Mentioned here because the brief specifically asks for experiments that were tried and abandoned, not just what shipped. |
| Final | Full pipeline run via `eval/run_eval.py` against all 11 seeded schemas. | Detector: precision 1.0, recall 1.0, F1 1.0 (18 true positives, 0 false positives, 0 false negatives). Agent: 17/18 findings independently verified by real query execution (94.4%), 1 correctly deferred to manual review rather than falsely reported as fixed. | This is the headline result: not just "the agent found issues" but "the agent's claimed fixes were independently proven correct by executing queries against them," and the one case it didn't auto-fix is one it was right to decline. |

## Main failure mode

The fixer's ownership-column inference is single-column and FK-based. It
works well for personally-owned resources (`todos`, `recipes`, `notes`)
and breaks down for team-shared resources, where ownership is really a
relationship through project membership rather than one column. The
`tasks` table in `08_dashboard_multi_issue.sql` is the concrete example:
the fixer inferred `assignee_id` as the ownership column (the only FK to
`auth.users` present), which passed verification because the read-isolation
probe only tests one seeded row against one identity, but doesn't reflect
a correct real-world access model (a project owner arguably should also
see the team's tasks, and unassigned tasks become invisible to everyone).

A second, narrower limitation in the detector itself: `permissive_policy`
only matches a literal `USING (true)` or `WITH CHECK (true)`, exact
string comparison. A logically equivalent but differently worded bypass,
`USING (auth.uid() = user_id OR true)`, or `USING (1=1)`, would not be
flagged. The detector is a pattern matcher for five specific shapes, not
a general tautology checker, and that's a deliberate scope boundary
worth stating rather than a gap worth hiding.

## Hot take

Read-isolation verification proves a fix is internally consistent, not
that it encodes the correct ownership model for the domain. The `tasks`
case verified successfully while still being the wrong fix semantically,
proof-by-execution is a real and necessary check, but it is not a
substitute for understanding what "ownership" actually means for a given
table. Building the detect-fix-verify loop was the easier half of this
project; getting the fixer's judgment right for relational (not
column-based) ownership would be the harder half, and is the most honest
answer to "what would you build next."