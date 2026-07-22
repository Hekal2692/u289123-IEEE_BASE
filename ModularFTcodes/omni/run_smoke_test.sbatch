#!/usr/bin/env bash
#SBATCH --job-name=hga-smoke
#SBATCH --partition=medium
#SBATCH --time=04:00:00
#SBATCH --requeue
#SBATCH --signal=B:USR1@300
#SBATCH --output=logs_proposed_all_deadlines/slurm/smoke-%j.out
#SBATCH --error=logs_proposed_all_deadlines/slurm/smoke-%j.err

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PROJECT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_DIR/codes"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_all_deadlines}"
OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
READY_MARKER="${READY_MARKER:-$OMNI_STATE_DIR/environment_ready.json}"
VENV="${VENV:-$HOME/venvs/ftcodes311}"

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
python "$SCRIPT_DIR/omni_array.py" check-environment --marker "$READY_MARKER" --project-dir "$PROJECT_DIR"

export AM_ID=AM100
export WORKLOAD=AM100
export BASE_DEADLINE=2600
export DEADLINE_RATIO=1.00
export SEED=1001
export VARIANT=smoke
export RUN_KEY=AM100__ratio1.00__seed1001__smoke
export RUN_DIR="$OUTPUT_ROOT/smoke/$RUN_KEY"
export CHECKPOINT_PATH="$RUN_DIR/checkpoint_latest.pkl"
export OUTPUT_ROOT
export PLATFORMS_DIR="${PLATFORMS_DIR:-$PROJECT_DIR/Platforms}"
export REQUIRE_ENV_CONFIG=1
export AUTO_RESUME=1
export SYSTEM_LEVEL_GENERATIONS="${SYSTEM_LEVEL_GENERATIONS:-2}"
export PARTITION_GENERATIONS="${PARTITION_GENERATIONS:-2}"
export SYSTEM_LEVEL_POPULATION_SIZE="${SYSTEM_LEVEL_POPULATION_SIZE:-4}"
export PARTITION_POPULATION_SIZE="${PARTITION_POPULATION_SIZE:-4}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-$SEED}"
export MPLBACKEND=Agg
export PYTHONPATH="$CODE_DIR:${PYTHONPATH:-}"
export GIT_COMMIT_SHA="${GIT_COMMIT_SHA:-$(git -C "$PROJECT_DIR" rev-parse --verify HEAD 2>/dev/null || true)}"

mkdir -p "$RUN_DIR" "$OUTPUT_ROOT/slurm" "$REPO_ROOT/logs_proposed_all_deadlines/slurm"
cd "$CODE_DIR"
python main.py
