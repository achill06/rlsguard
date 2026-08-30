"""
fixer.py

Takes the detector's findings and generates corrected policy SQL for each
one. Infers the ownership column (the one that references auth.users) by
reading the table's actual column definitions, rather than assuming a
fixed name like `user_id`.

This does not need to be perfect. Every fix it proposes gets applied to a
disposable sandbox and empirically verified in Phase 6 (three-role probe
queries), and the orchestrator in Phase 7 retries or falls back to manual
review if verification fails. The fixer's job is to propose a reasonable
fix, not to be trusted blindly, that's the whole point of the
detect-fix-verify loop over a single-shot "fix it and hope" approach.

Usage:
    python fixer.py path/to/schema.sql
    python fixer.py path/to/schema.sql --out fixes.sql
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detector import detect, strip_comments, parse_policy, extract_balanced


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on a separator, ignoring separators inside nested parens."""
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def find_table_columns_block(schema_text: str, table_name: str):
    pattern = re.compile(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?"
        + re.escape(table_name)
        + r"\s*\(",
        re.IGNORECASE,
    )
    m = pattern.search(schema_text)
    if not m:
        return None
    open_idx = m.end() - 1
    content, _ = extract_balanced(schema_text, open_idx)
    return content


def infer_ownership_column(schema_text: str, table_name: str):
    """Return the column name that references auth.users, or a column
    named user_id/owner_id as a fallback, or None if nothing plausible
    is found."""
    block = find_table_columns_block(schema_text, table_name)
    if not block:
        return None

    columns = split_top_level(block)
    for col_def in columns:
        if re.search(r"references\s+(?:public\.)?auth\.users", col_def, re.IGNORECASE):
            return col_def.split()[0]

    for col_def in columns:
        first_word = col_def.split()[0].lower() if col_def.split() else ""
        if first_word in ("user_id", "owner_id"):
            return col_def.split()[0]

    return None


def get_policy_details(schema_text: str, table: str, policy_name: str):
    text = strip_comments(schema_text)
    statements = [s.strip() for s in text.split(";") if s.strip()]
    for stmt in statements:
        if re.match(r"create\s+policy", stmt.strip(), re.IGNORECASE):
            p = parse_policy(stmt)
            if p and p["table"] == table and p["name"] == policy_name:
                return p
    return None


def clauses_for_command(command: str, col: str):
    using_clause = ""
    check_clause = ""
    if command in ("select", "delete"):
        using_clause = f" using (auth.uid() = {col})"
    elif command == "insert":
        check_clause = f" with check (auth.uid() = {col})"
    else:  # update, all
        using_clause = f" using (auth.uid() = {col})"
        check_clause = f" with check (auth.uid() = {col})"
    return using_clause, check_clause


def generate_fix(schema_text: str, finding: dict):
    table = finding["table"]
    issue_type = finding["issue_type"]
    policy_name = finding.get("policy")
    col = infer_ownership_column(schema_text, table)

    if issue_type == "rls_not_enabled":
        if col is None:
            return {
                "manual_review": True,
                "sql": [],
                "description": (
                    f"Could not infer an ownership column for {table}. "
                    f"Enabling RLS with no matching policy would lock the "
                    f"table entirely. Needs manual review."
                ),
            }
        sql = [
            f"alter table public.{table} enable row level security;",
            f'create policy "{table}_select_own" on public.{table} '
            f"for select using (auth.uid() = {col});",
            f'create policy "{table}_insert_own" on public.{table} '
            f"for insert with check (auth.uid() = {col});",
            f'create policy "{table}_update_own" on public.{table} '
            f"for update using (auth.uid() = {col}) with check (auth.uid() = {col});",
            f'create policy "{table}_delete_own" on public.{table} '
            f"for delete using (auth.uid() = {col});",
        ]
        return {
            "manual_review": False,
            "sql": sql,
            "description": (
                f"Enabled RLS on {table} and added owner-scoped policies "
                f"for select/insert/update/delete, keyed on {col} = auth.uid()."
            ),
        }

    if issue_type in ("permissive_policy", "not_scoped_to_caller"):
        if col is None:
            return {
                "manual_review": True,
                "sql": [],
                "description": (
                    f"Could not infer an ownership column for {table}. "
                    f"Policy '{policy_name}' needs manual review."
                ),
            }
        policy = get_policy_details(schema_text, table, policy_name)
        command = policy["command"] if policy else "all"
        using_clause, check_clause = clauses_for_command(command, col)
        sql = [
            f'drop policy "{policy_name}" on public.{table};',
            f'create policy "{policy_name}" on public.{table} '
            f"for {command}{using_clause}{check_clause};",
        ]
        reason = (
            "was unconditionally true"
            if issue_type == "permissive_policy"
            else "never referenced the caller's identity"
        )
        return {
            "manual_review": False,
            "sql": sql,
            "description": (
                f"Policy '{policy_name}' on {table} {reason}. Replaced it "
                f"with an owner-scoped version keyed on {col} = auth.uid()."
            ),
        }

    if issue_type == "missing_with_check":
        if col is None:
            return {
                "manual_review": True,
                "sql": [],
                "description": (
                    f"Could not infer an ownership column for {table}. "
                    f"Policy '{policy_name}' needs manual review."
                ),
            }
        sql = [
            f'alter policy "{policy_name}" on public.{table} '
            f"with check (auth.uid() = {col});"
        ]
        return {
            "manual_review": False,
            "sql": sql,
            "description": (
                f"Added a WITH CHECK clause to INSERT policy '{policy_name}' "
                f"on {table}, requiring the inserted row's {col} to match "
                f"the caller."
            ),
        }

    if issue_type == "anon_role_overgranted":
        sql = [f"revoke all on public.{table} from anon;"]
        return {
            "manual_review": False,
            "sql": sql,
            "description": (
                f"Revoked anon's table-level grant on {table}, which had "
                f"no legitimate anonymous use case."
            ),
        }

    return {
        "manual_review": True,
        "sql": [],
        "description": f"Unknown issue_type '{issue_type}', needs manual review.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema_file", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Save combined fix SQL here")
    args = parser.parse_args()

    if not args.schema_file.exists():
        print(f"Schema file not found: {args.schema_file}", file=sys.stderr)
        sys.exit(1)

    schema_text = args.schema_file.read_text()
    findings = detect(schema_text)

    all_sql = []
    report = []
    for finding in findings:
        fix = generate_fix(schema_text, finding)
        report.append({**finding, **fix})
        print(f"\n--- {finding['table']} / {finding['issue_type']} "
              f"({finding.get('policy', '')}) ---")
        if fix["manual_review"]:
            print(f"  MANUAL REVIEW NEEDED: {fix['description']}")
        else:
            print(f"  {fix['description']}")
            for stmt in fix["sql"]:
                print(f"  > {stmt}")
            all_sql.extend(fix["sql"])

    if not findings:
        print("No findings, nothing to fix.")

    if args.out:
        args.out.write_text("\n".join(all_sql) + "\n" if all_sql else "")
        print(f"\nCombined fix SQL written to {args.out}")


if __name__ == "__main__":
    main()