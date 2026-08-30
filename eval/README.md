# Seeded eval set

10 synthetic Supabase/Postgres schemas across three fictional apps (todo,
recipe sharing, small team dashboard, notes), each written in the style a
vibe-coding tool would plausibly generate. 8 have 1-3 planted issues, 2 are
clean. All data and table names are synthetic, no real users or credentials.

## Issue type taxonomy (must match what the detector emits)

- `rls_not_enabled` : table has no RLS enabled at all.
- `permissive_policy` : a policy exists but uses an unconditionally true
  USING or WITH CHECK expression.
- `missing_with_check` : an INSERT-only policy has no WITH CHECK clause at
  all. (UPDATE policies auto-inherit USING as WITH CHECK if omitted, per
  Postgres semantics, so this class applies to INSERT policies only. An
  UPDATE policy with an explicit, weaker-than-USING WITH CHECK is a
  `permissive_policy` case instead, since the hole comes from what was
  written, not what was left out.)
- `not_scoped_to_caller` : a policy exists and looks like a check, but never
  references `auth.uid()` or an ownership column.
- `anon_role_overgranted` : the `anon` role has a table-level GRANT it has
  no legitimate reason to hold.

## Files

| File | Issues planted |
|---|---|
| 01_todo_no_rls.sql | rls_not_enabled |
| 02_todo_permissive_using_true.sql | permissive_policy x2 |
| 03_recipes_check_issues.sql | missing_with_check (insert), permissive_policy (update, explicit WITH CHECK(true)) |
| 04_recipes_policy_not_scoped.sql | not_scoped_to_caller x2 |
| 05_dashboard_anon_grant.sql | anon_role_overgranted |
| 06_todo_multi_issue.sql | rls_not_enabled, missing_with_check |
| 07_recipes_multi_issue.sql | permissive_policy, not_scoped_to_caller |
| 08_dashboard_multi_issue.sql | rls_not_enabled, missing_with_check, anon_role_overgranted |
| 09_notes_multi_issue.sql | permissive_policy, not_scoped_to_caller, rls_not_enabled |
| 10_todo_clean.sql | none (false-positive check) |
| 11_recipes_clean.sql | none (false-positive check) |

`expected_findings.json` is the ground truth `run_eval.py` will score
against in Phase 8. Table and policy names in the detector's output must
match these exactly for scoring to work, so keep this file as the source of
truth if any schema changes later.
