#!/usr/bin/env bash
# ------------------------------------------------------------
# Script: scripts/install.sh
# Purpose: Detect OS and CPU architecture, install Python 3 and pip
#          when missing, create a project virtualenv, install
#          requirements, and write scripts/run.sh (and on macOS
#          scripts/RUN.command). On Windows cmd use scripts/install.bat.
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
# OS / hardware detection
# ------------------------------------------------------------
detect_os() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux*) OS="linux" ;;
    Darwin*) OS="darwin" ;;
    MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
    *) OS="unknown" ;;
  esac
}

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
  if command -v py >/dev/null 2>&1; then
    if py -3 -c "import sys; v=sys.version_info; raise SystemExit(0 if (v.major,v.minor)>=(int('$MIN_PY_MAJOR'),int('$MIN_PY_MINOR')) else 1)" 2>/dev/null; then
      echo "py -3"
      return 0
    fi
  fi
  # macOS: PATH may omit Homebrew / MacPorts / python.org Framework installs
  if [[ "${OS:-}" == "darwin" ]]; then
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
  fi
  return 1
}

# ------------------------------------------------------------
# macOS: install Python when missing (Homebrew, then MacPorts)
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
# Install system Python + pip (best-effort per OS)
# ------------------------------------------------------------
install_system_python() {
  info "Python $MIN_PY_MAJOR.$MIN_PY_MINOR+ not found; attempting OS-appropriate install..."
  case "$OS" in
    linux)
      if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        case "${ID:-}" in
          ubuntu|debian|pop|linuxmint|raspbian)
            info "Using apt (Debian/Ubuntu family)..."
            run_sudo apt-get update -qq
            run_sudo apt-get install -y python3 python3-pip python3-venv
            return 0
            ;;
          fedora|rhel|centos|rocky|almalinux)
            info "Using dnf..."
            run_sudo dnf install -y python3 python3-pip
            return 0
            ;;
          arch|manjaro|endeavouros)
            info "Using pacman (Arch)..."
            run_sudo pacman -S --needed --noconfirm python python-pip
            return 0
            ;;
          opensuse*|suse)
            info "Using zypper..."
            run_sudo zypper install -y python3 python3-pip
            return 0
            ;;
        esac
        # Match ID_LIKE for derivatives
        case "${ID_LIKE:-}" in
          *debian*|*ubuntu*)
            info "Using apt (ID_LIKE)..."
            run_sudo apt-get update -qq
            run_sudo apt-get install -y python3 python3-pip python3-venv
            return 0
            ;;
          *rhel*|*fedora*)
            info "Using dnf (ID_LIKE)..."
            run_sudo dnf install -y python3 python3-pip
            return 0
            ;;
        esac
      fi
      err "Unsupported or unknown Linux distribution. Install Python $MIN_PY_MAJOR.$MIN_PY_MINOR+ and pip, then re-run this script."
      return 1
      ;;
    darwin)
      install_macos_python
      ;;
    windows)
      if command -v winget >/dev/null 2>&1; then
        info "Using winget..."
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements || true
        # Refresh PATH in this session (common install locations)
        export PATH="/c/Users/${USERNAME:-$USER}/AppData/Local/Programs/Python/Python312:$PATH"
        export PATH="/c/Users/${USERNAME:-$USER}/AppData/Local/Programs/Python/Python311:$PATH"
        hash -r 2>/dev/null || true
        return 0
      fi
      if command -v choco >/dev/null 2>&1; then
        info "Using Chocolatey..."
        run_sudo choco install -y python3
        return 0
      fi
      err "Install Python 3 from https://www.python.org/downloads/ and ensure it is on PATH, then re-run."
      return 1
      ;;
    *)
      err "Unknown OS. Install Python $MIN_PY_MAJOR.$MIN_PY_MINOR+ and pip manually, then re-run."
      return 1
      ;;
  esac
}

# Bootstrap pip inside the venv (system Python may ship without pip).
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
  err "  Linux: sudo apt install python3-pip python3-venv (or your distro equivalent)."
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
  if install_system_python; then
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
  elif [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
    venv_python="$VENV_DIR/Scripts/python.exe"
  else
    err "venv is missing an interpreter under .venv/bin or .venv/Scripts."
    exit 1
  fi
  ensure_venv_pip "$venv_python"
  local pip_inv
  if [[ -x "$VENV_DIR/bin/pip" ]]; then
    pip_inv=("$VENV_DIR/bin/pip")
  elif [[ -x "$VENV_DIR/Scripts/pip.exe" ]]; then
    pip_inv=("$VENV_DIR/Scripts/pip.exe")
  else
    err "venv exists but pip not found inside it."
    exit 1
  fi
  "${pip_inv[@]}" install --upgrade pip
  if [[ -f "$ROOT/$REQUIREMENTS" ]]; then
    info "Installing packages from $REQUIREMENTS ..."
    "${pip_inv[@]}" install -r "$ROOT/$REQUIREMENTS"
  else
    warn "No $REQUIREMENTS; skipping package install."
  fi
}

# ------------------------------------------------------------
# Write scripts/run.sh (Unix + Git Bash on Windows)
# Uses the venv interpreter directly so macOS never picks Python 2.
# ------------------------------------------------------------
write_run_sh() {
  cat > "$SCRIPT_DIR/run.sh" << 'RUNSH'
#!/usr/bin/env bash
# ------------------------------------------------------------
# Script: scripts/run.sh
# Purpose: Run the app with the project .venv interpreter.
# Generated by scripts/install.sh — safe to re-run install.sh to refresh.
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
echo "        Run:  bash scripts/install.sh" >&2
echo "        (Windows cmd:  scripts\\install.bat)" >&2
exit 1
RUNSH
  chmod +x "$SCRIPT_DIR/run.sh"
  info "Wrote $SCRIPT_DIR/run.sh"
}

# ------------------------------------------------------------
# macOS: double-click launcher (Terminal.app runs .command files)
# ------------------------------------------------------------
write_run_command_macos() {
  cat > "$SCRIPT_DIR/RUN.command" << 'RUNCMD'
#!/bin/bash
# ------------------------------------------------------------
# Double-click launcher for macOS (Terminal opens this file).
# Requires: bash scripts/install.sh  (creates .venv)
# ------------------------------------------------------------
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/run.sh"
RUNCMD
  chmod +x "$SCRIPT_DIR/RUN.command"
  info "Wrote $SCRIPT_DIR/RUN.command (double-click in Finder after install)"
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
  case "$OS" in
    linux)
      if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        case "${ID:-}${ID_LIKE:-}" in
          *arch*|*manjaro*|*endeavouros*)
            run_sudo pacman -S --needed --noconfirm 7zip && return 0
            ;;
          *debian*|*ubuntu*|*mint*|*pop*)
            if run_sudo apt-get update -qq && run_sudo apt-get install -y 7zip; then
              return 0
            fi
            run_sudo apt-get install -y p7zip-full && return 0
            ;;
          *fedora*|*rhel*|*centos*|*rocky*|*alma*)
            if run_sudo dnf install -y 7zip; then
              return 0
            fi
            run_sudo dnf install -y p7zip p7zip-plugins && return 0
            ;;
          *suse*)
            run_sudo zypper install -y 7zip && return 0
            ;;
        esac
      fi
      ;;
    darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install sevenzip && return 0
      fi
      ;;
    windows)
      if command -v winget >/dev/null 2>&1; then
        winget install -e --id 7zip.7zip --accept-package-agreements --accept-source-agreements && return 0
      fi
      ;;
  esac
  warn "Could not install 7-Zip. Archive browsing needs it."
  warn "  Linux: install the 7zip package (Debian may call it p7zip-full)."
  warn "  macOS: brew install sevenzip"
  warn "  Windows: winget install 7zip.7zip"
  return 0
}

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
main() {
  detect_os
  detect_arch
  info "Detected OS: $OS"
  info "Detected hardware: $ARCH — $ARCH_LABEL"

  resolve_python
  info "Using Python: ${PY_CMD[*]}"
  "${PY_CMD[@]}" --version

  create_venv_and_install "${PY_CMD[@]}"
  install_sevenzip || warn "Continuing without 7-Zip."
  write_run_sh
  if [[ "$OS" == "darwin" ]]; then
    write_run_command_macos
  fi

  info "Done."
  info "  Start from a terminal:  bash scripts/run.sh"
  if [[ "$OS" == "darwin" ]]; then
    info "  macOS Finder:           double-click scripts/RUN.command (if needed: chmod +x scripts/RUN.command)"
  fi
  if [[ "$OS" == "windows" ]]; then
    info "  Windows (cmd):          scripts\\\\install.bat  then  scripts\\\\run.bat"
  fi
}

main "$@"
