"""
Total Commander Clone - Startup update check
Compare local APP_VERSION to the public GitHub repo (and/or local git remote)
and optionally launch scripts/update-and-rebuild.bat (pull + build).

The canonical public repo needs no username/PAT for read (fetch/pull/raw).
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from config_backup import (
    _authGitEnv,
    _loadSavedGitAuth,
    _runGit,
    findGitRepoRoot,
    loadGitAccountProfile,
    resolveBackupRepoRoot,
    runGitPushWithAuth,
)


# Public upstream (read without credentials).
PUBLIC_REPO_HTTPS = "https://github.com/derya-kromeka/total-commander-clone.git"
PUBLIC_REPO_OWNER = "derya-kromeka"
PUBLIC_REPO_NAME = "total-commander-clone"
PUBLIC_DEFAULT_BRANCH = "main"

_VERSION_RE = re.compile(
    r'APP_VERSION\s*=\s*["\'](\d+\.\d+\.\d+(?:\.\d+)?)["\']'
)


# ------------------------------------------------------------
# Function: parseVersion
# Purpose: Parse "x.y.z" into a comparable tuple of ints.
# ------------------------------------------------------------
def parseVersion(text: str) -> Optional[Tuple[int, ...]]:
    raw = (text or "").strip()
    if not raw:
        return None
    parts = []
    for piece in raw.split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    if len(parts) < 2:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


# ------------------------------------------------------------
# Function: parseAppVersionFromText
# Purpose: Extract APP_VERSION from app_version.py contents.
# ------------------------------------------------------------
def parseAppVersionFromText(text: str) -> Optional[str]:
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    return match.group(1)


# ------------------------------------------------------------
# Function: compareVersions
# Purpose: -1 if a<b, 0 if equal, 1 if a>b. None if unparsable.
# ------------------------------------------------------------
def compareVersions(a: str, b: str) -> Optional[int]:
    ta = parseVersion(a)
    tb = parseVersion(b)
    if ta is None or tb is None:
        return None
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


# ------------------------------------------------------------
# Function: _looksLikeProjectRoot
# Purpose: Folder has main.py and the update/build scripts.
# ------------------------------------------------------------
def _looksLikeProjectRoot(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    return (
        os.path.isfile(os.path.join(path, "main.py"))
        and os.path.isfile(os.path.join(path, "scripts", "update-and-rebuild.bat"))
        and (
            os.path.isfile(os.path.join(path, "scripts", "build-user.bat"))
            or os.path.isfile(os.path.join(path, "scripts", "build.bat"))
        )
    )


# ------------------------------------------------------------
# Function: findProjectRoot
# Purpose: Walk parents for a project folder (with or without .git).
# ------------------------------------------------------------
def findProjectRoot(start_path: Optional[str] = None) -> Optional[str]:
    candidates: List[str] = []
    if start_path:
        candidates.append(start_path)
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    if getattr(__import__("sys"), "frozen", False):
        import sys

        candidates.append(os.path.dirname(sys.executable))

    seen = set()
    for start in candidates:
        if not start:
            continue
        cur = os.path.abspath(start)
        for _ in range(12):
            if cur in seen:
                break
            seen.add(cur)
            if _looksLikeProjectRoot(cur):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return None


# ------------------------------------------------------------
# Function: resolveUpdateRepoRoot
# Purpose: Find project root for updates (.git preferred, not required).
# ------------------------------------------------------------
def resolveUpdateRepoRoot(project_root: Optional[str] = None) -> Optional[str]:
    # Prefer a real git checkout when present.
    root = resolveBackupRepoRoot(project_root)
    if root and os.path.isdir(os.path.join(root, ".git")) and _looksLikeProjectRoot(root):
        return root
    if project_root:
        found = findGitRepoRoot(project_root)
        if found and _looksLikeProjectRoot(found):
            return found
    # Zip-based updates work without .git — only need source + scripts.
    return findProjectRoot(project_root)


# ------------------------------------------------------------
# Function: _gitAvailable
# ------------------------------------------------------------
def _gitAvailable() -> bool:
    try:
        completed = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **(
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
                if os.name == "nt"
                else {}
            ),
        )
        return completed.returncode == 0
    except Exception:
        return False


# ------------------------------------------------------------
# Function: _currentBranch
# ------------------------------------------------------------
def _currentBranch(repo_root: str) -> str:
    ok, out = _runGit(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=15)
    branch = (out or "").strip()
    if ok and branch and branch != "HEAD":
        return branch
    return PUBLIC_DEFAULT_BRANCH


# ------------------------------------------------------------
# Function: _defaultRemote
# ------------------------------------------------------------
def _defaultRemote(repo_root: str) -> str:
    ok, out = _runGit(repo_root, ["remote"], timeout=15)
    if not ok:
        return "origin"
    remotes = [line.strip() for line in (out or "").splitlines() if line.strip()]
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes else "origin"


# ------------------------------------------------------------
# Function: ensurePublicOrigin
# Purpose: If origin is missing, add the public HTTPS remote (no auth).
# ------------------------------------------------------------
def ensurePublicOrigin(repo_root: str) -> Tuple[bool, str]:
    remote = _defaultRemote(repo_root)
    ok, url = _runGit(repo_root, ["remote", "get-url", remote], timeout=15)
    if ok and (url or "").strip():
        return True, remote

    ok, out = _runGit(
        repo_root,
        ["remote", "add", "origin", PUBLIC_REPO_HTTPS],
        timeout=15,
    )
    if ok:
        return True, "origin"
    # Race / already exists under another form
    ok2, _ = _runGit(
        repo_root,
        ["remote", "set-url", "origin", PUBLIC_REPO_HTTPS],
        timeout=15,
    )
    if ok2:
        return True, "origin"
    return False, out or "Could not configure origin"


# ------------------------------------------------------------
# Function: fetchPublicAppVersionViaHttps
# Purpose: Read APP_VERSION from raw.githubusercontent.com (anonymous).
# ------------------------------------------------------------
def fetchPublicAppVersionViaHttps(branch: str = PUBLIC_DEFAULT_BRANCH) -> Tuple[Optional[str], str]:
    branches: List[str] = []
    if branch:
        branches.append(branch)
    if PUBLIC_DEFAULT_BRANCH not in branches:
        branches.append(PUBLIC_DEFAULT_BRANCH)
    if "master" not in branches:
        branches.append("master")

    errors = []
    for br in branches:
        url = (
            f"https://raw.githubusercontent.com/{PUBLIC_REPO_OWNER}/"
            f"{PUBLIC_REPO_NAME}/{br}/app_version.py"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "TotalCommanderClone-Updater"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            ver = parseAppVersionFromText(text)
            if ver:
                return ver, br
            errors.append(f"{br}: no APP_VERSION in file")
        except urllib.error.HTTPError as exc:
            errors.append(f"{br}: HTTP {exc.code}")
        except Exception as exc:
            errors.append(f"{br}: {exc}")

    return None, "; ".join(errors) if errors else "HTTPS version fetch failed"


# ------------------------------------------------------------
# Function: _fetchRemoteBranch
# Purpose: Fetch remote/branch anonymously; retry with saved PAT only if needed.
# ------------------------------------------------------------
def _fetchRemoteBranch(repo_root: str, remote: str, branch: str) -> Tuple[bool, str]:
    ok, out = _runGit(repo_root, ["fetch", remote, branch], timeout=90)
    if ok:
        return True, out

    # Public HTTPS remotes normally succeed without auth. Retry with PAT only
    # when a saved account exists (e.g. private fork / rate limits).
    auth_env = _authGitEnv(_loadSavedGitAuth(repo_root))
    if not auth_env:
        return False, out
    return _runGit(repo_root, ["fetch", remote, branch], timeout=90, extra_env=auth_env)


# ------------------------------------------------------------
# Function: checkRemoteAppVersion
# Purpose: Prefer anonymous GitHub raw version; fall back to git fetch/show.
# Output: dict with status, local, remote, message, repo_root, …
# ------------------------------------------------------------
def checkRemoteAppVersion(
    local_version: str,
    project_root: Optional[str] = None,
    skip_version: str = "",
) -> Dict[str, Any]:
    repo_root = resolveUpdateRepoRoot(project_root)
    result: Dict[str, Any] = {
        "status": "error",
        "local": local_version,
        "remote": "",
        "repo_root": repo_root or "",
        "message": "",
        "branch": "",
        "remote_name": "",
        "source": "",
        "can_publish": False,
    }

    if not repo_root:
        result["status"] = "no_repo"
        result["message"] = (
            "Could not find the project folder near this app "
            "(needs main.py and scripts\\update-and-rebuild.bat).\n"
            f"Public repo: https://github.com/{PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME}"
        )
        return result

    script = os.path.join(repo_root, "scripts", "update-and-rebuild.bat")
    if not os.path.isfile(script):
        result["status"] = "no_script"
        result["message"] = (
            f"Update script not found:\n{script}\n\n"
            "Keep the full project folder so updates can download sources and rebuild."
        )
        return result

    has_git = _gitAvailable() and os.path.isdir(os.path.join(repo_root, ".git"))
    if has_git:
        ensurePublicOrigin(repo_root)
        remote = _defaultRemote(repo_root)
        branch = _currentBranch(repo_root)
        result["remote_name"] = remote
    else:
        remote = "origin"
        branch = PUBLIC_DEFAULT_BRANCH
        result["remote_name"] = "(GitHub zip / HTTPS)"
    result["branch"] = branch

    remote_version = None
    # 1) Anonymous HTTPS (no account, no Git) — preferred for the public repo.
    https_ver, https_info = fetchPublicAppVersionViaHttps(branch)
    if https_ver:
        remote_version = https_ver
        result["source"] = "https"
        if https_info and https_info != branch:
            result["branch"] = https_info
            branch = https_info
    elif has_git:
        # 2) Fall back to local git fetch + show.
        ok, fetch_out = _fetchRemoteBranch(repo_root, remote, branch)
        if not ok:
            result["status"] = "fetch_failed"
            result["message"] = (
                "Could not read the latest version from GitHub "
                f"({PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME}).\n\n"
                f"HTTPS: {https_info}\n"
                f"Git: {(fetch_out or 'Unknown fetch error')[:400]}"
            )
            return result

        ok, remote_file = _runGit(
            repo_root,
            ["show", f"{remote}/{branch}:app_version.py"],
            timeout=30,
        )
        if not ok:
            result["status"] = "no_remote_version"
            result["message"] = (
                f"Could not read app_version.py from {remote}/{branch}."
            )
            return result

        remote_version = parseAppVersionFromText(remote_file)
        result["source"] = "git"
    else:
        result["status"] = "fetch_failed"
        result["message"] = (
            "Could not read the latest version from GitHub "
            f"({PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME}).\n\n"
            f"{https_info}\n\n"
            "No Git install is required when the network can reach GitHub."
        )
        return result

    if not remote_version:
        result["status"] = "no_remote_version"
        result["message"] = "Remote app_version.py has no parsable APP_VERSION."
        return result

    result["remote"] = remote_version
    cmp = compareVersions(local_version, remote_version)
    if cmp is None:
        result["status"] = "error"
        result["message"] = "Could not compare version numbers."
        return result

    if cmp == 0:
        result["status"] = "up_to_date"
        result["can_publish"] = False
        result["message"] = (
            f"You are on the latest version (v{local_version})."
        )
        return result

    if cmp > 0:
        can_publish = bool(
            has_git and os.path.isdir(os.path.join(repo_root, ".git"))
        )
        result["status"] = "local_ahead"
        result["can_publish"] = can_publish
        if can_publish:
            result["message"] = (
                f"Your version (v{local_version}) is newer than "
                f"GitHub (v{remote_version}).\n\n"
                f"Branch: {branch}\n"
                f"Repo:   {PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME}\n\n"
                "You can publish this version to GitHub (commit if needed, "
                "then a normal push — never force-push)."
            )
        else:
            result["message"] = (
                f"Your version (v{local_version}) is newer than "
                f"GitHub (v{remote_version}).\n\n"
                "Publishing requires a Git source checkout (a .git folder) "
                "and Git installed. Frozen/exe-only installs cannot push."
            )
        return result

    if skip_version and skip_version.strip() == remote_version:
        result["status"] = "skipped"
        result["message"] = (
            f"Update to v{remote_version} was skipped earlier."
        )
        return result

    result["status"] = "update_available"
    how = (
        "download the public zip (no Git install needed)"
        if not (_gitAvailable() and os.path.isdir(os.path.join(repo_root, ".git")))
        else "pull the latest public code"
    )
    result["message"] = (
        f"A newer version is available on GitHub.\n\n"
        f"Current:  v{local_version}\n"
        f"GitHub:   v{remote_version}\n"
        f"Repo:     {PUBLIC_REPO_OWNER}/{PUBLIC_REPO_NAME}\n"
        f"Branch:   {branch}\n\n"
        f"Update now? This will close the app, {how}, "
        "rebuild the .exe (scripts\\build-user.bat), and restart.\n"
        "No GitHub login is required."
    )
    return result


# ------------------------------------------------------------
# Function: getRemoteUrl
# Purpose: origin (or default remote) URL for display / credentials.
# ------------------------------------------------------------
def getRemoteUrl(repo_root: str) -> str:
    if not repo_root:
        return PUBLIC_REPO_HTTPS
    remote = _defaultRemote(repo_root)
    ok, url = _runGit(repo_root, ["remote", "get-url", remote], timeout=15)
    if ok and (url or "").strip():
        return (url or "").strip()
    profile = loadGitAccountProfile(repo_root) or {}
    saved = (profile.get("remoteUrl") or "").strip()
    return saved or PUBLIC_REPO_HTTPS


# ------------------------------------------------------------
# Function: getWorkingTreeDirty
# Purpose: True when git status --porcelain has any output.
#          None when git status itself failed (state unknown).
# ------------------------------------------------------------
def getWorkingTreeDirty(repo_root: str) -> Optional[bool]:
    ok, status = _runGit(repo_root, ["status", "--porcelain"], timeout=30)
    if not ok:
        return None
    return bool((status or "").strip())


# ------------------------------------------------------------
# Function: getPublishPreview
# Purpose: Facts for the publish confirmation dialog.
# ------------------------------------------------------------
def getPublishPreview(
    repo_root: str,
    local_version: str = "",
    remote_version: str = "",
) -> Dict[str, Any]:
    has_git = (
        bool(repo_root)
        and _gitAvailable()
        and os.path.isdir(os.path.join(repo_root, ".git"))
    )
    branch = _currentBranch(repo_root) if has_git else PUBLIC_DEFAULT_BRANCH
    remote_url = getRemoteUrl(repo_root) if has_git else PUBLIC_REPO_HTTPS
    dirty = getWorkingTreeDirty(repo_root) if has_git else False
    return {
        "repo_root": repo_root or "",
        "branch": branch,
        "remote_url": remote_url,
        "dirty": dirty,
        "local": local_version,
        "remote": remote_version,
        "can_publish": has_git,
    }


# ------------------------------------------------------------
# Function: _looksLikeAuthFailure
# Purpose: Detect push/fetch auth failures from git stderr text.
# ------------------------------------------------------------
def _looksLikeAuthFailure(text: str) -> bool:
    lower = (text or "").lower()
    needles = (
        "authentication failed",
        "could not read username",
        "invalid username or password",
        "403",
        "401",
        "support for password authentication was removed",
        "permission denied",
        "access denied",
        "fatal: could not read password",
        "repository not found",
    )
    return any(n in lower for n in needles)


# ------------------------------------------------------------
# Function: _looksLikeNonFastForward
# Purpose: Detect rejected non-force-safe pushes.
# ------------------------------------------------------------
def _looksLikeNonFastForward(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        n in lower
        for n in (
            "non-fast-forward",
            "fetch first",
            "updates were rejected",
            "failed to push some refs",
            "[rejected]",
        )
    )


# ------------------------------------------------------------
# Function: publishLocalVersionToGitHub
# Purpose: Fetch, verify local APP_VERSION is still ahead, commit
#          if dirty, then normal (non-force) push. auth optional
#          dict with username + pat; falls back to saved credentials.
# Output: (ok, message). Third tuple slot auth_failed for UI retry.
# ------------------------------------------------------------
def publishLocalVersionToGitHub(
    repo_root: str,
    auth: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, bool]:
    if not repo_root or not os.path.isdir(repo_root):
        return False, "Invalid project root.", False
    if not _gitAvailable():
        return False, "Git is not installed or not on PATH.", False
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        return (
            False,
            "This folder is not a Git checkout (no .git). "
            "Publishing requires the source repository.",
            False,
        )

    from app_version import APP_VERSION

    local_version = APP_VERSION
    ensurePublicOrigin(repo_root)
    remote = _defaultRemote(repo_root)
    branch = _currentBranch(repo_root)

    use_auth = auth if auth and auth.get("pat") else _loadSavedGitAuth(repo_root)
    auth_env = _authGitEnv(use_auth)

    # Prefer configuring remote URL when auth dialog supplied one.
    if auth and (auth.get("remote_url") or "").strip():
        url = (auth.get("remote_url") or "").strip()
        _runGit(repo_root, ["remote", "set-url", remote, url], timeout=15)

    fetch_cmd = ["fetch", remote, branch]
    ok, fetch_out = _runGit(repo_root, fetch_cmd, timeout=90, extra_env=auth_env)
    if not ok and not auth_env:
        # Anonymous fetch failed — retry with saved PAT if any.
        saved = _loadSavedGitAuth(repo_root)
        retry_env = _authGitEnv(saved)
        if retry_env:
            ok, fetch_out = _runGit(repo_root, fetch_cmd, timeout=90, extra_env=retry_env)
            if ok:
                use_auth = saved
    if not ok:
        auth_fail = _looksLikeAuthFailure(fetch_out)
        return (
            False,
            f"git fetch failed:\n{(fetch_out or 'Unknown error')[:500]}",
            auth_fail,
        )

    ok, remote_file = _runGit(
        repo_root,
        ["show", f"{remote}/{branch}:app_version.py"],
        timeout=30,
    )
    if ok:
        remote_version = parseAppVersionFromText(remote_file)
        if remote_version:
            cmp = compareVersions(local_version, remote_version)
            if cmp is not None and cmp <= 0:
                return (
                    False,
                    f"Local version v{local_version} is no longer ahead of "
                    f"GitHub v{remote_version}. Publish aborted.",
                    False,
                )

    dirty = getWorkingTreeDirty(repo_root)
    if dirty is None:
        return False, "Could not read git status. Publish aborted.", False
    if dirty:
        ok, add_out = _runGit(repo_root, ["add", "-A"], timeout=60)
        if not ok:
            return False, f"git add failed:\n{(add_out or '')[:400]}", False
        msg = f"release: v{local_version}"
        ok, commit_out = _runGit(repo_root, ["commit", "-m", msg], timeout=60)
        if not ok:
            # Nothing to commit after add is fine; other errors are not.
            lower = (commit_out or "").lower()
            if "nothing to commit" not in lower:
                return (
                    False,
                    f"git commit failed:\n{(commit_out or '')[:400]}",
                    False,
                )

    ok, push_out = runGitPushWithAuth(repo_root, auth=use_auth)
    if ok:
        return (
            True,
            f"Published v{local_version} to {remote}/{branch} "
            f"({getRemoteUrl(repo_root)}).",
            False,
        )

    if _looksLikeNonFastForward(push_out):
        return (
            False,
            "Push was rejected (non-fast-forward). "
            "Pull or merge remote changes first, then try again.\n"
            "This app never force-pushes.\n\n"
            f"{(push_out or '')[:400]}",
            False,
        )
    auth_fail = _looksLikeAuthFailure(push_out)
    return (
        False,
        f"git push failed:\n{(push_out or 'Unknown error')[:500]}",
        auth_fail,
    )


# ------------------------------------------------------------
# Function: launchUpdateAndRebuild
# Purpose: Start scripts/update-and-rebuild.bat in a new console,
#          detached so it survives after this process exits.
# ------------------------------------------------------------
def launchUpdateAndRebuild(repo_root: str) -> Tuple[bool, str]:
    if not repo_root or not os.path.isdir(repo_root):
        return False, "Invalid project root."

    bat = os.path.join(repo_root, "scripts", "update-and-rebuild.bat")
    if not os.path.isfile(bat):
        return False, f"Missing update script:\n{bat}"

    # Only configure origin when Git + .git are available.
    if _gitAvailable() and os.path.isdir(os.path.join(repo_root, ".git")):
        ensurePublicOrigin(repo_root)

    try:
        if os.name == "nt":
            # `start "title" ...` — first quoted arg is the window title.
            # DETACHED_PROCESS keeps the updater alive after we quit.
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
            subprocess.Popen(
                [
                    "cmd.exe",
                    "/c",
                    "start",
                    "Total Commander Clone — Update",
                    "cmd.exe",
                    "/c",
                    bat,
                ],
                cwd=repo_root,
                close_fds=True,
                creationflags=creationflags,
            )
        else:
            subprocess.Popen(
                ["bash", bat.replace(".bat", ".sh")],
                cwd=repo_root,
                start_new_session=True,
            )
        return True, ""
    except Exception as exc:
        return False, str(exc)
