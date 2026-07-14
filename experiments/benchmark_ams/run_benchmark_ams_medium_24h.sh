#!/bin/bash -l
#SBATCH --partition=medium
#SBATCH --time=1-00:00:00
#SBATCH --job-name=benchmark_ams
#SBATCH --array=0-39
#SBATCH --output=logs/benchmark_ams/%x_%A_%a.out
#SBATCH --error=logs/benchmark_ams/%x_%A_%a.err

set -euo pipefail

echo "submit_pwd=$(pwd)"
SUBMIT_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}"
if [[ -d "$SUBMIT_DIR/ModularFTcodes" && -d "$SUBMIT_DIR/experiments/benchmark_ams" ]]; then
  WORKTREE_ROOT="$SUBMIT_DIR"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  WORKTREE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
cd "$WORKTREE_ROOT"
echo "worktree_pwd=$(pwd)"

mkdir -p logs/benchmark_ams results/benchmark_ams results/benchmark_ams/summaries
export MPLBACKEND=Agg

if command -v module >/dev/null 2>&1; then
  module --ignore-cache purge
  module --ignore-cache load "${PYTHON_MODULE:-python/3.11.2}"
fi

if [[ -x "$HOME/venvs/ftcodes311/bin/python" ]]; then
  source "$HOME/venvs/ftcodes311/bin/activate"
elif [[ -x "ModularFTcodes/.venv/bin/python" ]]; then
  source "ModularFTcodes/.venv/bin/activate"
fi

if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON_BIN="$VIRTUAL_ENV/bin/python"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
else
  PYTHON_BIN="$(command -v python)"
fi

"$PYTHON_BIN" -V
echo "$PYTHON_BIN"

DEADLINE_RATIOS=(1.00 0.90 0.80 0.70)
SEEDS=(1001 1002 1003 1004 1005 1006 1007 1008 1009 1010)
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
N_RATIOS=${#DEADLINE_RATIOS[@]}
N_SEEDS=${#SEEDS[@]}
TOTAL=$((N_RATIOS * N_SEEDS))

if (( TASK_ID >= TOTAL )); then
  echo "Skipping task $TASK_ID; configured grid has only $TOTAL tasks."
  exit 0
fi

RATIO_INDEX=$((TASK_ID / N_SEEDS))
SEED_INDEX=$((TASK_ID % N_SEEDS))
DEADLINE_RATIO="${DEADLINE_RATIOS[$RATIO_INDEX]}"
SEED="${SEEDS[$SEED_INDEX]}"
RATIO_LABEL="ratio${DEADLINE_RATIO/./}"
TASK_LABEL="${RATIO_LABEL}_seed${SEED}"
RUN_TAG="${SLURM_ARRAY_JOB_ID:-local}_${SLURM_ARRAY_TASK_ID:-0}"

echo "Running WATERS100 validation for task ${TASK_LABEL}"
"$PYTHON_BIN" experiments/benchmark_ams/validate_benchmark_ams.py > "logs/benchmark_ams/validation_${TASK_LABEL}.log" 2>&1

echo "Running WATERS100 benchmark ${TASK_LABEL}"
"$PYTHON_BIN" experiments/benchmark_ams/run_benchmark_ams.py \
  --deadline-ratios "$DEADLINE_RATIO" \
  --seeds "$SEED" \
  --run-tag "$RUN_TAG" \
  --output-root results/benchmark_ams/runs \
  --log-file "logs/benchmark_ams/run_${TASK_LABEL}.log" \
  --summary-csv "results/benchmark_ams/summaries/benchmark_ams_${TASK_LABEL}.csv"

echo "Task summary: results/benchmark_ams/summaries/benchmark_ams_${TASK_LABEL}.csv"
echo "After all array tasks finish, collect one combined CSV with:"
echo "python experiments/benchmark_ams/run_benchmark_ams.py --collect-only --output-root results/benchmark_ams/runs --summary-csv results/benchmark_ams/benchmark_ams_summary.csv"
