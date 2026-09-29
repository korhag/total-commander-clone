"""
Config backup: write latest settings/bookmarks/libraries under the
local user-data directory (never into Git).

Windows: %APPDATA%\\TotalCommanderClone\\backups\\<computer-name>\\
Other:   ~/.config/TotalCommanderClone/backups/<computer-name>/

Git credential and push helpers in this module are for explicit
version publishing only, not for settings backups.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
APP_DATA_DIRNAME = "TotalCommanderClone"
BACKUP_ROOT_NAME = "backups"
MANIFEST_FILENAME = "backup_manifest.json"


# ------------------------------------------------------------
# Function: sanitizeComputerName
# Purpose: Folder-safe hostname for backup/settings/<name>/.
# ------------------------------------------------------------
def sanitizeComputerName(name: str) -> str:
    raw = (name or "").strip() or "unknown-host"
    cleaned = re.sub(r"[^\w.\-]+", "_", raw, flags=re.UNICODE)
    cleaned = cleaned.strip("._") or "unknown-host"
    return cleaned[:80]


# ------------------------------------------------------------
# Function: getComputerName
# Purpose: Local machine name for per-PC backup folders.
# ------------------------------------------------------------
def getComputerName() -> str:
    for getter in (
        lambda: os.environ.get("COMPUTERNAME"),
        lambda: os.environ.get("HOSTNAME"),
        socket.gethostname,
    ):
        try:
            value = getter()
            if value and str(value).strip():
                return sanitizeComputerName(str(value))
        except Exception:
            continue
    return "unknown-host"


# ------------------------------------------------------------
# Function: findGitRepoRoot
# Purpose: Walk parents of start_path looking for a .git directory.
# ------------------------------------------------------------
def findGitRepoRoot(start_path: str) -> Optional[str]:
    if not start_path:
        return None
    cur = os.path.abspath(start_path)
    for _ in range(10):
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


# ------------------------------------------------------------
# Function: resolveBackupRepoRoot
# Purpose: Locate the Git/project checkout (used by update/publish,
#          not by settings backups).
# ------------------------------------------------------------
def resolveBackupRepoRoot(project_root: Optional[str] = None) -> Optional[str]:
    candidates = []
    if project_root:
        candidates.append(project_root)
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    if getattr(__import__("sys"), "frozen", False):
        import sys

        candidates.append(os.path.dirname(sys.executable))
    for start in candidates:
        root = findGitRepoRoot(start)
        if root:
            return root
    # Dev without .git yet: still write under project/source folder.
    if project_root and os.path.isdir(project_root):
        return os.path.abspath(project_root)
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isdir(here):
        return here
    return None


# ------------------------------------------------------------
# Function: getUserDataDir
# Purpose: Per-user app data folder (settings backups live here).
# ------------------------------------------------------------
def getUserDataDir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_DATA_DIRNAME)


# ------------------------------------------------------------
# Function: getComputerBackupDir
# Purpose: <user-data>/backups/<computer-name>/ for this PC.
# ------------------------------------------------------------
def getComputerBackupDir(
    user_data_dir: Optional[str] = None,
    computer_name: Optional[str] = None,
) -> str:
    host = computer_name or getComputerName()
    root = user_data_dir or getUserDataDir()
    return os.path.join(root, BACKUP_ROOT_NAME, host)


# ------------------------------------------------------------
# Function: _writeJson
# Purpose: Write pretty JSON; replace previous file in place (latest only).
# ------------------------------------------------------------
def _writeJson(path: str, data: Any) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ------------------------------------------------------------
# Function: countBookmarkNodes
# Purpose: Count bookmark entries, including ones nested in groups.
# ------------------------------------------------------------
def countBookmarkNodes(structure: Any) -> int:
    """Count bookmark entries, including ones nested inside groups."""
    count = 0

    def walk(nodes: Any) -> None:
        nonlocal count
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "group":
                walk(node.get("children", []))
            elif node.get("type") == "bookmark" or "path" in node:
                count += 1

    walk(structure)
    return count


def _readBackupBookmarks(backup_dir: str) -> Optional[list]:
    path = os.path.join(backup_dir, "bookmarks.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("bookmarks"), list):
        return data["bookmarks"]
    return None


def _bookmarksForBackup(
    state: Dict[str, Any],
    backup_dir: str,
    allow_empty_bookmarks: bool,
) -> list:
    incoming = (state or {}).get("bookmarks", [])
    if not isinstance(incoming, list):
        incoming = []
    if countBookmarkNodes(incoming) == 0 and not allow_empty_bookmarks:
        existing = _readBackupBookmarks(backup_dir)
        if existing is not None and countBookmarkNodes(existing) > 0:
            return existing
    return incoming


# ------------------------------------------------------------
# Function: writeConfigBackup
# Purpose: Write latest settings/bookmarks/libraries for this PC
#          under the local user-data directory. Overwrites previous
#          files in the same computer folder. Does not touch Git.
#          An empty bookmark list does not replace a non-empty
#          backup unless allow_empty_bookmarks is true.
# Output: Absolute backup directory path, or None on failure.
# ------------------------------------------------------------
def writeConfigBackup(
    settings: Dict[str, Any],
    state: Dict[str, Any],
    user_data_dir: Optional[str] = None,
    allow_empty_bookmarks: bool = False,
) -> Optional[str]:
    host = getComputerName()
    backup_dir = getComputerBackupDir(user_data_dir, host)
    os.makedirs(backup_dir, exist_ok=True)
    bookmarks = _bookmarksForBackup(state or {}, backup_dir, allow_empty_bookmarks)

    # Keep only these latest files (overwrite; remove stray older copies).
    payload = {
        "settings.json": settings or {},
        "bookmarks.json": {
            "bookmarks": bookmarks,
        },
        "libraries.json": {
            "libraries": (state or {}).get("libraries", []),
            "folder_tags": (state or {}).get("folder_tags", {}),
            "saved_library_filters": (state or {}).get("saved_library_filters", []),
        },
        "state.json": {
            "bookmarks": bookmarks,
            "libraries": (state or {}).get("libraries", []),
            "folder_tags": (state or {}).get("folder_tags", {}),
            "saved_library_filters": (state or {}).get("saved_library_filters", []),
            "saved_file_filters": (state or {}).get("saved_file_filters", []),
            "sidebar_state": (state or {}).get("sidebar_state", {}),
            "recent_paths": (state or {}).get("recent_paths", []),
            "left_panel": (state or {}).get("left_panel", {}),
            "right_panel": (state or {}).get("right_panel", {}),
        },
    }

    for filename, data in payload.items():
        _writeJson(os.path.join(backup_dir, filename), data)

    manifest = {
        "computer_name": host,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(payload.keys()),
        "app_note": (
            "Latest local backup only for this computer; overwritten on each save. "
            "Not stored in Git. Use Settings export/import to copy a profile."
        ),
    }
    _writeJson(os.path.join(backup_dir, MANIFEST_FILENAME), manifest)

    # Remove unknown extras so the folder stays "latest only".
    keep = set(payload.keys()) | {MANIFEST_FILENAME}
    try:
        for name in os.listdir(backup_dir):
            if name in keep or name.endswith(".tmp"):
                continue
            path = os.path.join(backup_dir, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass

    return backup_dir


# ------------------------------------------------------------
# Function: _hiddenSubprocessKwargs
# Purpose: On Windows, hide console windows for git/powershell so the
#          GUI app does not flash cmd windows on every backup upload.
# ------------------------------------------------------------
def _hiddenSubprocessKwargs() -> Dict[str, Any]:
    if os.name != "nt":
        return {}
    # CREATE_NO_WINDOW (0x08000000) — available on Python 3.7+ as
    # subprocess.CREATE_NO_WINDOW; keep literal fallback for older builds.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    kwargs: Dict[str, Any] = {"creationflags": flags}
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


# ------------------------------------------------------------
# Function: _runGit
# Purpose: Run a git command in repo_root; return (ok, combined output).
# ------------------------------------------------------------
def _runGit(repo_root: str, args, timeout: int = 60):
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **_hiddenSubprocessKwargs(),
        )
        out = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode == 0, out.strip()
    except Exception as exc:
        return False, str(exc)


# ------------------------------------------------------------
# Function: _loadSavedGitAuth
# Purpose: Username + DPAPI-decrypted PAT from .git-account.* (Windows).
# ------------------------------------------------------------
def _loadSavedGitAuth(repo_root: str):
    profile_path = os.path.join(repo_root, ".git-account.json")
    pat_path = os.path.join(repo_root, ".git-account.pat")
    if not os.path.isfile(profile_path) or not os.path.isfile(pat_path):
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        username = (profile.get("githubUsername") or "").strip()
        if not username:
            return None
        if os.name != "nt":
            return None
        # Escape single quotes for PowerShell single-quoted path literal.
        pat_ps = pat_path.replace("'", "''")
        ps = (
            "$ErrorActionPreference='Stop';"
            f"$enc = Get-Content -LiteralPath '{pat_ps}' -Raw -Encoding UTF8;"
            "$sec = ConvertTo-SecureString -String $enc;"
            "$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec);"
            "try { [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }"
            "finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }"
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            **_hiddenSubprocessKwargs(),
        )
        if completed.returncode != 0:
            return None
        pat = (completed.stdout or "").strip()
        if not pat:
            return None
        return {"username": username, "pat": pat}
    except Exception:
        return None


# ------------------------------------------------------------
# Function: loadGitAccountProfile
# Purpose: Read .git-account.json fields (no PAT decrypt).
# ------------------------------------------------------------
def loadGitAccountProfile(repo_root: str) -> Optional[Dict[str, Any]]:
    if not repo_root:
        return None
    profile_path = os.path.join(repo_root, ".git-account.json")
    if not os.path.isfile(profile_path):
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


# ------------------------------------------------------------
# Function: saveGitAccountCredentials
# Purpose: Save GitHub username/URL to .git-account.json and encrypt
#          PAT into .git-account.pat (Windows DPAPI via PowerShell).
# ------------------------------------------------------------
def saveGitAccountCredentials(
    repo_root: str,
    username: str,
    remote_url: str = "",
    pat: str = "",
    commit_name: str = "",
    commit_email: str = "",
) -> Tuple[bool, str]:
    if not repo_root or not os.path.isdir(repo_root):
        return False, "Invalid repository root."
    username = (username or "").strip()
    if not username:
        return False, "GitHub username is required."
    if os.name != "nt":
        return False, "Saving an encrypted PAT is only supported on Windows."

    existing = loadGitAccountProfile(repo_root) or {}
    profile = {
        "label": existing.get("label") or "default",
        "remoteUrl": (remote_url or "").strip() or (existing.get("remoteUrl") or ""),
        "commitName": (commit_name or "").strip() or (existing.get("commitName") or ""),
        "commitEmail": (commit_email or "").strip() or (existing.get("commitEmail") or ""),
        "githubUsername": username,
    }
    profile_path = os.path.join(repo_root, ".git-account.json")
    pat_path = os.path.join(repo_root, ".git-account.pat")
    try:
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        return False, f"Could not write .git-account.json: {exc}"

    pat = (pat or "").strip()
    if not pat:
        return True, "Saved profile (PAT unchanged)."

    import tempfile

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="tcc-pat-", suffix=".txt")
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(pat)
        tmp_ps = tmp_path.replace("'", "''")
        pat_ps = pat_path.replace("'", "''")
        ps = (
            "$ErrorActionPreference='Stop';"
            f"$plain = (Get-Content -LiteralPath '{tmp_ps}' -Raw -Encoding UTF8).Trim();"
            "if (-not $plain) { throw 'Empty PAT' };"
            "$secure = ConvertTo-SecureString -String $plain -AsPlainText -Force;"
            "$enc = ConvertFrom-SecureString -SecureString $secure;"
            f"Set-Content -LiteralPath '{pat_ps}' -Value $enc -Encoding UTF8 -NoNewline;"
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            **_hiddenSubprocessKwargs(),
        )
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "encrypt failed").strip()
            return False, f"Could not encrypt PAT: {err[:300]}"
        return True, "Saved profile and encrypted PAT."
    except Exception as exc:
        return False, str(exc)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ------------------------------------------------------------
# Function: _authExtraHeaderArgs
# Purpose: git -c http.extraHeader=AUTHORIZATION… args, or [].
# ------------------------------------------------------------
def _authExtraHeaderArgs(auth: Optional[Dict[str, Any]]):
    if not auth or not auth.get("pat"):
        return []
    import base64

    user = (auth.get("username") or "").strip()
    pat = (auth.get("pat") or "").strip()
    if not user or not pat:
        return []
    pair = f"{user}:{pat}"
    encoded = base64.b64encode(pair.encode("ascii")).decode("ascii")
    header = f"AUTHORIZATION: basic {encoded}"
    return ["-c", f"http.extraHeader={header}"]


# ------------------------------------------------------------
# Function: runGitPushWithAuth
# Purpose: Push HEAD with optional explicit auth; never force.
# Output: (ok, combined git output).
# ------------------------------------------------------------
def runGitPushWithAuth(
    repo_root: str,
    auth: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    push_args = ["push", "-u", "origin", "HEAD"]
    use_auth = auth if auth and auth.get("pat") else _loadSavedGitAuth(repo_root)
    header_args = _authExtraHeaderArgs(use_auth)
    if header_args:
        ok, out = _runGit(repo_root, [*header_args, *push_args], timeout=120)
        if ok:
            return True, out
        # Fall through to plain push only when no explicit auth was given.
        if auth and auth.get("pat"):
            return False, out
    return _runGit(repo_root, push_args, timeout=120)


# ------------------------------------------------------------
# Function: backupConfig
# Purpose: Write latest per-PC backup under the user-data directory.
#          Does not commit, push, or otherwise invoke Git.
# ------------------------------------------------------------
def backupConfig(
    settings: Dict[str, Any],
    state: Dict[str, Any],
    user_data_dir: Optional[str] = None,
    allow_empty_bookmarks: bool = False,
) -> Optional[str]:
    try:
        return writeConfigBackup(
            settings,
            state,
            user_data_dir=user_data_dir,
            allow_empty_bookmarks=allow_empty_bookmarks,
        )
    except Exception as exc:
        print(f"[ConfigBackup] Write failed: {exc}")
        return None
