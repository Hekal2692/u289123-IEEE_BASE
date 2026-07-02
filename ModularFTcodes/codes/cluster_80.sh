#!/bin/bash -l
#SBATCH --job-name=ftcodes_D80
#SBATCH --time=2-00:00:00
#SBATCH --partition=short
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --requeue
#SBATCH --array=0-2
#SBATCH --output=logs/slurm/%x-%A_%a.out
#SBATCH --error=logs/slurm/%x-%A_%a.err

# One deadline range across all AM sizes.
# For one exact AM+deadline pair, use cluster.sh instead.

export DEADLINE_PERCENT=80
export CONFIG_TAG="${CONFIG_TAG:-D80}"

SCRIPT_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
exec "$SCRIPT_DIR/cluster_worker.sh" "$@"
