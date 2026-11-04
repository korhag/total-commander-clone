#!/usr/bin/env bash
# ------------------------------------------------------------
# Script: scripts/install_linux.sh
# Purpose: On Linux, install Python 3 when it is missing, create
#          the project virtualenv, install requirements, install
#          7-Zip when possible, and write scripts/run.sh.
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
  return 1
}

# ------------------------------------------------------------
# Install system Python + pip (best-effort per distribution)
# ------------------------------------------------------------
install_system_python() {
  info "Python $MIN_PY_MAJOR.$MIN_PY_MINOR+ not found; attempting to install it..."
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
  err "  Linux: sudo apt install python3-pip python3-venv (or your distro equivalent)."
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
# Uses the venv interpreter directly so PATH cannot pick another Python.
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
# Launcher the desktop and taskbar pin. It runs the venv, so the
# next install picks up the version just installed.
# ------------------------------------------------------------
write_desktop_entry() {
  local apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  local desktop="$apps_dir/total-commander-clone.desktop"
  local py="$ROOT/.venv/bin/python"
  mkdir -p "$apps_dir"
  {
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Version=1.0"
    echo "Name=Total Commander Clone"
    echo "Comment=Dual-pane file manager"
    printf 'Exec="%s" "%s"\n' "$py" "$ROOT/main.py"
    printf 'Path=%s\n' "$ROOT"
    if [[ -f "$ROOT/file-explorer.ico" ]]; then
      printf 'Icon=%s\n' "$ROOT/file-explorer.ico"
    fi
    echo "Terminal=false"
    echo "Categories=Utility;FileManager;"
    echo "StartupWMClass=Total Commander Clone"
  } > "$desktop"
  chmod 644 "$desktop"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" || warn "Could not refresh the desktop database."
  fi
  info "Wrote $desktop"
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
  warn "Could not install 7-Zip. Archive browsing needs it."
  warn "  Install the 7zip package (Debian may call it p7zip-full)."
  return 0
}

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
main() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux*) ;;
    Darwin*)
      err "This installer is for Linux."
      err "  On macOS run:  bash scripts/install_macos.sh"
      exit 1
      ;;
    *)
      err "This installer is for Linux."
      err "  macOS:    bash scripts/install_macos.sh"
      err "  Windows:  scripts\\install_windows.bat"
      exit 1
      ;;
  esac

  detect_arch
  info "Detected OS: linux"
  info "Detected hardware: $ARCH — $ARCH_LABEL"

  resolve_python
  info "Using Python: ${PY_CMD[*]}"
  "${PY_CMD[@]}" --version

  create_venv_and_install "${PY_CMD[@]}"
  install_sevenzip || warn "Continuing without 7-Zip."
  write_run_sh
  write_desktop_entry

  info "Done."
  info "  Start from a terminal:  bash scripts/run.sh"
  info "  Taskbar / menu:         Total Commander Clone"
}

main "$@"
