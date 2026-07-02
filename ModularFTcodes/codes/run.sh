#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CODE_DIR="$PROJECT_DIR/codes"
REQ_FILE="$PROJECT_DIR/requirements.txt"

cd "$CODE_DIR"
mkdir -p logs

export MPLBACKEND=Agg
export PYTHONPATH="$CODE_DIR:${PYTHONPATH:-}"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_BIN was not found. Load Python 3.11 or set PYTHON_BIN=/path/to/python3.11" >&2
  exit 2
fi
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required")'

VENV="${VENV:-$PROJECT_DIR/.venv}"
if [[ ! -d "$VENV" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi
source "$VENV/bin/activate"
python -m pip install -U pip
python -m pip install -r "$REQ_FILE"

AM_SIZE="${AM_SIZE:-100T}"
DEADLINE_PERCENT="${DEADLINE_PERCENT:-100}"
CONFIG_TAG="${CONFIG_TAG:-local}"
timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
DEADLINE_LABEL="D${DEADLINE_PERCENT}"
if [[ -n "${DEADLINE:-}" ]]; then
  DEADLINE_LABEL="Dcustom"
fi

main_args=(
  --am-size "$AM_SIZE"
  --deadline-percent "$DEADLINE_PERCENT"
  --platforms-dir "$PROJECT_DIR/Platforms"
  --log-dir "logs/$CONFIG_TAG/$AM_SIZE/$DEADLINE_LABEL"
  --timestamp "$timestamp"
  --auto-resume
)

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
