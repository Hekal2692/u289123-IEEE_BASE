#!/bin/bash -l
#SBATCH --job-name=ftcodes_D100
#SBATCH --time=5-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-29
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

# One deadline ratio across all AMs and all 10 seeds.

set -euo pipefail

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
read -r -a AM_ID_LIST <<< "${AM_IDS:-AM100 AM250 AM500}"
read -r -a BASE_DEADLINE_LIST <<< "${BASE_DEADLINES:-2600 2700 4300}"
read -r -a SEED_LIST <<< "${SEEDS:-1001 1002 1003 1004 1005 1006 1007 1008 1009 1010}"
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
N_AM=${#AM_ID_LIST[@]}
N_SEEDS=${#SEED_LIST[@]}
TOTAL=$((N_AM * N_SEEDS))

if (( ${#AM_ID_LIST[@]} != ${#BASE_DEADLINE_LIST[@]} )); then
  echo "ERROR: AM_IDS and BASE_DEADLINES must have the same length." >&2
  exit 2
fi

if (( TASK_ID >= TOTAL )); then
  echo "Skipping task $TASK_ID; configured grid has only $TOTAL tasks."
  exit 0
fi

AM_INDEX=$((TASK_ID / N_SEEDS))
SEED_INDEX=$((TASK_ID % N_SEEDS))

export AM_ID="${AM_ID_LIST[$AM_INDEX]}"
export BASE_DEADLINE="${BASE_DEADLINE_LIST[$AM_INDEX]}"
export DEADLINE_RATIO="1.00"
export SEED="${SEED_LIST[$SEED_INDEX]}"
export VARIANT="${VARIANT:-proposed}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs}"
export CONFIG_TAG="${CONFIG_TAG:-D100}"

exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
