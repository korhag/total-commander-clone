#!/bin/bash
# ------------------------------------------------------------
# Double-click launcher for macOS (Terminal opens this file).
# Requires: bash scripts/install_macos.sh  (creates .venv)
# ------------------------------------------------------------
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/run.sh"
