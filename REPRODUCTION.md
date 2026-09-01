# Reproduction Guide

Written for someone starting from a clean environment with nothing set up
beyond Docker and Python 3.

## Requirements

- Docker (running)
- Python 3.10+
- A free Gemini API key (used only for the baseline comparator), from
  https://aistudio.google.com/apikey. No credit card required.

## Setup

```bash
git clone <this-repo-url>
cd rlsguard

pip3 install -r baseline/requirements.txt --break-system-packages
pip3 install -r advanced/requirements.txt --break-system-packages

export GEMINI_API_KEY=your_key_here
```

Approximate cost: $0. Gemini's free tier covers the handful of baseline
calls needed here many times over. The advanced pipeline makes no API
calls at all, detection and fixing are local, deterministic Python;
verification runs entirely in a local, disposable Docker container.

## Running the baseline

```bash
python3 baseline/baseline_review.py eval/schemas/01_todo_no_rls.sql
```

Expected output: a short plain-text note that `todos` has no RLS enabled.
Runtime: a few seconds, dominated by the API round trip.

## Running the advanced solution on one schema

```bash
python3 advanced/agent.py eval/schemas/08_dashboard_multi_issue.sql --out /tmp/report.md
cat /tmp/report.md
```

This spins up a disposable Postgres container (first run pulls the
`postgres:16` image, roughly 200-300MB, one-time cost), applies the
schema, seeds one row per table, detects the RLS issues, applies a fix
for each, proves the fix by running real queries as three simulated
identities (anonymous, an authenticated non-owner, and the authenticated
owner), and tears the container down. Runtime: roughly 10-20 seconds per
schema, most of it Postgres startup and probe queries.

Expected output: a markdown table showing each finding, its severity, and
whether it was verified or flagged for manual review.

## Running the full evaluation

```bash
python3 eval/run_eval.py --out eval/results.json
```

Runs the detector and the full agent pipeline against all 11 seeded
schemas in `eval/schemas/` and scores them against
`eval/expected_findings.json`. Runtime: roughly 2-3 minutes (a fresh
sandbox container per schema with findings). No API calls, this only
exercises the detector and advanced pipeline, not the baseline.

Expected output, matching the numbers reported in CHANGELOG.md:

```
DETECTOR (structured, exact match against ground truth)
  precision: 1.0
  recall:    1.0
  f1:        1.0
  TP=18 FP=0 FN=0

AGENT (fix applied and empirically verified in sandbox)
  17/18 findings verified (94.4%)
  1 flagged for manual review
```

The one manual-review case is `note_tags` in
`09_notes_multi_issue.sql`, correctly declined because it has no foreign
key to `auth.users` for the fixer to infer ownership from.

## Running the detector or fixer standalone

```bash
python3 advanced/detector.py eval/schemas/01_todo_no_rls.sql
python3 advanced/fixer.py eval/schemas/01_todo_no_rls.sql
```

Neither of these needs Docker or an API key, both are pure local Python.
Useful for inspecting what the pipeline found or proposed without paying
the cost of spinning up a sandbox.

## Running the one-command demo

```bash
./demo.sh
```

Runs the baseline, the full agent pipeline, and the evaluation summary
in sequence, with a banner before each step explaining what it does and
why. Pauses between steps (press Enter to continue) so it's suitable for
narrating live during a recording.

## Data

All schema files in `eval/schemas/` are synthetic, hand-written to
represent plausible vibe-coded apps (a todo app, a recipe-sharing app, a
small team dashboard, a notes app), with known, documented issues planted
in `eval/expected_findings.json`. `eval/real-world-examples/` additionally
contains a schema pulled from a real Lovable-generated app, used to test
generalization beyond the hand-written set. No real user data,
credentials, or third-party systems are touched anywhere in this
repository.