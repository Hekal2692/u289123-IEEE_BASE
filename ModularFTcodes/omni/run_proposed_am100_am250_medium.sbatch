#!/bin/bash -l
#SBATCH --job-name=hga-100-250
#SBATCH --time=1-00:00:00
#SBATCH --partition=medium
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-79
#SBATCH --signal=B:USR1@300
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

set -euo pipefail

if [[ -n "${SLURM_SUBMIT_DIR:-}" && -d "$SLURM_SUBMIT_DIR/ModularFTcodes/omni" ]]; then
  REPO_ROOT="$(cd "$SLURM_SUBMIT_DIR" && pwd)"
  PROJECT_DIR="$REPO_ROOT/ModularFTcodes"
  SCRIPT_DIR="$PROJECT_DIR/omni"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
  REPO_ROOT="$(cd "$PROJECT_DIR/.." && pwd)"
fi
CODE_DIR="$PROJECT_DIR/codes"
MANIFEST_PATH="${MANIFEST_PATH:-$SCRIPT_DIR/proposed_am100_am250_medium_manifest.tsv}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_am100_am250_medium}"
OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
PYTHON_MODULE="${PYTHON_MODULE:-python/3.11.2}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
VENV="${VENV:-$HOME/venvs/ftcodes311}"
REQ_FILE="$PROJECT_DIR/requirements.txt"

if command -v module >/dev/null 2>&1; then
  module --ignore-cache purge
  module --ignore-cache load "$PYTHON_MODULE"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required")'

mkdir -p "$OMNI_STATE_DIR" "$(dirname "$VENV")"
LOCK_FILE="$OMNI_STATE_DIR/environment.lock"
(
  flock 9
  if [[ ! -d "$VENV" ]]; then
    "$PYTHON_BIN" -m venv "$VENV"
  fi
  source "$VENV/bin/activate"
  REQ_HASH="$(sha256sum "$REQ_FILE" | awk '{print $1}')"
  MARKER="$VENV/.requirements-$REQ_HASH.installed"
  if [[ ! -f "$MARKER" ]]; then
    python -m pip install -U pip
    python -m pip install -r "$REQ_FILE"
    rm -f "$VENV"/.requirements-*.installed
    touch "$MARKER"
  fi
) 9>"$LOCK_FILE"

source "$VENV/bin/activate"
PYTHON_BIN=python
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
