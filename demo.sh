#!/usr/bin/env bash
set -e

SCHEMA="eval/schemas/08_dashboard_multi_issue.sql"

banner() {
  echo ""
  echo "================================================================"
  echo "  $1"
  echo "================================================================"
  echo ""
}

pause() {
  echo ""
  read -p ">>> Press Enter to run this step... " _
  echo ""
}

banner "Pre-flight checks"

if [ -z "$GEMINI_API_KEY" ]; then
  echo "ERROR: GEMINI_API_KEY is not set. Run: export GEMINI_API_KEY=your_key"
  exit 1
fi
echo "GEMINI_API_KEY is set."

if ! docker info > /dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Docker before running this demo."
  exit 1
fi
echo "Docker is running."

docker rm -f rlsguard-sandbox > /dev/null 2>&1 || true
echo "Cleared any leftover sandbox container."

pause

banner "STEP 1 / 3 -- Baseline: one prompt, no tools, no proof"
echo "This is what most people would actually do: ask an AI once, get prose back."
echo ""
echo "\$ python3 baseline/baseline_review.py $SCHEMA"
pause
python3 baseline/baseline_review.py "$SCHEMA"

banner "STEP 2 / 3 -- rlsguard: detect, fix, apply, and PROVE by executing real queries"
echo "Every fix below is verified by running actual SELECT queries as three"
echo "simulated identities: anonymous, an authenticated non-owner, and the"
echo "authenticated owner. VERIFIED means denied/denied/allowed was proven,"
echo "not claimed."
echo ""
echo "\$ python3 advanced/agent.py $SCHEMA --out /tmp/report.md"
pause
python3 advanced/agent.py "$SCHEMA" --out /tmp/report.md

echo ""
echo "--- Generated report (/tmp/report.md) ---"
cat /tmp/report.md

banner "STEP 3 / 3 -- Full evaluation across all 11 seeded schemas"
echo "\$ cat eval/results.json"
pause
python3 -m json.tool eval/results.json

banner "Done. Full iteration history and honest limitations: CHANGELOG.md"