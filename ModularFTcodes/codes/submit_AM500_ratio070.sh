#!/bin/bash -l
#SBATCH --job-name=AM500_r070
#SBATCH --time=5-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-9
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

set -euo pipefail

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SEEDS=(1001 1002 1003 1004 1005 1006 1007 1008 1009 1010)
SEED="${SEEDS[$SLURM_ARRAY_TASK_ID]}"

export AM_ID=AM500
export BASE_DEADLINE=4300
export DEADLINE_RATIO=0.70
export SEED="$SEED"
export VARIANT="${VARIANT:-proposed}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs}"
export CONFIG_TAG="${CONFIG_TAG:-AM500_ratio070}"

exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
