#!/usr/bin/env bash
set -euo pipefail
set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_DIR/codes"
REQ_FILE="$PROJECT_DIR/requirements.txt"

cd "$CODE_DIR"
mkdir -p logs

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

read -r -a AM_SIZE_LIST <<< "${AM_SIZES:-100T 250T 500T}"
TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"
if [[ -n "${AM_SIZE:-}" ]]; then
  SELECTED_AM_SIZE="$AM_SIZE"
else
  if (( TASK_ID >= ${#AM_SIZE_LIST[@]} )); then
    echo "Skipping task $TASK_ID; only ${#AM_SIZE_LIST[@]} AM sizes configured."
    exit 0
  fi
  SELECTED_AM_SIZE="${AM_SIZE_LIST[$TASK_ID]}"
fi

DEADLINE_PERCENT="${DEADLINE_PERCENT:-100}"
case "$DEADLINE_PERCENT" in
  100|90|80|70) ;;
  *) echo "ERROR: DEADLINE_PERCENT must be one of 100, 90, 80, 70; got '$DEADLINE_PERCENT'" >&2; exit 2 ;;
esac

CONFIG_TAG="${CONFIG_TAG:-D${DEADLINE_PERCENT}}"
if [[ -n "${RUN_ID:-}" ]]; then
  timestamp="$RUN_ID"
elif [[ -n "${SLURM_ARRAY_JOB_ID:-}" ]]; then
  timestamp="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
elif [[ -n "${SLURM_JOB_ID:-}" ]]; then
  timestamp="$SLURM_JOB_ID"
else
  timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
fi
DEADLINE_LABEL="D${DEADLINE_PERCENT}"
if [[ -n "${DEADLINE:-}" ]]; then
  DEADLINE_LABEL="Dcustom"
fi

RUN_BASE_DIR="logs/$CONFIG_TAG/$SELECTED_AM_SIZE/$DEADLINE_LABEL"

main_args=(
  --am-size "$SELECTED_AM_SIZE"
  --deadline-percent "$DEADLINE_PERCENT"
  --platforms-dir "$PROJECT_DIR/Platforms"
  --log-dir "$RUN_BASE_DIR"
  --timestamp "$timestamp"
  --auto-resume
)

if [[ "${RESUME_LATEST:-0}" == "1" && -z "${RESUME_FROM:-}" ]]; then
  latest_checkpoint=""
  for candidate in "$RUN_BASE_DIR"/*/checkpoint_latest.pkl; do
    [[ -f "$candidate" ]] || continue
    if [[ -z "$latest_checkpoint" || "$candidate" -nt "$latest_checkpoint" ]]; then
      latest_checkpoint="$candidate"
    fi
  done
  if [[ -n "$latest_checkpoint" ]]; then
    main_args+=(--resume-from "$latest_checkpoint")
  fi
fi

if [[ -n "${DEADLINE_BASE:-}" ]]; then
  main_args+=(--deadline-base "$DEADLINE_BASE")
fi
if [[ -n "${DEADLINE:-}" ]]; then
  main_args+=(--deadline "$DEADLINE")
fi
if [[ -n "${RESUME_FROM:-}" ]]; then
  main_args+=(--resume-from "$RESUME_FROM")
fi

python main.py "${main_args[@]}" "$@"
