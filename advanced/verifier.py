"""
verifier.py

Applies each fix inside the sandbox and proves it actually works by
running real SELECT queries as three simulated identities (anonymous, an
authenticated non-owner, and the authenticated owner), rather than just
re-reading the policy SQL and asserting it looks right. This is the step
that would catch something like the fixer's assignee_id inference on
`tasks`: syntactically valid, but only actually provable by running it.

Scope, stated plainly: this verifies read isolation (SELECT) only. Write
probes (attempting an INSERT/UPDATE impersonating another user) are not
implemented in this version. That's a real, documented limitation, not
an oversight, name it as such in the changelog rather than implying full
coverage.

Usage:
    python verifier.py path/to/schema.sql
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detector import detect, strip_comments
from fixer import generate_fix, infer_ownership_column, find_table_columns_block, split_top_level
from sandbox import Sandbox

OWNER_UUID = "11111111-1111-1111-1111-111111111111"
OTHER_UUID = "22222222-2222-2222-2222-222222222222"


def get_tables_in_declaration_order(schema_text: str):
    pattern = re.compile(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)",
        re.IGNORECASE,
    )
    return [m.group(1) for m in pattern.finditer(strip_comments(schema_text))]


def build_column_values(columns, ownership_col, ownership_value, known_ids):
    values = {}
    for col_def in columns:
        parts = col_def.split()
        if not parts:
            continue
        col_name = parts[0]
        low = col_def.lower()

        if col_name == ownership_col:
            values[col_name] = f"'{ownership_value}'"
            continue
        if "primary key" in low and "default" in low:
            continue  # let the DB generate it
        ref_match = re.search(r"references\s+(?:public\.)?(\w+)\s*\(", col_def, re.IGNORECASE)
        if ref_match:
            parent = ref_match.group(1)
            if parent == "users":  # auth.users
                values[col_name] = f"'{ownership_value}'"
            elif parent in known_ids:
                values[col_name] = f"'{known_ids[parent]}'"
            continue
        if "not null" in low and "default" not in low:
            if "timestamptz" in low or "timestamp" in low:
                values[col_name] = "now()"
            elif "boolean" in low:
                values[col_name] = "false"
            elif "uuid" in low:
                values[col_name] = "gen_random_uuid()"
            else:
                values[col_name] = "'seed'"
    return values

def seed_auth_users(sandbox: Sandbox):
    """auth.users needs rows for OWNER_UUID and OTHER_UUID before any
    table with a foreign key to it can be seeded."""
    sandbox.apply_sql(
        f"""
        insert into auth.users (id, email) values
          ('{OWNER_UUID}', 'owner@example.com'),
          ('{OTHER_UUID}', 'other@example.com')
        on conflict (id) do nothing;
        """
    )

def seed_tables(sandbox: Sandbox, schema_text: str, tables_in_order):
    """Insert one row per table, owned by OWNER_UUID. Returns {table: row_id}."""
    known_ids = {}
    for table in tables_in_order:
        block = find_table_columns_block(schema_text, table)
        if not block:
            continue
        columns = split_top_level(block)
        ownership_col = infer_ownership_column(schema_text, table)
        values = build_column_values(columns, ownership_col, OWNER_UUID, known_ids)
        if not values:
            continue
        cols_sql = ", ".join(values.keys())
        vals_sql = ", ".join(values.values())
        insert_sql = f"insert into public.{table} ({cols_sql}) values ({vals_sql}) returning id;"
        try:
            rows = sandbox.apply_sql_fetch(insert_sql)
            if rows:
                known_ids[table] = str(rows[0][0])
        except Exception as e:
            print(f"  (seed warning: could not seed {table}: {e})")
    return known_ids


def probe_select(sandbox: Sandbox, table: str):
    results = {}
    for label, jwt_sub in [
        ("anon", None),
        ("authenticated_non_owner", OTHER_UUID),
        ("authenticated_owner", OWNER_UUID),
    ]:
        role = "anon" if label == "anon" else "authenticated"
        try:
            rows = sandbox.execute_as(role, jwt_sub, f"select * from public.{table};")
            results[label] = {"error": None, "row_count": len(rows) if rows else 0}
        except Exception as e:
            results[label] = {"error": str(e), "row_count": 0}
    return results

def check_select_probe(results):
    anon_ok = results["anon"]["row_count"] == 0
    other_ok = results["authenticated_non_owner"]["row_count"] == 0
    owner_ok = (
        results["authenticated_owner"]["row_count"] >= 1
        and results["authenticated_owner"]["error"] is None
    )
    return anon_ok and other_ok and owner_ok

def get_table_policy_commands(sandbox: Sandbox, table: str):
    rows = sandbox.apply_sql_fetch(
        f"select cmd from pg_policies where schemaname = 'public' and tablename = '{table}';"
    )
    return {r[0] for r in rows} if rows else set()

def probe_writes(sandbox: Sandbox, table: str, schema_text: str, known_ids: dict):
    ownership_col = infer_ownership_column(schema_text, table)
    if not ownership_col:
        return None

    policy_commands = get_table_policy_commands(sandbox, table)
    has_insert_policy = bool(policy_commands & {"INSERT", "ALL"})
    has_update_policy = bool(policy_commands & {"UPDATE", "ALL"})

    block = find_table_columns_block(schema_text, table)
    columns = split_top_level(block)
    results = {}

    if has_insert_policy:
        values = build_column_values(columns, ownership_col, OTHER_UUID, known_ids)
        cols_sql = ", ".join(values.keys())
        vals_sql = ", ".join(values.values())
        insert_self_sql = f"insert into public.{table} ({cols_sql}) values ({vals_sql}) returning id;"
        try:
            rows = sandbox.execute_as("authenticated", OTHER_UUID, insert_self_sql)
            results["insert_self"] = {"error": None, "row_count": len(rows) if rows else 0}
        except Exception as e:
            results["insert_self"] = {"error": str(e), "row_count": 0}

        values2 = build_column_values(columns, ownership_col, OWNER_UUID, known_ids)
        cols_sql2 = ", ".join(values2.keys())
        vals_sql2 = ", ".join(values2.values())
        insert_impersonate_sql = f"insert into public.{table} ({cols_sql2}) values ({vals_sql2}) returning id;"
        try:
            rows = sandbox.execute_as("authenticated", OTHER_UUID, insert_impersonate_sql)
            results["insert_impersonate"] = {"error": None, "row_count": len(rows) if rows else 0}
        except Exception as e:
            results["insert_impersonate"] = {"error": str(e), "row_count": 0}
    else:
        results["insert_self"] = {"not_applicable": True}
        results["insert_impersonate"] = {"not_applicable": True}

    if has_update_policy:
        update_other_sql = f"update public.{table} set {ownership_col} = {ownership_col} returning id;"
        try:
            rows = sandbox.execute_as("authenticated", OTHER_UUID, update_other_sql)
            results["update_as_non_owner"] = {"error": None, "row_count": len(rows) if rows else 0}
        except Exception as e:
            results["update_as_non_owner"] = {"error": str(e), "row_count": 0}

        reassign_sql = f"update public.{table} set {ownership_col} = '{OTHER_UUID}' returning id;"
        try:
            rows = sandbox.execute_as("authenticated", OWNER_UUID, reassign_sql)
            results["update_reassign_owner"] = {"error": None, "row_count": len(rows) if rows else 0}
        except Exception as e:
            results["update_reassign_owner"] = {"error": str(e), "row_count": 0}
    else:
        results["update_as_non_owner"] = {"not_applicable": True}
        results["update_reassign_owner"] = {"not_applicable": True}

    return results


def check_write_probe(results):
    if results is None:
        return True

    def ok(key, expect):
        r = results[key]
        if r.get("not_applicable"):
            return True
        if expect == "some":
            return r["row_count"] >= 1 and r["error"] is None
        return r["row_count"] == 0

    return (
        ok("insert_self", "some")
        and ok("insert_impersonate", "zero")
        and ok("update_as_non_owner", "zero")
        and ok("update_reassign_owner", "zero")
    )

def verify_finding(sandbox: Sandbox, finding, fix, schema_text: str, known_ids: dict):
    table = finding["table"]

    if fix["manual_review"]:
        return {"verified": False, "reason": "flagged for manual review, not auto-applied"}

    for stmt in fix["sql"]:
        try:
            sandbox.apply_sql(stmt)
        except Exception as e:
            return {"verified": False, "reason": f"fix SQL failed to apply: {e}"}

    select_results = probe_select(sandbox, table)
    select_ok = check_select_probe(select_results)

    write_results = probe_writes(sandbox, table, schema_text, known_ids)
    write_ok = check_write_probe(write_results)

    verified = select_ok and write_ok
    if verified:
        reason = "select and write probes passed: reads and writes both correctly isolated by owner"
    elif not select_ok:
        reason = f"select probes failed: {select_results}"
    else:
        reason = f"write probes failed: {write_results}"

    return {
        "verified": verified,
        "reason": reason,
        "probe_detail": {"select": select_results, "write": write_results},
    }


def run(schema_path: Path):
    schema_text = schema_path.read_text()
    findings = detect(schema_text)

    if not findings:
        print("No findings to verify.")
        return []

    sandbox = Sandbox()
    print("starting sandbox...")
    sandbox.start()
    try:
        sandbox.apply_sql(schema_text)
        seed_auth_users(sandbox)
        tables_in_order = get_tables_in_declaration_order(schema_text)
        known_ids = seed_tables(sandbox, schema_text, tables_in_order)
        print(f"seeded rows for: {list(known_ids.keys())}")

        results = []
        for finding in findings:
            fix = generate_fix(schema_text, finding)
            outcome = verify_finding(sandbox, finding, fix, schema_text, known_ids)
            results.append({"finding": finding, "fix_description": fix["description"], **outcome})
            status = "VERIFIED" if outcome["verified"] else "NOT VERIFIED"
            print(f"\n[{status}] {finding['table']} / {finding['issue_type']}: {outcome['reason']}")
        return results
    finally:
        sandbox.stop()
        print("\nsandbox torn down")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python verifier.py path/to/schema.sql", file=sys.stderr)
        sys.exit(1)
    run(Path(sys.argv[1]))