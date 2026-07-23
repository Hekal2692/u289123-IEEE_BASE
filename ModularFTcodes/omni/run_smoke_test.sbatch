#!/bin/bash -l
#SBATCH --job-name=hga-smoke
#SBATCH --time=4-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --signal=B:USR1@300
#SBATCH --output=logs/slurm/%x-%j.out
#SBATCH --error=logs/slurm/%x-%j.err

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PROJECT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_DIR/codes"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_all_deadlines}"
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

mkdir -p "$RUN_DIR" "$OUTPUT_ROOT/slurm" "$REPO_ROOT/logs/slurm"
cd "$CODE_DIR"
python main.py
