#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OMNI_STATE_DIR="${OMNI_STATE_DIR:-$HOME/.ftcodes_omni}"
READY_MARKER="${READY_MARKER:-$OMNI_STATE_DIR/environment_ready.json}"
PREFLIGHT_MARKER="${PREFLIGHT_MARKER:-$OMNI_STATE_DIR/preflight_success.json}"
MANIFEST_PATH="${MANIFEST_PATH:-$SCRIPT_DIR/proposed_experiment_manifest.tsv}"
VENV="${VENV:-$HOME/venvs/ftcodes311}"

if [[ -f "$READY_MARKER" ]]; then
  MARKER_VENV="$(python3 "$SCRIPT_DIR/omni_array.py" marker-value --marker "$READY_MARKER" --key venv 2>/dev/null || true)"
  if [[ -n "$MARKER_VENV" ]]; then
    VENV="$MARKER_VENV"
  fi
fi

if [[ ! -d "$VENV" ]]; then
  echo "ERROR: expected virtual environment was not found: $VENV" >&2
  echo "Run: bash ModularFTcodes/omni/prepare_omni_environment.sh" >&2
  exit 2
fi

source "$VENV/bin/activate"
python "$SCRIPT_DIR/omni_array.py" check-environment --marker "$READY_MARKER" --project-dir "$PROJECT_DIR"
python "$SCRIPT_DIR/omni_array.py" validate-manifest --manifest "$MANIFEST_PATH" --project-dir "$PROJECT_DIR"
python -m py_compile \
  "$PROJECT_DIR/codes/main.py" \
  "$PROJECT_DIR/codes/SystemLevelScheduler.py" \
  "$PROJECT_DIR/omni/omni_array.py"
python -c 'import numpy, networkx, matplotlib, deap; print("OK: required Python imports available")'
python "$SCRIPT_DIR/omni_array.py" write-preflight-marker \
  --marker "$PREFLIGHT_MARKER" \
  --project-dir "$PROJECT_DIR" \
  --manifest "$MANIFEST_PATH"

printf 'Omni preflight passed. Marker: %s\n' "$PREFLIGHT_MARKER"
