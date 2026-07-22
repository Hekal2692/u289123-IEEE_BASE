#!/bin/bash -l
#SBATCH --job-name=hga-proposed
#SBATCH --time=4-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-119
#SBATCH --signal=B:USR1@300
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PROJECT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_DIR/codes"
MANIFEST_PATH="${MANIFEST_PATH:-$SCRIPT_DIR/proposed_experiment_manifest.tsv}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_all_deadlines}"
OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
READY_MARKER="${READY_MARKER:-$OMNI_STATE_DIR/environment_ready.json}"
PYTHON_MODULE="${PYTHON_MODULE:-python/3.11.2}"
VENV="${VENV:-$HOME/venvs/ftcodes311}"

if command -v module >/dev/null 2>&1; then
  module --ignore-cache purge
  module --ignore-cache load "$PYTHON_MODULE"
fi

if [[ -f "$READY_MARKER" ]]; then
  MARKER_VENV="$(python3 "$SCRIPT_DIR/omni_array.py" marker-value --marker "$READY_MARKER" --key venv 2>/dev/null || true)"
  if [[ -n "$MARKER_VENV" ]]; then
    VENV="$MARKER_VENV"
  fi
fi
if [[ ! -d "$VENV" ]]; then
  echo "ERROR: Omni environment is not ready; missing venv: $VENV" >&2
  exit 2
fi

source "$VENV/bin/activate"
PYTHON_BIN="${PYTHON_BIN:-python}"
"$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" check-environment --marker "$READY_MARKER" --project-dir "$PROJECT_DIR"
"$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" validate-manifest --manifest "$MANIFEST_PATH" --project-dir "$PROJECT_DIR"

TASK_ID="${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID is required}"
eval "$("$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" export-row --manifest "$MANIFEST_PATH" --array-index "$TASK_ID" --project-dir "$PROJECT_DIR")"

CALCULATED_DEADLINE="$("$PYTHON_BIN" -c 'import os; print(int(round(float(os.environ["BASE_DEADLINE"]) * float(os.environ["DEADLINE_RATIO"]))))')"
if [[ "$CALCULATED_DEADLINE" != "$ACTUAL_DEADLINE" ]]; then
  echo "ERROR: calculated deadline $CALCULATED_DEADLINE does not match manifest actual_deadline $ACTUAL_DEADLINE" >&2
  exit 2
fi

export OUTPUT_ROOT="$(cd "$(dirname "$OUTPUT_ROOT")" && pwd)/$(basename "$OUTPUT_ROOT")"
export RUN_DIR="$OUTPUT_ROOT/runs/$RUN_KEY"
export CHECKPOINT_PATH="$RUN_DIR/checkpoint_latest.pkl"
export PLATFORMS_DIR="${PLATFORMS_DIR:-$PROJECT_DIR/Platforms}"
export REQUIRE_ENV_CONFIG=1
export AUTO_RESUME=1
export PYTHONHASHSEED="${PYTHONHASHSEED:-$SEED}"
export MPLBACKEND=Agg
export PYTHONPATH="$CODE_DIR:${PYTHONPATH:-}"
export GIT_COMMIT_SHA="${GIT_COMMIT_SHA:-$(git -C "$PROJECT_DIR" rev-parse --verify HEAD 2>/dev/null || true)}"

mkdir -p "$RUN_DIR" "$OUTPUT_ROOT/slurm" "$REPO_ROOT/logs/slurm"

if "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" check-complete --manifest "$MANIFEST_PATH" --array-index "$TASK_ID" --output-root "$OUTPUT_ROOT"; then
  echo "already completed: $RUN_KEY"
  exit 0
fi

if [[ -f "$CHECKPOINT_PATH" ]]; then
  if "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" check-checkpoint --manifest "$MANIFEST_PATH" --array-index "$TASK_ID" --checkpoint-path "$CHECKPOINT_PATH"; then
    export RESUME_FROM="$CHECKPOINT_PATH"
  else
    "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" write-status \
      --state CHECKPOINT_INCOMPATIBLE \
      --message "checkpoint does not match selected manifest row" \
      --manifest "$MANIFEST_PATH" \
      --array-index "$TASK_ID" \
      --output-root "$OUTPUT_ROOT"
    exit 2
  fi
fi

"$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" write-status \
  --state RUNNING \
  --message "array task started" \
  --manifest "$MANIFEST_PATH" \
  --array-index "$TASK_ID" \
  --output-root "$OUTPUT_ROOT"

cat <<EOF
Selected configuration:
  SLURM_ARRAY_TASK_ID=$TASK_ID
  RUN_KEY=$RUN_KEY
  AM_ID=$AM_ID
  workload=$WORKLOAD
  BASE_DEADLINE=$BASE_DEADLINE
  DEADLINE_RATIO=$DEADLINE_RATIO
  actual_deadline=$ACTUAL_DEADLINE
  SEED=$SEED
  VARIANT=$VARIANT
  RUN_DIR=$RUN_DIR
  CHECKPOINT_PATH=$CHECKPOINT_PATH
  RESUME_FROM=${RESUME_FROM:-}
EOF

cd "$CODE_DIR"
child_pid=""
forwarded_signal=0
forward_signal() {
  local sig="$1"
  forwarded_signal=1
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -s "$sig" "$child_pid" 2>/dev/null || true
  fi
}
trap 'forward_signal USR1' USR1
trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT

set +e
"$PYTHON_BIN" main.py &
child_pid=$!
while true; do
  wait "$child_pid"
  rc=$?
  if (( rc >= 128 )) && kill -0 "$child_pid" 2>/dev/null; then
    continue
  fi
  break
done
set -e
trap - USR1 TERM INT

if [[ "$rc" -eq 0 ]]; then
  if "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" check-complete --manifest "$MANIFEST_PATH" --array-index "$TASK_ID" --output-root "$OUTPUT_ROOT"; then
    exit 0
  fi
  "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" write-status \
    --state FAILED \
    --message "main.py exited 0 but valid _SUCCESS/run_summary.json was not found" \
    --exit-code 3 \
    --manifest "$MANIFEST_PATH" \
    --array-index "$TASK_ID" \
    --output-root "$OUTPUT_ROOT"
  exit 3
fi

STATUS_STATE="$("$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" marker-value --marker "$RUN_DIR/run_status.json" --key state 2>/dev/null || true)"
if [[ "$STATUS_STATE" == "CHECKPOINT_INCOMPATIBLE" ]]; then
  exit "$rc"
fi
if [[ "$rc" -eq 99 || "$forwarded_signal" -eq 1 ]]; then
  "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" write-status \
    --state INTERRUPTED \
    --message "array task interrupted; checkpoint retained when available" \
    --exit-code "$rc" \
    --manifest "$MANIFEST_PATH" \
    --array-index "$TASK_ID" \
    --output-root "$OUTPUT_ROOT"
else
  "$PYTHON_BIN" "$SCRIPT_DIR/omni_array.py" write-status \
    --state FAILED \
    --message "main.py failed" \
    --exit-code "$rc" \
    --manifest "$MANIFEST_PATH" \
    --array-index "$TASK_ID" \
    --output-root "$OUTPUT_ROOT"
fi
exit "$rc"
