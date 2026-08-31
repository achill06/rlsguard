"""
detector.py

Parses a Supabase/Postgres schema file and flags RLS issues by pattern,
not by asking a model. This is the first stage of the advanced agent
pipeline (detector -> fixer -> sandbox -> verifier).

Issue types (must match eval/expected_findings.json exactly):
    rls_not_enabled       - a table has no ALTER TABLE ... ENABLE ROW LEVEL
                             SECURITY at all.
    permissive_policy     - a policy's USING or WITH CHECK expression is
                             the literal `true`.
    missing_with_check    - an INSERT-only policy has no WITH CHECK clause.
                             (UPDATE/ALL policies auto-inherit USING as
                             WITH CHECK when omitted, per Postgres
                             semantics, so this class is INSERT-only.)
    not_scoped_to_caller  - a policy has a real expression, but it never
                             references auth.uid().
    anon_role_overgranted - the `anon` role has a table-level GRANT.

Usage:
    python detector.py path/to/schema.sql
    python detector.py path/to/schema.sql --out findings.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)", re.IGNORECASE
)
ALTER_RLS_RE = re.compile(
    r"alter\s+table\s+(?:public\.)?(\w+)\s+enable\s+row\s+level\s+security",
    re.IGNORECASE,
)
POLICY_NAME_RE = re.compile(r'create\s+policy\s+"([^"]+)"', re.IGNORECASE)
POLICY_TABLE_RE = re.compile(r"\bon\s+(?:public\.)?(\w+)\b", re.IGNORECASE)
POLICY_COMMAND_RE = re.compile(
    r"\bfor\s+(all|select|insert|update|delete)\b", re.IGNORECASE
)
USING_START_RE = re.compile(r"\busing\s*\(", re.IGNORECASE)
CHECK_START_RE = re.compile(r"\bwith\s+check\s*\(", re.IGNORECASE)
GRANT_RE = re.compile(
    r"grant\s+([\w,\s]+?)\s+on\s+(?:table\s+)?(?:public\.)?(\w+)\s+to\s+([\w,\s]+)",
    re.IGNORECASE,
)


def strip_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def extract_balanced(text: str, open_paren_idx: int):
    """Given the index of a '(' in text, return (content, index_of_matching_close)."""
    depth = 0
    for i in range(open_paren_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_idx + 1 : i], i
    return None, len(text) - 1


def parse_policy(stmt: str):
    name_match = POLICY_NAME_RE.search(stmt)
    table_match = POLICY_TABLE_RE.search(stmt)
    command_match = POLICY_COMMAND_RE.search(stmt)
    if not table_match:
        return None

    using_expr = None
    using_match = USING_START_RE.search(stmt)
    if using_match:
        using_expr, _ = extract_balanced(stmt, using_match.end() - 1)

    check_expr = None
    check_match = CHECK_START_RE.search(stmt)
    if check_match:
        check_expr, _ = extract_balanced(stmt, check_match.end() - 1)

    return {
        "name": name_match.group(1) if name_match else "(unnamed)",
        "table": table_match.group(1),
        "command": (command_match.group(1).lower() if command_match else "all"),
        "using": using_expr,
        "check": check_expr,
    }


def is_literal_true(expr):
    return expr is not None and expr.strip().lower() == "true"


def references_caller(expr):
    return expr is not None and "auth.uid()" in expr.lower().replace(" ", "")


def detect(schema_text: str):
    schema_text = strip_comments(schema_text)
    statements = [s.strip() for s in schema_text.split(";") if s.strip()]

    tables = set()
    rls_enabled_tables = set()
    policies = []
    grants = []

    for stmt in statements:
        if CREATE_TABLE_RE.match(stmt.strip()):
            m = CREATE_TABLE_RE.search(stmt)
            tables.add(m.group(1))
        elif ALTER_RLS_RE.search(stmt):
            m = ALTER_RLS_RE.search(stmt)
            rls_enabled_tables.add(m.group(1))
        elif re.match(r"create\s+policy", stmt.strip(), re.IGNORECASE):
            policy = parse_policy(stmt)
            if policy:
                policies.append(policy)
        elif re.match(r"grant\s", stmt.strip(), re.IGNORECASE):
            m = GRANT_RE.search(stmt)
            if m:
                table = m.group(2)
                roles = [r.strip().lower() for r in m.group(3).split(",")]
                grants.append({"table": table, "roles": roles})

    findings = []

    for table in sorted(tables):
        if table not in rls_enabled_tables:
            findings.append({"table": table, "issue_type": "rls_not_enabled"})

    for policy in policies:
        flagged_permissive = False

        if is_literal_true(policy["using"]) or is_literal_true(policy["check"]):
            findings.append(
                {
                    "table": policy["table"],
                    "issue_type": "permissive_policy",
                    "policy": policy["name"],
                }
            )
            flagged_permissive = True

        if policy["command"] == "insert" and policy["check"] is None:
            findings.append(
                {
                    "table": policy["table"],
                    "issue_type": "missing_with_check",
                    "policy": policy["name"],
                }
            )

        has_any_expr = policy["using"] is not None or policy["check"] is not None
        references_uid = references_caller(policy["using"]) or references_caller(
            policy["check"]
        )
        if has_any_expr and not flagged_permissive and not references_uid:
            findings.append(
                {
                    "table": policy["table"],
                    "issue_type": "not_scoped_to_caller",
                    "policy": policy["name"],
                }
            )

    for grant in grants:
        if "anon" in grant["roles"]:
            findings.append(
                {"table": grant["table"], "issue_type": "anon_role_overgranted"}
            )

    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema_file", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.schema_file.exists():
        print(f"Schema file not found: {args.schema_file}", file=sys.stderr)
        sys.exit(1)

    findings = detect(args.schema_file.read_text())
    output = json.dumps(findings, indent=2)
    print(output)

    if args.out:
        args.out.write_text(output)


if __name__ == "__main__":
    main()