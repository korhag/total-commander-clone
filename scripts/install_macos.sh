#!/usr/bin/env bash
# ------------------------------------------------------------
# Script: scripts/install_macos.sh
# Purpose: On macOS, install Python 3 when it is missing, create
#          the project virtualenv, install requirements, install
#          7-Zip with Homebrew when possible, and write
#          scripts/run.sh and scripts/RUN.command.
# ------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

REQUIREMENTS="requirements.txt"
VENV_DIR="$ROOT/.venv"
MIN_PY_MAJOR=3
MIN_PY_MINOR=8

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*" >&2; }
err() { echo "[ERROR] $*" >&2; }

# ------------------------------------------------------------
# Hardware label (informational)
# ------------------------------------------------------------
detect_arch() {
  ARCH="$(uname -m 2>/dev/null || echo unknown)"
  case "$ARCH" in
    x86_64|amd64) ARCH_LABEL="64-bit Intel/AMD (x86_64)" ;;
    aarch64|arm64) ARCH_LABEL="64-bit ARM (aarch64/arm64)" ;;
    armv7l) ARCH_LABEL="32-bit ARM" ;;
    i386|i686) ARCH_LABEL="32-bit x86" ;;
    *) ARCH_LABEL="cpu=$ARCH" ;;
  esac
}

# ------------------------------------------------------------
# Privileged command helper (sudo when not root)
# ------------------------------------------------------------
SUDO=()
if [[ "$(id -u)" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO=(sudo)
  fi
fi

run_sudo() {
  if [[ ${#SUDO[@]} -gt 0 ]]; then
    "${SUDO[@]}" "$@"
  else
    "$@"
  fi
}

# ------------------------------------------------------------
# Python version check (requires python at $1)
# ------------------------------------------------------------
python_ok() {
  local py="$1"
  "$py" -c "import sys; v=sys.version_info; raise SystemExit(0 if (v.major,v.minor)>=(int('$MIN_PY_MAJOR'),int('$MIN_PY_MINOR')) else 1)" 2>/dev/null
}

find_python_cmd() {
  if command -v python3 >/dev/null 2>&1 && python_ok python3; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1 && python_ok python; then
    echo "python"
    return 0
  fi
  # PATH may omit Homebrew / MacPorts / python.org Framework installs
  local p _majmin
  for p in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /opt/local/bin/python3 \
    /opt/local/bin/python3.12 \
    /opt/local/bin/python3.11
  do
    if [[ -x "$p" ]] && python_ok "$p"; then
      echo "$p"
      return 0
    fi
  done
  for _majmin in 3.14 3.13 3.12 3.11 3.10 3.9 3.8; do
    p="/Library/Frameworks/Python.framework/Versions/${_majmin}/bin/python3"
    if [[ -x "$p" ]] && python_ok "$p"; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

# ------------------------------------------------------------
# Install Python when missing (Homebrew, then MacPorts)
# ------------------------------------------------------------
install_macos_python() {
  info "macOS: installing Python (Homebrew preferred, else MacPorts)..."

  if [[ -x /opt/homebrew/bin/brew ]]; then
    info "Using Homebrew (Apple Silicon default: /opt/homebrew)..."
    eval "$(/opt/homebrew/bin/brew shellenv)"
    brew install python
    hash -r 2>/dev/null || true
    return 0
  fi
  if [[ -x /usr/local/bin/brew ]]; then
    info "Using Homebrew (Intel default: /usr/local)..."
    eval "$(/usr/local/bin/brew shellenv)"
    brew install python
    hash -r 2>/dev/null || true
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    info "Using Homebrew (from PATH)..."
    eval "$(brew shellenv)"
    brew install python
    hash -r 2>/dev/null || true
    return 0
  fi

  if command -v port >/dev/null 2>&1; then
    info "Using MacPorts..."
    run_sudo port install python312
    export PATH="/opt/local/bin:/opt/local/sbin:$PATH"
    run_sudo port select --set python3 python312 2>/dev/null || true
    hash -r 2>/dev/null || true
    return 0
  fi

  err "Could not auto-install Python on macOS (Homebrew and MacPorts not found)."
  err "Install one of the following, then re-run this script:"
  err "  • Homebrew:  https://brew.sh  →  brew install python"
  err "  • MacPorts:  https://www.macports.org/install.php  →  sudo port install python312 && sudo port select --set python3 python312"
  err "  • Official installer:  https://www.python.org/downloads/macos/"
  return 1
}

# ------------------------------------------------------------
# Bootstrap pip inside the venv (system Python may ship without pip)
# ------------------------------------------------------------
ensure_venv_pip() {
  local venv_python="$1"
  if "$venv_python" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  info "pip missing in venv; running ensurepip..."
  if "$venv_python" -m ensurepip --upgrade 2>/dev/null; then
    return 0
  fi
  err "Could not install pip into the venv."
  err "  macOS: ensure a full Python 3 install (brew install python), not only the Xcode stub."
  return 1
}

resolve_python() {
  local found
  found="$(find_python_cmd)" || true
  if [[ -n "${found:-}" ]]; then
    # shellcheck disable=SC2206
    PY_CMD=($found)
    return 0
  fi
  if install_macos_python; then
    hash -r 2>/dev/null || true
    found="$(find_python_cmd)" || true
    if [[ -n "${found:-}" ]]; then
      PY_CMD=($found)
      return 0
    fi
  fi
  err "Could not find a usable Python $MIN_PY_MAJOR.$MIN_PY_MINOR+ after install attempt."
  exit 1
}

# ------------------------------------------------------------
# Create venv and install dependencies
# ------------------------------------------------------------
create_venv_and_install() {
  local py_cmd=("$@")
  if [[ -f "$VENV_DIR/pyvenv.cfg" ]]; then
    info "Virtual environment already exists at .venv — refreshing packages."
  else
    info "Creating virtual environment at .venv ..."
    "${py_cmd[@]}" -m venv "$VENV_DIR"
  fi
  local venv_python=""
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    venv_python="$VENV_DIR/bin/python"
  else
    err "venv is missing an interpreter under .venv/bin."
    exit 1
  fi
  ensure_venv_pip "$venv_python"
  if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
    err "venv exists but pip not found inside it."
    exit 1
  fi
  "$VENV_DIR/bin/pip" install --upgrade pip
  if [[ -f "$ROOT/$REQUIREMENTS" ]]; then
    info "Installing packages from $REQUIREMENTS ..."
    "$VENV_DIR/bin/pip" install -r "$ROOT/$REQUIREMENTS"
  else
    warn "No $REQUIREMENTS; skipping package install."
  fi
}

# ------------------------------------------------------------
# Write scripts/run.sh
# Uses the venv interpreter directly so macOS never picks Python 2.
# ------------------------------------------------------------
write_run_sh() {
  cat > "$SCRIPT_DIR/run.sh" << 'RUNSH'
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
RUNSH
  chmod +x "$SCRIPT_DIR/run.sh"
  info "Wrote $SCRIPT_DIR/run.sh"
}

# ------------------------------------------------------------
# Double-click launcher (Terminal.app runs .command files)
# ------------------------------------------------------------
write_run_command_macos() {
  cat > "$SCRIPT_DIR/RUN.command" << 'RUNCMD'
#!/bin/bash
# ------------------------------------------------------------
# Double-click launcher for macOS (Terminal opens this file).
# Requires: bash scripts/install_macos.sh  (creates .venv)
# ------------------------------------------------------------
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/run.sh"
RUNCMD
  chmod +x "$SCRIPT_DIR/RUN.command"
  info "Wrote $SCRIPT_DIR/RUN.command (double-click in Finder after install)"
}

# ------------------------------------------------------------
# App the Dock pin keeps. The launcher runs the venv, so the
# next install picks up the version just installed.
# ------------------------------------------------------------
write_macos_app() {
  local app="$HOME/Applications/Total Commander Clone.app"
  local macos="$app/Contents/MacOS"
  local py="$ROOT/.venv/bin/python"
  local version=""
  mkdir -p "$macos"
  if [[ -f "$ROOT/app_version.py" ]]; then
    version="$(grep -E '^APP_VERSION[[:space:]]*=' "$ROOT/app_version.py" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
  fi
  cat > "$macos/launcher" << EOF
#!/bin/bash
exec "$py" "$ROOT/main.py"
EOF
  chmod +x "$macos/launcher"
  cat > "$app/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Total Commander Clone</string>
  <key>CFBundleDisplayName</key>
  <string>Total Commander Clone</string>
  <key>CFBundleIdentifier</key>
  <string>com.tcclone.fileexplorer</string>
  <key>CFBundleExecutable</key>
  <string>launcher</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleVersion</key>
  <string>${version}</string>
  <key>CFBundleShortVersionString</key>
  <string>${version}</string>
</dict>
</plist>
EOF
  info "Wrote $app"
}

# ------------------------------------------------------------
# 7-Zip command-line tool (archive browse / extract / compress).
# Failure here is a warning: the app still runs, and archive
# actions explain how to install 7-Zip.
# ------------------------------------------------------------
install_sevenzip() {
  if command -v 7zz >/dev/null 2>&1 || command -v 7z >/dev/null 2>&1 || command -v 7za >/dev/null 2>&1; then
    info "7-Zip is already installed."
    return 0
  fi
  info "7-Zip not found; attempting to install it..."
  if command -v brew >/dev/null 2>&1; then
    brew install sevenzip && return 0
  fi
  warn "Could not install 7-Zip. Archive browsing needs it."
  warn "  Install it with:  brew install sevenzip"
  return 0
}

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
main() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin*) ;;
    Linux*)
      err "This installer is for macOS."
      err "  On Linux run:  bash scripts/install_linux.sh"
      exit 1
      ;;
    *)
      err "This installer is for macOS."
      err "  Linux:    bash scripts/install_linux.sh"
      err "  Windows:  scripts\\install_windows.bat"
      exit 1
      ;;
  esac

  detect_arch
  info "Detected OS: darwin"
  info "Detected hardware: $ARCH — $ARCH_LABEL"

  resolve_python
  info "Using Python: ${PY_CMD[*]}"
  "${PY_CMD[@]}" --version

  create_venv_and_install "${PY_CMD[@]}"
  install_sevenzip || warn "Continuing without 7-Zip."
  write_run_sh
  write_run_command_macos
  write_macos_app

  info "Done."
  info "  Start from a terminal:  bash scripts/run.sh"
  info "  Dock / Applications:    Total Commander Clone"
  info "  macOS Finder:           double-click scripts/RUN.command (if needed: chmod +x scripts/RUN.command)"
}

main "$@"
