#!/bin/bash -l
#SBATCH --job-name=ftcodes_allD
#SBATCH --time=5-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-119
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

# Default grid: 3 AMs x 4 deadline ratios x 10 seeds = 120 independent Slurm tasks.
# Example custom grid:
#   AM_IDS="AM250 AM500" BASE_DEADLINES="2700 4300" DEADLINE_RATIOS="0.90 0.80" SEEDS="1001 1002" sbatch --array=0-7 cluster_all_deadlines.sh

set -euo pipefail

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
read -r -a AM_ID_LIST <<< "${AM_IDS:-AM100 AM250 AM500}"
read -r -a BASE_DEADLINE_LIST <<< "${BASE_DEADLINES:-2600 2700 4300}"
read -r -a DEADLINE_RATIO_LIST <<< "${DEADLINE_RATIOS:-1.00 0.90 0.80 0.70}"
read -r -a SEED_LIST <<< "${SEEDS:-1001 1002 1003 1004 1005 1006 1007 1008 1009 1010}"

TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
N_AM=${#AM_ID_LIST[@]}
N_RATIOS=${#DEADLINE_RATIO_LIST[@]}
N_SEEDS=${#SEED_LIST[@]}
TOTAL=$((N_AM * N_RATIOS * N_SEEDS))

if (( ${#AM_ID_LIST[@]} != ${#BASE_DEADLINE_LIST[@]} )); then
  echo "ERROR: AM_IDS and BASE_DEADLINES must have the same length." >&2
  exit 2
fi

if (( TASK_ID >= TOTAL )); then
  echo "Skipping task $TASK_ID; configured grid has only $TOTAL tasks."
  exit 0
fi

TASKS_PER_AM=$((N_RATIOS * N_SEEDS))
AM_INDEX=$((TASK_ID / TASKS_PER_AM))
REM=$((TASK_ID % TASKS_PER_AM))
RATIO_INDEX=$((REM / N_SEEDS))
SEED_INDEX=$((REM % N_SEEDS))

export AM_ID="${AM_ID_LIST[$AM_INDEX]}"
export BASE_DEADLINE="${BASE_DEADLINE_LIST[$AM_INDEX]}"
export DEADLINE_RATIO="${DEADLINE_RATIO_LIST[$RATIO_INDEX]}"
export SEED="${SEED_LIST[$SEED_INDEX]}"
export VARIANT="${VARIANT:-proposed}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs}"
export CONFIG_TAG="${CONFIG_TAG:-all_deadlines}"

exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
