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

export AM_ID="${AM_ID:-AM100}"
export BASE_DEADLINE="${BASE_DEADLINE:-2600}"
if [[ -z "${DEADLINE_RATIO:-}" && -n "${DEADLINE_PERCENT:-}" ]]; then
  export DEADLINE_RATIO="$(python - <<'EOF'
import os
print(f"{int(os.environ['DEADLINE_PERCENT']) / 100.0:.2f}")
EOF
)"
fi
export DEADLINE_RATIO="${DEADLINE_RATIO:-1.00}"
export SEED="${SEED:-1001}"
export VARIANT="${VARIANT:-proposed}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-$SEED}"
export PLATFORMS_DIR="${PLATFORMS_DIR:-$PROJECT_DIR/Platforms}"
export REQUIRE_ENV_CONFIG=1
export AUTO_RESUME="${AUTO_RESUME:-0}"

if [[ -z "${RUN_TIMESTAMP:-}" ]]; then
  export RUN_TIMESTAMP="$(date +"%Y-%m-%d_%H-%M-%S")"
fi

python main.py "$@"
