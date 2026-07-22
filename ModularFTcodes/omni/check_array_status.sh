#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"
MANIFEST_PATH="${MANIFEST_PATH:-$SCRIPT_DIR/proposed_experiment_manifest.tsv}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_all_deadlines}"
ARRAY_JOB_ID="${ARRAY_JOB_ID:-}"
if [[ -z "$ARRAY_JOB_ID" && -f "$OUTPUT_ROOT/array_submission.json" ]]; then
  ARRAY_JOB_ID="$(python3 "$SCRIPT_DIR/omni_array.py" marker-value --marker "$OUTPUT_ROOT/array_submission.json" --key array_job_id 2>/dev/null || true)"
fi

python3 "$SCRIPT_DIR/omni_array.py" status \
  --manifest "$MANIFEST_PATH" \
  --project-dir "$PROJECT_DIR" \
  --output-root "$OUTPUT_ROOT" \
  ${ARRAY_JOB_ID:+--array-job-id "$ARRAY_JOB_ID"}
