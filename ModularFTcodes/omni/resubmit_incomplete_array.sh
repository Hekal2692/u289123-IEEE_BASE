#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi
if [[ "$#" -ne 0 ]]; then
  echo "Usage: $0 [--dry-run]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"
MANIFEST_PATH="${MANIFEST_PATH:-$SCRIPT_DIR/proposed_experiment_manifest.tsv}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_all_deadlines}"
MAX_CONCURRENT="${MAX_CONCURRENT:-40}"
SBATCH_SCRIPT_REL="ModularFTcodes/omni/run_proposed_array.sbatch"
ARRAY_JOB_ID="${ARRAY_JOB_ID:-}"
if [[ -z "$ARRAY_JOB_ID" && -f "$OUTPUT_ROOT/array_submission.json" ]]; then
  ARRAY_JOB_ID="$(python3 "$SCRIPT_DIR/omni_array.py" marker-value --marker "$OUTPUT_ROOT/array_submission.json" --key array_job_id 2>/dev/null || true)"
fi

python3 "$SCRIPT_DIR/omni_array.py" validate-manifest --manifest "$MANIFEST_PATH" --project-dir "$PROJECT_DIR"
python3 "$SCRIPT_DIR/omni_array.py" incomplete-expression \
  --manifest "$MANIFEST_PATH" \
  --project-dir "$PROJECT_DIR" \
  --output-root "$OUTPUT_ROOT" \
  ${ARRAY_JOB_ID:+--array-job-id "$ARRAY_JOB_ID"}
EXPR="$(python3 "$SCRIPT_DIR/omni_array.py" incomplete-expression \
  --manifest "$MANIFEST_PATH" \
  --project-dir "$PROJECT_DIR" \
  --output-root "$OUTPUT_ROOT" \
  ${ARRAY_JOB_ID:+--array-job-id "$ARRAY_JOB_ID"} \
  --plain)"

if [[ -z "$EXPR" ]]; then
  echo "No resubmittable incomplete tasks found."
  exit 0
fi

ARRAY_EXPR="${EXPR}%${MAX_CONCURRENT}"
printf 'Default MAX_CONCURRENT=%s; adjust with MAX_CONCURRENT=<n> according to Omni quotas.\n' "$MAX_CONCURRENT"
printf 'sbatch --parsable --array=%q %s\n' "$ARRAY_EXPR" "$SBATCH_SCRIPT_REL"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry run only; no job submitted."
  exit 0
fi

mkdir -p "$OUTPUT_ROOT/slurm" "$REPO_ROOT/logs_proposed_all_deadlines/slurm"
export OUTPUT_ROOT MANIFEST_PATH OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
cd "$REPO_ROOT"
RESUBMIT_JOB_ID="$(sbatch --parsable --array="$ARRAY_EXPR" "$SBATCH_SCRIPT_REL")"
printf 'Submitted incomplete-task SLURM array job: %s\n' "$RESUBMIT_JOB_ID"
