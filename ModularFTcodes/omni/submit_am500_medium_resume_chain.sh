#!/usr/bin/env bash
set -euo pipefail

ATTEMPTS="${1:-${AM500_MEDIUM_ATTEMPTS:-4}}"
if ! [[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || [[ "$ATTEMPTS" -lt 1 ]]; then
  echo "Usage: $0 [attempt_count]" >&2
  echo "attempt_count must be a positive integer; default is 4." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null || (cd "$PROJECT_DIR/.." && pwd))"
SBATCH_SCRIPT="ModularFTcodes/omni/run_proposed_am500_medium.sbatch"
OUTPUT_ROOT="${OUTPUT_ROOT:-$REPO_ROOT/logs_proposed_am500_medium}"
MAX_CONCURRENT="${MAX_CONCURRENT:-40}"
DEPENDENCY=""
JOB_IDS=()

mkdir -p "$OUTPUT_ROOT" "$REPO_ROOT/logs/slurm"
cd "$REPO_ROOT"

for attempt in $(seq 1 "$ATTEMPTS"); do
  if [[ -n "$DEPENDENCY" ]]; then
    job_id="$(sbatch --parsable --dependency="afterany:$DEPENDENCY" --array="0-39%${MAX_CONCURRENT}" --job-name="hga-500-a${attempt}" "$SBATCH_SCRIPT")"
  else
    job_id="$(sbatch --parsable --array="0-39%${MAX_CONCURRENT}" --job-name="hga-500-a${attempt}" "$SBATCH_SCRIPT")"
  fi
  job_id="${job_id%%;*}"
  JOB_IDS+=("$job_id")
  DEPENDENCY="$job_id"
  echo "submitted AM500 medium attempt $attempt/$ATTEMPTS: $job_id"
done

JOB_IDS_CSV="$(IFS=,; echo "${JOB_IDS[*]}")"
python3 "$SCRIPT_DIR/omni_array.py" write-submission \
  --output-root "$OUTPUT_ROOT" \
  --array-job-id "${JOB_IDS[0]}" \
  --manifest "$SCRIPT_DIR/proposed_am500_medium_manifest.tsv" \
  --max-concurrent "$MAX_CONCURRENT" \
  --git-commit-sha "$(git -C "$REPO_ROOT" rev-parse --verify HEAD 2>/dev/null || true)" \
  --array-expression "0-39%${MAX_CONCURRENT}"

python3 - "$OUTPUT_ROOT" "$ATTEMPTS" "$MAX_CONCURRENT" "$SBATCH_SCRIPT" "$JOB_IDS_CSV" <<'PYMETA'
import json
import sys
from datetime import datetime
from pathlib import Path
output_root, attempts, max_concurrent, sbatch_script, job_ids_csv = sys.argv[1:]
job_ids = [item for item in job_ids_csv.split(",") if item]
payload = {
    "submitted_at": datetime.now().isoformat(timespec="seconds"),
    "attempt_count": int(attempts),
    "job_ids": job_ids,
    "dependency": "afterany chain",
    "max_concurrent": int(max_concurrent),
    "sbatch_script": sbatch_script,
    "output_root": output_root,
}
path = Path(output_root) / "am500_medium_resume_chain.json"
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"saved chain metadata: {path}")
PYMETA

echo "AM500 medium resume chain submitted. Later attempts will start after the previous array exits."
