"""
report.py

Formats the orchestrator's results into a severity-ranked markdown report.
"""

SEVERITY_ORDER = {
    "rls_not_enabled": (1, "critical"),
    "permissive_policy": (1, "critical"),
    "missing_with_check": (2, "high"),
    "not_scoped_to_caller": (2, "high"),
    "anon_role_overgranted": (3, "medium"),
}


def severity_for(issue_type: str):
    return SEVERITY_ORDER.get(issue_type, (4, "unknown"))


def generate_report(schema_name: str, results: list) -> str:
    if not results:
        return f"# rlsguard report: {schema_name}\n\nNo RLS issues found.\n"

    sorted_results = sorted(
        results,
        key=lambda r: (
            severity_for(r["finding"]["issue_type"])[0],
            r["finding"]["table"],
        ),
    )

    lines = [f"# rlsguard report: {schema_name}\n"]
    lines.append("| Table | Issue | Severity | Status | Detail |")
    lines.append("|---|---|---|---|---|")

    for r in sorted_results:
        finding = r["finding"]
        _, sev_label = severity_for(finding["issue_type"])
        policy = finding.get("policy", "")
        table_cell = finding["table"] + (f" (`{policy}`)" if policy else "")
        status_label = "verified" if r["status"] == "verified" else "needs manual review"
        lines.append(
            f"| {table_cell} | {finding['issue_type']} | {sev_label} | "
            f"{status_label} | {r['reason']} |"
        )

    verified_count = sum(1 for r in results if r["status"] == "verified")
    lines.append("")
    lines.append(
        f"**{verified_count}/{len(results)} findings verified and fixed. "
        f"{len(results) - verified_count} flagged for manual review.**"
    )

    return "\n".join(lines)