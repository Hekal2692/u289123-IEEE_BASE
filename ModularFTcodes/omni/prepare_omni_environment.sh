#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
READY_MARKER="${READY_MARKER:-$OMNI_STATE_DIR/environment_ready.json}"
PYTHON_MODULE="${PYTHON_MODULE:-python/3.11.2}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
VENV="${VENV:-$HOME/venvs/ftcodes311}"
REQ_FILE="$PROJECT_DIR/requirements.txt"

if command -v module >/dev/null 2>&1; then
  module --ignore-cache purge
  module --ignore-cache load "$PYTHON_MODULE"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required")'
mkdir -p "$(dirname "$VENV")" "$OMNI_STATE_DIR"
LOCK_FILE="$OMNI_STATE_DIR/environment.lock"

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
  python "$SCRIPT_DIR/omni_array.py" write-environment-marker \
    --marker "$READY_MARKER" \
    --project-dir "$PROJECT_DIR" \
    --venv "$VENV" \
    --python-bin "$VENV/bin/python"
) 9>"$LOCK_FILE"

printf 'Omni environment is ready. Marker: %s\n' "$READY_MARKER"
