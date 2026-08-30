"""
agent.py

The orchestrator: detect -> fix -> apply -> verify -> report, for a whole
schema file in one command. This is the "advanced solution" entry point,
what the eval harness (Phase 8) runs against every seeded schema, and
what the demo video should show end to end.

On retries: apply failures (the fix SQL fails to execute, e.g. a
transient connection issue) get retried, capped at 3. A verification
failure (the fix applied cleanly but the probes still fail) escalates
straight to manual review after one attempt instead of retrying, since
fixer.py is deterministic and a repeat attempt would generate the
identical SQL and fail identically. See the module docstring history in
CHANGELOG.md for why this differs from the originally planned uniform
3x retry.

Usage:
    python agent.py path/to/schema.sql
    python agent.py path/to/schema.sql --out report.md
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detector import detect
from fixer import generate_fix
from sandbox import Sandbox
from verifier import (
    seed_auth_users,
    seed_tables,
    get_tables_in_declaration_order,
    probe_select,
    check_select_probe,
)
from report import generate_report

MAX_APPLY_RETRIES = 3


def process_finding(sandbox: Sandbox, schema_text: str, finding: dict):
    fix = generate_fix(schema_text, finding)

    if fix["manual_review"]:
        return {
            "finding": finding,
            "status": "manual_review",
            "reason": fix["description"],
            "attempts": 0,
        }

    apply_error = None
    attempts_used = 0
    for attempt_num in range(1, MAX_APPLY_RETRIES + 1):
        attempts_used = attempt_num
        try:
            for stmt in fix["sql"]:
                sandbox.apply_sql(stmt)
            apply_error = None
            break
        except Exception as e:
            apply_error = str(e)

    if apply_error is not None:
        return {
            "finding": finding,
            "status": "manual_review",
            "reason": f"fix SQL failed to apply after {attempts_used} attempts: {apply_error}",
            "attempts": attempts_used,
        }

    select_results = probe_select(sandbox, finding["table"])
    verified = check_select_probe(select_results)

    if verified:
        return {
            "finding": finding,
            "status": "verified",
            "reason": "select probes passed: anon and non-owner denied, owner allowed",
            "fix_description": fix["description"],
            "fix_sql": fix["sql"],
            "attempts": attempts_used,
            "probe_detail": select_results,
        }
    else:
        return {
            "finding": finding,
            "status": "manual_review",
            "reason": (
                "fix applied but verification failed; not retrying since the "
                "fixer is deterministic and a repeat attempt would produce an "
                "identical, identically-failing result"
            ),
            "fix_description": fix["description"],
            "fix_sql": fix["sql"],
            "attempts": attempts_used,
            "probe_detail": select_results,
        }


def run(schema_path: Path):
    schema_text = schema_path.read_text()
    findings = detect(schema_text)

    if not findings:
        return {"schema": schema_path.name, "findings": [], "results": []}

    sandbox = Sandbox()
    sandbox.start()
    try:
        sandbox.apply_sql(schema_text)
        seed_auth_users(sandbox)
        tables_in_order = get_tables_in_declaration_order(schema_text)
        seed_tables(sandbox, schema_text, tables_in_order)

        results = []
        for finding in findings:
            result = process_finding(sandbox, schema_text, finding)
            results.append(result)
            print(
                f"[{result['status'].upper()}] {finding['table']} / "
                f"{finding['issue_type']}: {result['reason']}"
            )
        return {"schema": schema_path.name, "findings": findings, "results": results}
    finally:
        sandbox.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema_file", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Save the markdown report here")
    args = parser.parse_args()

    if not args.schema_file.exists():
        print(f"Schema file not found: {args.schema_file}", file=sys.stderr)
        sys.exit(1)

    outcome = run(args.schema_file)
    report_text = generate_report(outcome["schema"], outcome["results"])
    print("\n" + report_text)

    if args.out:
        args.out.write_text(report_text)
        print(f"\nReport written to {args.out}")


if __name__ == "__main__":
    main()