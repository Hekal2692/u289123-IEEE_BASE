#!/bin/bash -l
#SBATCH --job-name=ftcodes_one
#SBATCH --time=3-00:00:00
#SBATCH --partition=long
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --output=logs/slurm/%x-%j.out
#SBATCH --error=logs/slurm/%x-%j.err

# One exact experiment with one AM, one deadline ratio, and one seed.
# Example:
#   AM_ID=AM250 BASE_DEADLINE=2700 DEADLINE_RATIO=0.90 SEED=1003 sbatch cluster.sh

export AM_ID="${AM_ID:-AM100}"
export BASE_DEADLINE="${BASE_DEADLINE:-2600}"
export DEADLINE_RATIO="${DEADLINE_RATIO:-1.00}"
export SEED="${SEED:-1001}"
export VARIANT="${VARIANT:-proposed}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs}"
export CONFIG_TAG="${CONFIG_TAG:-single}"

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
