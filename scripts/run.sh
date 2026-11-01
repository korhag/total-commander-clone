#!/usr/bin/env bash
# ------------------------------------------------------------
# Script: scripts/run.sh
# Purpose: Run the app with the project .venv interpreter.
# Refreshed by scripts/install_linux.sh or scripts/install_macos.sh.
# ------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/main.py" ]]; then
  echo "[ERROR] main.py not found in: $ROOT" >&2
  exit 1
fi

VENV_PY_UNIX="$ROOT/.venv/bin/python"
VENV_PY_WIN="$ROOT/.venv/Scripts/python.exe"

if [[ -x "$VENV_PY_UNIX" ]]; then
  exec "$VENV_PY_UNIX" "$ROOT/main.py"
fi
if [[ -f "$VENV_PY_WIN" ]]; then
  exec "$VENV_PY_WIN" "$ROOT/main.py"
fi

echo "[ERROR] Virtual environment not found or incomplete." >&2
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin*)
    echo "        Run:  bash scripts/install_macos.sh" >&2
    ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "        Run:  scripts\\install_windows.bat" >&2
    ;;
  *)
    echo "        Run:  bash scripts/install_linux.sh" >&2
    ;;
esac
exit 1
