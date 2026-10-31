"""
Total Commander Clone - Open the default terminal in a folder.

Linux honors $TERMINAL, then the freedesktop launcher
xdg-terminal-exec, then a short list of known terminals.
Windows prefers Windows Terminal and otherwise opens cmd.
Every launch is given the folder as its working directory,
so a terminal that ignores the directory flag still starts there.
"""

import os
import platform
import shutil
import subprocess


# ------------------------------------------------------------
# Directory flags
# The key is the executable's file name. The value is the
# extra arguments, with "{folder}" standing in for the path.
# An empty tuple means the terminal has no directory flag
# and must rely on the process working directory.
# ------------------------------------------------------------
LINUX_CWD_FLAGS = {
    "xdg-terminal-exec": ("--dir={folder}",),
    "alacritty": ("--working-directory", "{folder}"),
    "kitty": ("--directory", "{folder}"),
    "ghostty": ("--working-directory={folder}",),
    "foot": ("--working-directory={folder}",),
    "wezterm": ("start", "--cwd", "{folder}"),
    "konsole": ("--workdir", "{folder}"),
    "gnome-terminal": ("--working-directory={folder}",),
    "ptyxis": ("--working-directory={folder}",),
    "kgx": ("--working-directory={folder}",),
    "xfce4-terminal": ("--working-directory={folder}",),
    "terminator": ("--working-directory={folder}",),
    "tilix": ("-w", "{folder}"),
    "x-terminal-emulator": (),
    "xterm": (),
}

# Tried, in order, when $TERMINAL is unset or not installed.
LINUX_FALLBACK_NAMES = (
    "xdg-terminal-exec",
    "alacritty",
    "kitty",
    "ghostty",
    "foot",
    "wezterm",
    "konsole",
    "gnome-terminal",
    "ptyxis",
    "kgx",
    "xfce4-terminal",
    "terminator",
    "tilix",
    "x-terminal-emulator",
    "xterm",
)


# ------------------------------------------------------------
# Function: _programName
# Purpose: File name used to look up a directory flag.
#          "Kitty", "/usr/bin/kitty", and "kitty.exe" all
#          match the "kitty" entry.
# ------------------------------------------------------------
def _programName(executable):
    name = os.path.basename(str(executable)).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


# ------------------------------------------------------------
# Function: _commandFor
# Purpose: argv for one terminal, including its directory flag
#          when this program has one.
# ------------------------------------------------------------
def _commandFor(executable, folder):
    flags = LINUX_CWD_FLAGS.get(_programName(executable), ())
    extra = [part.replace("{folder}", folder) for part in flags]
    return [executable, *extra]


# ------------------------------------------------------------
# Function: buildTerminalCommand
# Purpose: Choose the argv that opens a terminal in `folder`.
# Input: folder (str) - directory the terminal should start in.
#        system (str) - platform.system() value, so tests can
#                       pass "Linux" or "Windows".
#        env (mapping) - environment, read for $TERMINAL.
#        which (callable) - resolves a program name to a path,
#                           or returns None when it is missing.
# Output: list of strings suitable for subprocess.Popen.
# Raises: OSError when no terminal can be found.
# ------------------------------------------------------------
def buildTerminalCommand(folder, system, env, which):
    if system == "Windows":
        windows_terminal = which("wt")
        if windows_terminal:
            # "." plus the process working directory avoids
            # quoting a path that ends in a backslash.
            return [windows_terminal, "-d", "."]
        return ["cmd.exe"]

    if system == "Darwin":
        return ["open", "-a", "Terminal", folder]

    preferred = str(env.get("TERMINAL") or "").strip()
    if preferred:
        found = which(preferred)
        if found:
            return _commandFor(found, folder)

    for name in LINUX_FALLBACK_NAMES:
        found = which(name)
        if found:
            return _commandFor(found, folder)

    raise OSError(
        "No supported terminal found. Set the TERMINAL environment "
        "variable to your terminal, or install one such as "
        "alacritty, kitty, foot, gnome-terminal, or xterm."
    )


# ------------------------------------------------------------
# Function: openTerminalAt
# Purpose: Start the default terminal with `folder` as its
#          working directory. The new process is detached so
#          closing this app does not close the terminal.
# Input: folder (str).
#        popen, system, env, which - optional stand-ins for tests.
# Output: the Popen object for the terminal process.
# Raises: OSError when no terminal can be found.
# ------------------------------------------------------------
def openTerminalAt(folder, popen=None, system=None, env=None, which=None):
    if system is None:
        system = platform.system()
    if env is None:
        env = os.environ
    if which is None:
        which = shutil.which
    if popen is None:
        popen = subprocess.Popen

    argv = buildTerminalCommand(folder, system, env, which)
    kwargs = {"cwd": folder}
    if system == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    else:
        kwargs["start_new_session"] = True
    return popen(argv, **kwargs)
