# rlsguard — Agentic RLS Remediation for Vibe-Coded Supabase Apps

> micro1 Agentic Workflows Hackathon 2026 - individual entry

## 1. Who has this problem, and why does it matter

Anyone shipping a Supabase-backed app built largely with AI coding tools
(Cursor, Bolt.new, Lovable, v0, Windsurf), without a dedicated security
review. This isn't hypothetical: in April 2026, Lovable disclosed a
Broken Object Level Authorization vulnerability that exposed source
code, database credentials, and chat histories for projects created
before November 2025, left unpatched for 48 days after initial report.
Independent analysis afterward found roughly 70% of Lovable-built apps
shipped with Row-Level Security disabled entirely. RLS is invisible in a
"happy path" demo, so it's exactly the kind of thing vibe-coding tools
skip.

## 2. What bottleneck this solves

A solo developer or small team using these tools usually doesn't know
RLS is a concept they need to configure, let alone how to audit it. This
tool takes their schema, tells them precisely what's wrong, proposes a
fix, and proves the fix actually works, rather than asking them to trust
either an AI-generated suggestion or their own read of unfamiliar SQL.

## 3. Approach

Four stages, chained by `advanced/agent.py`:

1. **Detect** (`advanced/detector.py`) — parses a schema file directly
   (no model call) and flags five specific issue classes: RLS never
   enabled, a policy that's unconditionally true, an INSERT policy
   missing its WITH CHECK clause, a policy that never references the
   caller's identity, and the `anon` role holding a grant it shouldn't.
2. **Fix** (`advanced/fixer.py`) — infers the ownership column by
   tracing the actual foreign key to `auth.users`, and generates
   corrected policy SQL.
3. **Apply + verify** (`advanced/sandbox.py`, `advanced/verifier.py`) —
   applies the fix inside a disposable local Postgres container that
   replicates Supabase's real `auth.uid()` implementation, then proves
   it by running actual SELECT queries as three simulated identities
   (anonymous, an authenticated non-owner, and the authenticated owner)
   and checking the access pattern is deny/deny/allow.
4. **Report** (`advanced/report.py`) — a severity-ranked table of every
   finding, whether it was verified, and why.

The baseline (`baseline/baseline_review.py`) is a single unstructured
prompt to Gemini, no tools, no sandbox, no verification, representing
the reasonable basic way someone would actually approach this task.

## 4. Results

Full details and the iteration history are in [CHANGELOG.md](./CHANGELOG.md).
Headline numbers from `eval/run_eval.py` against all 11 seeded schemas:

| | Result |
|---|---|
| Detector precision / recall / F1 | 1.0 / 1.0 / 1.0 (18 true positives, 0 false positives, 0 false negatives) |
| Fixes independently verified by real query execution | 17/18 (94.4%) |
| Correctly deferred to manual review rather than guessed | 1/18 |

The one non-verified case (`note_tags`, no foreign key to `auth.users`
to infer ownership from) is a correct decline, not a failure, the
fixer's manual-review fallback working as designed.

## 5. Reproduction

See [REPRODUCTION.md](./REPRODUCTION.md) for exact setup and commands
from a clean environment.

## 6. Tools disclosed

- **Baseline model**: Gemini 3.6 Flash, via Google's free-tier API.
- **Advanced pipeline**: no LLM call anywhere. Detection and fixing are
  deterministic Python; verification runs real SQL against a local
  Postgres container. The "agentic" capabilities here, per the
  hackathon brief's own definition, are tool use (the sandbox),
  verification (the three-role probes), and orchestration (the
  detect-fix-verify-report chain), not per-step LLM judgment.
- **Development**: built interactively via Claude (chat interface),
  used for design, code generation, and debugging throughout, including
  catching and fixing two real integration bugs (missing default
  privileges in the sandbox bootstrap; missing `auth.users` seed rows)
  that were only found by actually running the pipeline, not by
  inspection.

## 7. Main failure mode

See [CHANGELOG.md](./CHANGELOG.md#main-failure-mode). Short version: the
fixer's ownership-column inference is single-column and FK-based, which
works for personally-owned resources and breaks down for team-shared
ones (the `tasks` table is the concrete example), a case that passes
this version's read-isolation verification while still encoding a
questionable real-world access model.

## 8. Hot take

See [CHANGELOG.md](./CHANGELOG.md#hot-take). Short version: proving a
fix works by executing real queries against it is genuinely necessary
and this project's core contribution, but it proves internal
consistency, not that the underlying ownership model is correct for the
domain. Those are different claims, and it's worth being precise about
which one you're actually making.