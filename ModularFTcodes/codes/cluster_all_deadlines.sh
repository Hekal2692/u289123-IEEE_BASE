#!/bin/bash -l
#SBATCH --job-name=ftcodes_allD
#SBATCH --time=2-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-11
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

# Default grid: 3 AM sizes x 4 deadline settings = 12 independent Slurm tasks.
# To run a smaller custom grid, set AM_SIZES/DEADLINE_PERCENTS and submit with
# a matching --array range, e.g.:
#   AM_SIZES="250T 500T" DEADLINE_PERCENTS="90 80" sbatch --array=0-3 cluster_all_deadlines.sh

set -euo pipefail

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
read -r -a AM_SIZE_LIST <<< "${AM_SIZES:-100T 250T 500T}"
read -r -a DEADLINE_PERCENT_LIST <<< "${DEADLINE_PERCENTS:-100 90 80 70}"

TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
N_AM=${#AM_SIZE_LIST[@]}
N_DEADLINES=${#DEADLINE_PERCENT_LIST[@]}
TOTAL=$((N_AM * N_DEADLINES))

if (( TASK_ID >= TOTAL )); then
  echo "Skipping task $TASK_ID; configured grid has only $TOTAL tasks."
  exit 0
fi

AM_INDEX=$((TASK_ID / N_DEADLINES))
DEADLINE_INDEX=$((TASK_ID % N_DEADLINES))

export AM_SIZE="${AM_SIZE_LIST[$AM_INDEX]}"
export DEADLINE_PERCENT="${DEADLINE_PERCENT_LIST[$DEADLINE_INDEX]}"
export CONFIG_TAG="${CONFIG_TAG:-all_deadlines}"

exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
