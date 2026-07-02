#!/usr/bin/env bash
set -euo pipefail
set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_DIR/codes"
REQ_FILE="$PROJECT_DIR/requirements.txt"

cd "$CODE_DIR"
mkdir -p logs logs/slurm

export MPLBACKEND=Agg
export PYTHONPATH="$CODE_DIR:${PYTHONPATH:-}"

if command -v module >/dev/null 2>&1; then
  module --ignore-cache purge
  module --ignore-cache load "${PYTHON_MODULE:-python/3.11.2}"
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required")'

VENV="${VENV:-$HOME/venvs/ftcodes311}"
LOCK_FILE="${VENV}.lock"
mkdir -p "$(dirname "$VENV")"

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
python -V
which python

export PLATFORMS_DIR="${PLATFORMS_DIR:-$PROJECT_DIR/Platforms}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs}"
export VARIANT="${VARIANT:-proposed}"
export REQUIRE_ENV_CONFIG=1
export AUTO_RESUME="${AUTO_RESUME:-1}"

if [[ -z "${AM_ID:-}" && -n "${AM_SIZE:-}" ]]; then
  case "$AM_SIZE" in
    100T|100|AM100) export AM_ID=AM100 ;;
    250T|250|AM250) export AM_ID=AM250 ;;
    500T|500|AM500) export AM_ID=AM500 ;;
    *) echo "ERROR: Unsupported AM_SIZE='$AM_SIZE'" >&2; exit 2 ;;
  esac
fi

if [[ -z "${BASE_DEADLINE:-}" && -n "${AM_ID:-}" ]]; then
  case "$AM_ID" in
    AM100|100|100T) export BASE_DEADLINE=2600 ;;
    AM250|250|250T) export BASE_DEADLINE=2700 ;;
    AM500|500|500T) export BASE_DEADLINE=4300 ;;
    *) echo "ERROR: Unsupported AM_ID='$AM_ID'" >&2; exit 2 ;;
  esac
fi

if [[ -z "${DEADLINE_RATIO:-}" && -n "${DEADLINE_PERCENT:-}" ]]; then
  export DEADLINE_RATIO="$(python - <<'EOF'
import os
print(f"{int(os.environ['DEADLINE_PERCENT']) / 100.0:.2f}")
EOF
)"
fi

if [[ -z "${AM_ID:-}" || -z "${BASE_DEADLINE:-}" || -z "${DEADLINE_RATIO:-}" || -z "${SEED:-}" ]]; then
  echo "ERROR: AM_ID, BASE_DEADLINE, DEADLINE_RATIO, and SEED must be exported before running cluster_worker.sh" >&2
  exit 2
fi

export PYTHONHASHSEED="${PYTHONHASHSEED:-$SEED}"

ratio_dir="$(python - <<'EOF'
import os
print(f"ratio{float(os.environ['DEADLINE_RATIO']):.2f}")
EOF
)"
seed_dir="seed${SEED}"
resume_root="$OUTPUT_ROOT/$AM_ID/$ratio_dir/$seed_dir"

if [[ "${RESUME_LATEST:-0}" == "1" && -z "${RESUME_FROM:-}" ]]; then
  latest_checkpoint=""
  for candidate in "$resume_root"/*/checkpoint_latest.pkl; do
    [[ -f "$candidate" ]] || continue
    if [[ -z "$latest_checkpoint" || "$candidate" -nt "$latest_checkpoint" ]]; then
      latest_checkpoint="$candidate"
    fi
  done
  if [[ -n "$latest_checkpoint" ]]; then
    export RESUME_FROM="$latest_checkpoint"
  fi
fi

if [[ -z "${RUN_TIMESTAMP:-}" ]]; then
  if [[ -n "${SLURM_ARRAY_JOB_ID:-}" ]]; then
    export RUN_TIMESTAMP="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
  elif [[ -n "${SLURM_JOB_ID:-}" ]]; then
    export RUN_TIMESTAMP="${SLURM_JOB_ID}"
  else
    export RUN_TIMESTAMP="$(date +"%Y-%m-%d_%H-%M-%S")"
  fi
fi

echo "[cluster_worker] AM_ID=$AM_ID BASE_DEADLINE=$BASE_DEADLINE DEADLINE_RATIO=$DEADLINE_RATIO SEED=$SEED VARIANT=$VARIANT OUTPUT_ROOT=$OUTPUT_ROOT RUN_TIMESTAMP=$RUN_TIMESTAMP"

python main.py "$@"
