"""
run_eval.py

Runs the detector and the full agent pipeline against every seeded schema
and scores them against expected_findings.json: precision, recall, and
false-positive rate for detection, plus a verified-fix rate for the
agent's detect-fix-verify loop.

Baseline scoring is intentionally not automated here. baseline_review.py
returns free-text prose, not structured findings, so matching it against
ground truth would mean a fuzzy keyword heuristic rather than an exact
comparison, and re-running it repeatedly costs API calls. Run
baseline/baseline_review.py per schema separately and compare by eye,
that's an honest limitation of the baseline's own design (a single-shot
prose response can't be graded as precisely as structured output), not
something this script should paper over with a fake precision number.

Usage:
    python run_eval.py
    python run_eval.py --out results.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "advanced"))
from detector import detect

DEFAULT_SCHEMAS_DIR = Path(__file__).parent / "schemas"
DEFAULT_EXPECTED = Path(__file__).parent / "expected_findings.json"


def normalize(findings):
    return set((f["table"], f["issue_type"], f.get("policy")) for f in findings)


def score_detector(schemas_dir: Path, expected: dict):
    total_tp = total_fp = total_fn = 0
    per_file = []

    for filename, data in expected["schemas"].items():
        schema_path = schemas_dir / filename
        if not schema_path.exists():
            print(f"  warning: {filename} not found, skipping", file=sys.stderr)
            continue

        schema_text = schema_path.read_text()
        actual = normalize(detect(schema_text))
        exp = normalize(data["findings"])

        tp = len(actual & exp)
        fp = len(actual - exp)
        fn = len(exp - actual)

        total_tp += tp
        total_fp += fp
        total_fn += fn
        per_file.append({"file": filename, "tp": tp, "fp": fp, "fn": fn})

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "per_file": per_file,
        "true_positives": total_tp,
        "false_positives": total_fp,
        "false_negatives": total_fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def score_agent(schemas_dir: Path, expected: dict):
    from agent import run as run_agent

    total_findings = 0
    total_verified = 0
    per_file = []

    for filename in expected["schemas"]:
        schema_path = schemas_dir / filename
        if not schema_path.exists():
            continue

        outcome = run_agent(schema_path)
        n_findings = len(outcome["findings"])
        n_verified = sum(1 for r in outcome["results"] if r["status"] == "verified")

        total_findings += n_findings
        total_verified += n_verified
        per_file.append(
            {"file": filename, "findings": n_findings, "verified": n_verified}
        )
        print(f"  {filename}: {n_verified}/{n_findings} verified")

    verified_rate = total_verified / total_findings if total_findings else 1.0

    return {
        "per_file": per_file,
        "total_findings": total_findings,
        "total_verified": total_verified,
        "total_manual_review": total_findings - total_verified,
        "verified_rate": round(verified_rate, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schemas-dir", type=Path, default=DEFAULT_SCHEMAS_DIR)
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    expected = json.loads(args.expected.read_text())

    print("Scoring detector against ground truth...")
    detector_scores = score_detector(args.schemas_dir, expected)

    print("\nRunning the full agent pipeline (detect -> fix -> sandbox -> verify)...")
    agent_scores = score_agent(args.schemas_dir, expected)

    summary = {"detector": detector_scores, "agent": agent_scores}

    print("\n" + "=" * 60)
    print("DETECTOR (structured, exact match against ground truth)")
    print(f"  precision: {detector_scores['precision']}")
    print(f"  recall:    {detector_scores['recall']}")
    print(f"  f1:        {detector_scores['f1']}")
    print(
        f"  TP={detector_scores['true_positives']} "
        f"FP={detector_scores['false_positives']} "
        f"FN={detector_scores['false_negatives']}"
    )
    print("\nAGENT (fix applied and empirically verified in sandbox)")
    print(
        f"  {agent_scores['total_verified']}/{agent_scores['total_findings']} "
        f"findings verified ({agent_scores['verified_rate'] * 100:.1f}%)"
    )
    print(f"  {agent_scores['total_manual_review']} flagged for manual review")
    print("=" * 60)
    print(
        "\nBaseline is scored separately by hand: run "
        "baseline/baseline_review.py against each schema and compare its "
        "prose output to eval/expected_findings.json yourself, see the "
        "module docstring for why that isn't automated here."
    )

    if args.out:
        args.out.write_text(json.dumps(summary, indent=2))
        print(f"\nFull results written to {args.out}")

    # Regression guard: fail the build if a real drop happens, not just
    # print numbers and exit clean regardless.
    if detector_scores["precision"] < 1.0 or detector_scores["recall"] < 1.0:
        print("\nREGRESSION: detector precision/recall dropped below 1.0", file=sys.stderr)
        sys.exit(1)
    if agent_scores["verified_rate"] < 0.90:
        print("\nREGRESSION: agent verified rate dropped below 0.90", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()