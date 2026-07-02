#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export AM_ID="${AM_ID:-AM100}"
export BASE_DEADLINE="${BASE_DEADLINE:-2600}"
export DEADLINE_RATIO="${DEADLINE_RATIO:-1.00}"
export SEED="${SEED:-1001}"
export VARIANT="no_slack"
export OUTPUT_ROOT="${OUTPUT_ROOT:-logs/smoke_no_slack}"
export SYSTEM_LEVEL_GENERATIONS="${SYSTEM_LEVEL_GENERATIONS:-2}"
export PARTITION_GENERATIONS="${PARTITION_GENERATIONS:-2}"
export AUTO_RESUME="${AUTO_RESUME:-0}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-$SEED}"

exec "$SCRIPT_DIR/run.sh" "$@"
