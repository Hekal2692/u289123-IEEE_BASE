#!/bin/bash -l
#SBATCH --job-name=ftcodes_one
#SBATCH --time=2-00:00:00
#SBATCH --partition=short
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --output=logs/slurm/%x-%j.out
#SBATCH --error=logs/slurm/%x-%j.err

# One exact experiment: one AM size and one deadline range.
# Example:
#   AM_SIZE=100T DEADLINE_PERCENT=80 sbatch cluster.sh

export AM_SIZE="${AM_SIZE:-100T}"
export DEADLINE_PERCENT="${DEADLINE_PERCENT:-100}"
export CONFIG_TAG="${CONFIG_TAG:-single}"

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
