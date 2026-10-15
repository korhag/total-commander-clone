"""
Total Commander Clone - Drive list
Builds the entries shown in each panel's drive dropdown:
  - Windows: drive letters (C:\\, D:\\, ...).
  - Linux: "/" and "~", then real mounted folders (USB sticks, network
    shares, rclone/FUSE mounts) labelled with their folder name.
  - Other systems: "/" and "~".
Pure functions only, so they can be unit-tested without Qt.
"""

import os
import re
import shutil
import string
import sys
from collections import namedtuple


# ------------------------------------------------------------
# Constants (Linux mount filtering)
# ------------------------------------------------------------
LINUX_MOUNTS_FILE = "/proc/self/mounts"

# Filesystem types that are never a place a user browses.
IGNORED_FS_TYPES = frozenset({
    "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "squashfs", "overlay",
    "autofs", "fusectl", "fuse.portal", "fuse.gvfsd-fuse", "efivarfs",
    "debugfs", "tracefs", "configfs", "mqueue", "hugetlbfs", "bpf",
    "pstore", "securityfs", "binfmt_misc", "nsfs", "ramfs", "rpc_pipefs",
})
IGNORED_FS_PREFIXES = ("cgroup",)

# System locations. /run/media is kept because removable media mount there.
IGNORED_PATH_PREFIXES = (
    "/proc", "/sys", "/dev", "/run", "/tmp", "/boot", "/efi", "/var", "/snap",
)
KEPT_PATH_PREFIXES = ("/run/media",)

ROOT_LABEL = "/"
HOME_LABEL = "~"

_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")

# Filesystem types that live on another machine. Reading them can stall,
# so callers skip work that would touch every file (folder tooltip sizes).
REMOTE_FS_TYPES = frozenset({
    "cifs", "smbfs", "smb3", "9p", "davfs", "fuse",
})
REMOTE_FS_PREFIXES = ("fuse.", "nfs")

# label: text in the dropdown; path: folder to open;
# is_mount: True for extra mounts (the panel adds a separator before them).
DriveEntry = namedtuple("DriveEntry", ["label", "path", "is_mount"])

# total, used, and free bytes on the volume that holds a folder.
DriveSpace = namedtuple("DriveSpace", ["total", "used", "free"])


# ------------------------------------------------------------
# Function: _isUnder
# Purpose: True when path equals root or lies inside it.
# ------------------------------------------------------------
def _isUnder(path, root):
    path_norm = os.path.normcase(os.path.normpath(path))
    root_norm = os.path.normcase(os.path.normpath(root))
    return path_norm == root_norm or path_norm.startswith(
        root_norm.rstrip(os.sep) + os.sep
    )


# ------------------------------------------------------------
# Function: _isUnderAny
# ------------------------------------------------------------
def _isUnderAny(path, roots):
    return any(_isUnder(path, root) for root in roots)


# ------------------------------------------------------------
# Function: _decodeMountPath
# Purpose: /proc/self/mounts writes space, tab, newline and backslash
#          as octal escapes (a space is "\040"). Turn them back.
# ------------------------------------------------------------
def _decodeMountPath(raw):
    return _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), raw)


# ------------------------------------------------------------
# Function: _isBrowsableMount
# Purpose: Apply the filesystem-type and location filters.
# ------------------------------------------------------------
def _isBrowsableMount(target, fs_type, home_dir):
    if fs_type in IGNORED_FS_TYPES or fs_type.startswith(IGNORED_FS_PREFIXES):
        return False
    if target == "/" or target == "/home":
        return False
    if home_dir and os.path.normpath(target) == os.path.normpath(home_dir):
        return False
    if _isUnderAny(target, IGNORED_PATH_PREFIXES) and not _isUnderAny(
        target, KEPT_PATH_PREFIXES
    ):
        return False
    return not os.path.basename(target.rstrip("/")).startswith(".")


# ------------------------------------------------------------
# Function: _iterMounts
# Purpose: Yield (target path, filesystem type) from a mount table.
# ------------------------------------------------------------
def _iterMounts(mounts_text):
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        yield _decodeMountPath(fields[1]), fields[2]


# ------------------------------------------------------------
# Function: parseLinuxMounts
# Purpose: Turn the text of /proc/self/mounts into sorted DriveEntry
#          items for real mounted folders.
# Input:  mounts_text (str), home_dir (str)
# Output: list[DriveEntry] (is_mount=True), sorted by label
# ------------------------------------------------------------
def parseLinuxMounts(mounts_text, home_dir=""):
    entries = {}
    for target, fs_type in _iterMounts(mounts_text):
        if not _isBrowsableMount(target, fs_type, home_dir):
            continue
        label = os.path.basename(target.rstrip("/"))
        entries[target] = DriveEntry(label, target, True)
    return sorted(entries.values(), key=lambda e: (e.label.lower(), e.path))


# ------------------------------------------------------------
# Function: _fsTypeIsRemote
# Purpose: True for FUSE, NFS, and Windows-share filesystems.
# ------------------------------------------------------------
def _fsTypeIsRemote(fs_type):
    if fs_type in REMOTE_FS_TYPES:
        return True
    return fs_type.startswith(REMOTE_FS_PREFIXES)


# ------------------------------------------------------------
# Function: _linuxPathIsRemote
# Purpose: True when the deepest mount that contains path is remote.
# ------------------------------------------------------------
def _linuxPathIsRemote(path, mounts_text):
    best_len = -1
    best_remote = False
    for target, fs_type in _iterMounts(mounts_text):
        if not _isUnder(path, target):
            continue
        root_len = len(os.path.normpath(target))
        if root_len > best_len:
            best_len = root_len
            best_remote = _fsTypeIsRemote(fs_type)
    return best_remote


# ------------------------------------------------------------
# Function: _windowsDriveIsRemote
# Purpose: True when the drive of path is a mapped network drive.
# ------------------------------------------------------------
def _windowsDriveIsRemote(path):
    import ctypes

    DRIVE_REMOTE = 4
    root, _tail = os.path.splitdrive(os.path.abspath(path))
    if not root:
        return False
    if not root.endswith("\\"):
        root += "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(root) == DRIVE_REMOTE


# ------------------------------------------------------------
# Function: isRemotePath
# Purpose: True when reading path may block on a network or cloud
#          mount (rclone, sshfs, NFS, a Windows mapped drive).
# Input: mounts_text - optional mount table. Tests pass a sample;
#        otherwise Linux reads /proc/self/mounts.
# ------------------------------------------------------------
def isRemotePath(path, mounts_text=None):
    if not path:
        return False
    if mounts_text is None and os.name == "nt":
        return _windowsDriveIsRemote(path)
    if mounts_text is None and not sys.platform.startswith("linux"):
        return False
    text = _readLinuxMounts() if mounts_text is None else mounts_text
    return _linuxPathIsRemote(path, text)


# ------------------------------------------------------------
# Function: _windowsDrives
# ------------------------------------------------------------
def _windowsDrives():
    return [
        DriveEntry(f"{d}:\\", f"{d}:\\", False)
        for d in string.ascii_uppercase
        if os.path.exists(f"{d}:\\")
    ]


# ------------------------------------------------------------
# Function: _readLinuxMounts
# Purpose: Read the mount table; empty text when it is unavailable.
# ------------------------------------------------------------
def _readLinuxMounts():
    try:
        with open(LINUX_MOUNTS_FILE, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


# ------------------------------------------------------------
# Function: listDrives
# Purpose: Entries for the drive dropdown on the current OS.
# Output: list[DriveEntry]; empty when there is nothing to show.
# ------------------------------------------------------------
def listDrives():
    if os.name == "nt":
        return _windowsDrives()
    home_dir = os.path.expanduser("~")
    entries = [DriveEntry(ROOT_LABEL, "/", False)]
    if home_dir and os.path.isdir(home_dir) and home_dir != "/":
        entries.append(DriveEntry(HOME_LABEL, home_dir, False))
    if sys.platform.startswith("linux"):
        entries.extend(parseLinuxMounts(_readLinuxMounts(), home_dir))
    return entries


# ------------------------------------------------------------
# Function: findDriveForPath
# Purpose: Index of the entry that best contains path (the longest
#          matching root), or -1 when none contains it.
# ------------------------------------------------------------
def findDriveForPath(entries, path):
    best_index = -1
    best_len = -1
    for index, entry in enumerate(entries):
        if _isUnder(path, entry.path):
            root_len = len(os.path.normpath(entry.path))
            if root_len > best_len:
                best_index, best_len = index, root_len
    return best_index


# ------------------------------------------------------------
# Function: _fallbackDriveLabel
# Purpose: Root of path when no dropdown entry contains it.
#          "/" on Linux and macOS, "C:\\" style on Windows.
# ------------------------------------------------------------
def _fallbackDriveLabel(path):
    if not path:
        return ""
    if os.name == "nt":
        drive, _tail = os.path.splitdrive(os.path.abspath(path))
        if drive:
            return drive if drive.endswith("\\") else drive + "\\"
    return os.sep


# ------------------------------------------------------------
# Function: driveLabelForPath
# Purpose: Label of the dropdown entry that contains path
#          (the deepest match, so a mount wins over Home and /).
#          When none contains it, the root of path.
# ------------------------------------------------------------
def driveLabelForPath(entries, path):
    if path:
        entry_index = findDriveForPath(entries or [], path)
        if entry_index >= 0:
            return entries[entry_index].label
    return _fallbackDriveLabel(path)


# ------------------------------------------------------------
# Function: readDriveSpace
# Purpose: Bytes on the volume that holds path.
# Output: DriveSpace, or None when the volume cannot be read.
# ------------------------------------------------------------
def readDriveSpace(path):
    if not path:
        return None
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return DriveSpace(usage.total, usage.used, usage.free)
