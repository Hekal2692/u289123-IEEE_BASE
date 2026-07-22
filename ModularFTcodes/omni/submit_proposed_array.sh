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
OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
PREFLIGHT_MARKER="${PREFLIGHT_MARKER:-$OMNI_STATE_DIR/preflight_success.json}"
SBATCH_SCRIPT_REL="ModularFTcodes/omni/run_proposed_array.sbatch"
ARRAY_EXPR="0-119%${MAX_CONCURRENT}"

bash "$SCRIPT_DIR/preflight_omni.sh"

git -C "$REPO_ROOT" update-index -q --refresh
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  echo "ERROR: Git working tree is not clean. Commit or stash changes before production submission." >&2
  git -C "$REPO_ROOT" status --short >&2
  exit 2
fi
CURRENT_SHA="$(git -C "$REPO_ROOT" rev-parse --verify HEAD)"
TESTED_SHA="$(python3 "$SCRIPT_DIR/omni_array.py" marker-value --marker "$PREFLIGHT_MARKER" --key git_commit_sha)"
if [[ "$CURRENT_SHA" != "$TESTED_SHA" ]]; then
  echo "ERROR: tested Git commit SHA ($TESTED_SHA) does not match current HEAD ($CURRENT_SHA)." >&2
  exit 2
fi

mkdir -p "$OUTPUT_ROOT/runs" "$OUTPUT_ROOT/slurm" "$REPO_ROOT/logs_proposed_all_deadlines/slurm"
export OUTPUT_ROOT MANIFEST_PATH GIT_COMMIT_SHA="$CURRENT_SHA" OMNI_STATE_DIR

printf 'Default MAX_CONCURRENT=%s; adjust with MAX_CONCURRENT=<n> according to Omni quotas.\n' "$MAX_CONCURRENT"
printf 'sbatch --parsable --array=%q %s\n' "$ARRAY_EXPR" "$SBATCH_SCRIPT_REL"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry run only; no job submitted."
  exit 0
fi

cd "$REPO_ROOT"
ARRAY_JOB_ID="$(sbatch --parsable --array="$ARRAY_EXPR" "$SBATCH_SCRIPT_REL")"
python3 "$SCRIPT_DIR/omni_array.py" write-submission \
  --output-root "$OUTPUT_ROOT" \
  --array-job-id "$ARRAY_JOB_ID" \
  --manifest "$MANIFEST_PATH" \
  --max-concurrent "$MAX_CONCURRENT" \
  --git-commit-sha "$CURRENT_SHA" \
  --array-expression "$ARRAY_EXPR"
printf 'Submitted SLURM array job: %s\n' "$ARRAY_JOB_ID"
