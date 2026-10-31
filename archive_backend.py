"""
Total Commander Clone - Archive backend

Talks to the 7-Zip command-line tool (7zz, 7z, or 7za). No Qt here,
so listing, path parsing, and the temp cache can be tested on their own.

A path inside an archive is a normal string:

    /home/me/photos.zip/2024/img.jpg

The archive file is the last existing file whose name has an archive
extension. Everything after it is the member path, with "/" separators.
"""

import hashlib
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime


# ------------------------------------------------------------
# Formats 7-Zip can list and extract. RAR is extract-only:
# there is no free RAR writer, so it is not in COMPRESS_FORMATS.
# Compound suffixes are checked before the final extension so
# "notes.tar.gz" is one archive, not a .gz of a .tar file.
# ------------------------------------------------------------
COMPOUND_EXTENSIONS = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tar.zst",
    ".tar.lzma",
)

ARCHIVE_EXTENSIONS = {
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".tgz",
    ".gz",
    ".bz2",
    ".tbz",
    ".tbz2",
    ".xz",
    ".txz",
    ".zst",
    ".tzst",
    ".lzma",
    ".iso",
    ".cab",
    ".jar",
    ".war",
    ".ear",
    ".apk",
    ".xpi",
    ".whl",
    ".nupkg",
}

# key, label, file suffix, 7-Zip -t type, whether a password is meaningful.
COMPRESS_FORMATS = {
    "zip": {"label": "ZIP", "ext": ".zip", "type": "zip", "password": True},
    "7z": {"label": "7z", "ext": ".7z", "type": "7z", "password": True},
    "tar": {"label": "TAR", "ext": ".tar", "type": "tar", "password": False},
    "tar.gz": {"label": "TAR.GZ", "ext": ".tar.gz", "type": "gzip", "password": False},
    "tar.xz": {"label": "TAR.XZ", "ext": ".tar.xz", "type": "xz", "password": False},
}

# 7-Zip lists these as one gzip/xz/bzip2 member. The files are in
# the tar stored inside, so listing has to unpack that layer.
WRAPPED_TAR_EXTENSIONS = {
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".tar.zst",
    ".tzst",
    ".tar.lzma",
}

# Piped formats: 7-Zip writes a tar to stdout, then a second 7-Zip
# compresses that stream. -ttar -so cannot also be -tgzip.
PIPED_COMPRESS_TYPES = {
    "tar.gz": "gzip",
    "tar.xz": "xz",
}

# key, label, 7-Zip -mx level.
COMPRESSION_LEVELS = {
    "store": {"label": "Store", "mx": "0"},
    "fast": {"label": "Fast", "mx": "3"},
    "normal": {"label": "Normal", "mx": "5"},
    "maximum": {"label": "Maximum", "mx": "9"},
}

# F3 / quick view will not pull more than this out of an archive.
ARCHIVE_PREVIEW_MAX_BYTES = 32 * 1024 * 1024

_PERCENT_RE = re.compile(r"(\d{1,3})%")
_LISTING_CACHE = {}
_LISTING_CACHE_MAX = 8
_PASSWORDS = {}
_EXE_CACHE = None
_EXE_CHECKED = False


# ------------------------------------------------------------
# Class: ArchiveToolError
# Purpose: 7-Zip is missing or refused to start.
# ------------------------------------------------------------
class ArchiveToolError(Exception):
    pass


# ------------------------------------------------------------
# Function: archiveExtension
# Purpose: Return the archive suffix of a file name, or "".
#          "a.tar.gz" returns ".tar.gz", not ".gz".
# ------------------------------------------------------------
def archiveExtension(name):
    lower = os.path.basename(name or "").lower()
    for compound in COMPOUND_EXTENSIONS:
        if lower.endswith(compound):
            return compound
    _base, ext = os.path.splitext(lower)
    if ext in ARCHIVE_EXTENSIONS:
        return ext
    return ""


# ------------------------------------------------------------
# Function: archiveDisplayStem
# Purpose: File name without the archive suffix, for
#          "Extract to <name>/" and the compress dialog.
# ------------------------------------------------------------
def archiveDisplayStem(path):
    name = os.path.basename(path or "")
    ext = archiveExtension(name)
    if ext and name.lower().endswith(ext):
        return name[: -len(ext)] or name
    stem, _single = os.path.splitext(name)
    return stem or name or "archive"


# ------------------------------------------------------------
# Function: isArchiveFile
# Purpose: True when path is an existing archive file.
# ------------------------------------------------------------
def isNavigablePath(path):
    """True for a real folder or any path 7-Zip can list."""
    if not path:
        return False
    try:
        if os.path.isdir(path):
            return True
    except OSError:
        return False
    return splitArchivePath(path) is not None


def isArchiveFile(path):
    if not path or not archiveExtension(path):
        return False
    try:
        return os.path.isfile(path)
    except OSError:
        return False


# ------------------------------------------------------------
# Function: splitArchivePath
# Purpose: Split a panel path into (archive file, member).
#          member is "" when path is the archive file itself,
#          and uses "/" even on Windows.
#          Returns None when no archive file is on the path.
#          A folder whose name ends in ".zip" is not an archive.
# ------------------------------------------------------------
def splitArchivePath(path):
    if not path or not isinstance(path, str):
        return None
    normalized = path.replace("/", os.sep).replace("\\", os.sep)
    try:
        normalized = os.path.normpath(normalized)
    except ValueError:
        return None

    inner_parts = []
    current = normalized
    while current:
        try:
            is_file = os.path.isfile(current)
        except OSError:
            is_file = False
        if is_file and archiveExtension(os.path.basename(current)):
            return current, "/".join(reversed(inner_parts))
        parent = os.path.dirname(current)
        if not parent or parent == current:
            return None
        name = os.path.basename(current)
        if not name:
            return None
        inner_parts.append(name)
        current = parent
    return None


# ------------------------------------------------------------
# Function: pathInsideArchive
# Purpose: True when path points at a member, not the archive
#          file itself. Copying the archive file stays a normal
#          file copy. Copying a member extracts it.
# ------------------------------------------------------------
def pathInsideArchive(path):
    split = splitArchivePath(path)
    return bool(split and split[1])


# ------------------------------------------------------------
# Function: find7zExecutable
# Purpose: Locate 7-Zip once per process.
#          Order: copy bundled next to a frozen exe, then
#          7zz / 7z / 7za on PATH, then the Windows install dir.
# ------------------------------------------------------------
def find7zExecutable():
    global _EXE_CACHE, _EXE_CHECKED
    if _EXE_CACHE:
        return _EXE_CACHE
    if _EXE_CHECKED:
        return None
    _EXE_CHECKED = True

    candidates = []
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidates.append(os.path.join(base, "7zip", "7z.exe"))
        candidates.append(os.path.join(base, "7z.exe"))
    for name in ("7zz", "7z", "7za"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    if os.name == "nt":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(os.path.join(root, "7-Zip", "7z.exe"))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            _EXE_CACHE = candidate
            return candidate
    return None


# ------------------------------------------------------------
# Function: reset7zExecutableCache
# Purpose: Drop the cached lookup. Used by tests.
# ------------------------------------------------------------
def reset7zExecutableCache():
    global _EXE_CACHE, _EXE_CHECKED
    _EXE_CACHE = None
    _EXE_CHECKED = False


# ------------------------------------------------------------
# Function: missing7zHint
# Purpose: Tell the user how to install 7-Zip on this OS.
# ------------------------------------------------------------
def missing7zHint():
    if os.name == "nt":
        return (
            "7-Zip is not installed.\n\n"
            "Install it with:  winget install 7zip.7zip\n"
            "Or download it from https://www.7-zip.org/"
        )
    if platform.system() == "Darwin":
        return "7-Zip is not installed.\n\nInstall it with:  brew install sevenzip"

    family = _linuxFamily()
    if family == "arch":
        command = "sudo pacman -S 7zip"
    elif family == "debian":
        command = "sudo apt install 7zip"
    elif family == "fedora":
        command = "sudo dnf install 7zip"
    elif family == "suse":
        command = "sudo zypper install 7zip"
    else:
        command = "install the 7zip package for your distribution"
    return f"7-Zip is not installed.\n\nInstall it with:  {command}"


def _linuxFamily():
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            text = handle.read().lower()
    except OSError:
        return ""
    ident = ""
    like = ""
    for line in text.splitlines():
        if line.startswith("id="):
            ident = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("id_like="):
            like = line.split("=", 1)[1].strip().strip('"')
    blob = f"{ident} {like}"
    if any(name in blob for name in ("arch", "manjaro", "endeavouros")):
        return "arch"
    if any(name in blob for name in ("debian", "ubuntu", "mint", "pop")):
        return "debian"
    if any(name in blob for name in ("fedora", "rhel", "centos", "rocky", "alma")):
        return "fedora"
    if "suse" in blob:
        return "suse"
    return ""


# ------------------------------------------------------------
# Passwords are remembered for this session only, keyed by the
# archive file. They are not written to settings.
# ------------------------------------------------------------
def _archiveKey(archive_file):
    return os.path.normcase(os.path.normpath(archive_file))


def getArchivePassword(archive_file):
    if not archive_file:
        return ""
    return _PASSWORDS.get(_archiveKey(archive_file), "")


def setArchivePassword(archive_file, password):
    """Remember a password and drop any listing cached without it."""
    if not archive_file:
        return
    _PASSWORDS[_archiveKey(archive_file)] = password or ""
    dropArchiveListing(archive_file)


def dropArchiveListing(archive_file):
    key = _archiveKey(archive_file)
    for cached in list(_LISTING_CACHE):
        if cached and cached[0] == key:
            _LISTING_CACHE.pop(cached, None)


# ------------------------------------------------------------
# Function: passwordArg
# Purpose: -pPASSWORD, or -p- so 7-Zip never waits for a prompt.
# ------------------------------------------------------------
def passwordArg(password):
    if password:
        return f"-p{password}"
    return "-p-"


# ------------------------------------------------------------
# Function: parseProgressPercent
# Purpose: Read a "-bsp1" progress line. Returns 0..100, or None.
# ------------------------------------------------------------
def parseProgressPercent(line):
    if not line:
        return None
    match = _PERCENT_RE.search(line)
    if not match:
        return None
    return min(100, int(match.group(1)))


# ------------------------------------------------------------
# Function: isPasswordError
# Purpose: True when 7-Zip rejected the archive for a password.
# ------------------------------------------------------------
def isPasswordError(text):
    low = (text or "").lower()
    if "wrong password" in low:
        return True
    if "encrypted archive" in low:
        return True
    if "cannot open encrypted" in low or "can not open encrypted" in low:
        return True
    return False


def _short7zError(output):
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.lower().startswith("error"):
            return line[:400]
    if lines:
        return lines[-1][:400]
    return ""


# ------------------------------------------------------------
# Function: parseSltRecords
# Purpose: Split `7z l -slt` output into dicts, one per block.
# ------------------------------------------------------------
def parseSltRecords(text):
    records = []
    current = {}
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        current[key.strip()] = value.strip()
    if current:
        records.append(current)
    return records


# ------------------------------------------------------------
# Class: ArchiveNode
# Purpose: One file or folder in the cached archive tree.
# ------------------------------------------------------------
class ArchiveNode:
    def __init__(self, name, is_dir):
        self.name = name
        self.is_dir = is_dir
        self.size = 0
        self.mod_time = 0.0
        self.encrypted = False
        self.member = ""
        self.children = {}


def _parseModified(value):
    text = (value or "").strip()
    if not text:
        return 0.0
    main = text.split(".", 1)[0].strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(main, pattern).timestamp()
        except ValueError:
            continue
    return 0.0


def _memberParts(raw_path):
    text = (raw_path or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or (len(text) > 2 and text[1] == ":"):
        return []
    parts = [part for part in text.split("/") if part and part != "."]
    if not parts or ".." in parts:
        return []
    return parts


# ------------------------------------------------------------
# Function: buildArchiveTree
# Purpose: Turn -slt records into a tree. Folders that 7-Zip
#          never lists on their own are created along the way.
#          Records without Folder = + or - are the archive itself.
# ------------------------------------------------------------
def _recordIsDir(record):
    """7-Zip omits Folder for some formats and uses Attributes = D instead."""
    folder_flag = (record.get("Folder") or "").strip()
    if folder_flag == "+":
        return True
    if folder_flag == "-":
        return False
    return (record.get("Attributes") or "").strip().startswith("D")


def _recordIsMember(record):
    folder_flag = (record.get("Folder") or "").strip()
    if folder_flag in ("+", "-"):
        return True
    # The archive header has Type and Physical Size, not a member Size.
    return "Size" in record and bool((record.get("Path") or "").strip())


def buildArchiveTree(records):
    root = ArchiveNode("", True)
    for record in records or []:
        if not _recordIsMember(record):
            continue
        parts = _memberParts(record.get("Path"))
        if not parts:
            continue
        is_dir = _recordIsDir(record)
        node = root
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            child = node.children.get(part)
            if child is None:
                child = ArchiveNode(part, True if not last else is_dir)
                child.member = "/".join(parts[: index + 1])
                node.children[part] = child
            if not last or is_dir:
                child.is_dir = True
            node = child
        if not is_dir:
            node.is_dir = False
            try:
                node.size = int(record.get("Size") or 0)
            except (TypeError, ValueError):
                node.size = 0
        node.mod_time = _parseModified(record.get("Modified"))
        node.encrypted = (record.get("Encrypted") or "").strip() == "+"
        node.member = "/".join(parts)
    return root


def _findNode(root, member):
    node = root
    text = (member or "").replace("\\", "/").strip("/")
    if not text:
        return node
    for part in text.split("/"):
        if not part:
            continue
        child = node.children.get(part)
        if child is None:
            return None
        node = child
    return node


def _rememberListing(key, tree):
    if key in _LISTING_CACHE:
        _LISTING_CACHE.pop(key, None)
    _LISTING_CACHE[key] = tree
    while len(_LISTING_CACHE) > _LISTING_CACHE_MAX:
        oldest = next(iter(_LISTING_CACHE))
        _LISTING_CACHE.pop(oldest, None)


# ------------------------------------------------------------
# Command lines. One list, no shell, so names with spaces are safe.
# ------------------------------------------------------------
def buildListArgs(archive_file, password=""):
    return [
        "l",
        "-slt",
        "-y",
        "-sccUTF-8",
        passwordArg(password),
        "--",
        archive_file,
    ]


def buildExtractArgs(archive_file, dest_dir, members=None, password=""):
    args = [
        "x",
        "-y",
        "-bsp1",
        "-sccUTF-8",
        passwordArg(password),
        f"-o{dest_dir}",
        "--",
        archive_file,
    ]
    if members:
        args.extend(members)
    return args


def buildCompressArgs(archive_out, names, fmt_key, level_key, password=""):
    spec = COMPRESS_FORMATS.get(fmt_key) or COMPRESS_FORMATS["zip"]
    level = COMPRESSION_LEVELS.get(level_key) or COMPRESSION_LEVELS["normal"]
    args = [
        "a",
        "-y",
        "-bsp1",
        "-sccUTF-8",
        f"-t{spec['type']}",
        f"-mx={level['mx']}",
    ]
    if password and spec.get("password"):
        args.append(passwordArg(password))
        if fmt_key == "7z":
            args.append("-mhe=on")
    args.extend(["--", archive_out])
    args.extend(names)
    return args


def _popenKwargs():
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flag:
            return {"creationflags": flag}
    return {}


def spawn7z(args, cwd=None, stdin=None, stdout=None, stderr=None):
    """Start 7-Zip. Raises ArchiveToolError when it is not installed."""
    exe = find7zExecutable()
    if not exe:
        raise ArchiveToolError(missing7zHint())
    try:
        return subprocess.Popen(
            [exe, *args],
            cwd=cwd or None,
            stdin=stdin,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=stderr if stderr is not None else subprocess.STDOUT,
            **_popenKwargs(),
        )
    except OSError as exc:
        raise ArchiveToolError(str(exc)) from exc


def popen7z(args, cwd=None):
    """Start 7-Zip with stdout and stderr merged, for a single process."""
    return spawn7z(args, cwd=cwd)


def _killProcess(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ------------------------------------------------------------
# Function: readProcess
# Purpose: Collect stdout from a running 7-Zip process.
#          Progress lines use carriage returns, so this splits
#          on either line ending. cancel_check() kills the process.
# Output: (exit_code, output, cancelled).
# ------------------------------------------------------------
def readProcess(proc, on_line=None, cancel_check=None):
    lines = []
    line_queue = queue.Queue()

    def _reader():
        buf = ""
        try:
            while True:
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                parts = re.split(r"[\r\n]+", buf)
                buf = parts.pop() if parts else ""
                for part in parts:
                    text = part.strip()
                    if text:
                        line_queue.put(text)
        finally:
            tail = buf.strip()
            if tail:
                line_queue.put(tail)
            line_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    cancelled = False
    while True:
        if cancel_check is not None and cancel_check():
            cancelled = True
            _killProcess(proc)
            break
        try:
            item = line_queue.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None and not reader.is_alive():
                break
            continue
        if item is None:
            break
        lines.append(item)
        if on_line is not None:
            on_line(item)

    if not cancelled:
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _killProcess(proc)
            code = proc.poll()
    else:
        code = proc.poll()
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except OSError:
            pass
    return code, "\n".join(lines), cancelled


# ------------------------------------------------------------
# Function: stream7z
# Purpose: Run 7-Zip and report each output line.
#          Returns (exit_code, output, cancelled).
#          exit_code is None when 7-Zip could not be started;
#          the message is then in output.
# ------------------------------------------------------------
def stream7z(args, cwd=None, on_line=None, cancel_check=None):
    try:
        proc = popen7z(args, cwd=cwd)
    except ArchiveToolError as exc:
        return None, str(exc), False
    return readProcess(proc, on_line=on_line, cancel_check=cancel_check)


def _listWrappedTar(archive_file, password):
    """List the tar stored inside .tar.gz, .tar.xz, and the same family.

    7-Zip's own `l` command stops at the outer gzip/xz member.
    """
    exe = find7zExecutable()
    if not exe:
        return None, missing7zHint()
    first = None
    try:
        first = subprocess.Popen(
            [
                exe, "x", "-so", "-bso0", "-y", "-sccUTF-8",
                passwordArg(password), "--", archive_file,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_popenKwargs(),
        )
        second = subprocess.Popen(
            [exe, "l", "-ttar", "-si", "-slt", "-y", "-sccUTF-8"],
            stdin=first.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **_popenKwargs(),
        )
    except OSError as exc:
        _killProcess(first)
        return None, str(exc)
    if first.stdout is not None:
        first.stdout.close()
    try:
        stdout, _stderr = second.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        _killProcess(second)
        _killProcess(first)
        return 1, "7-Zip timed out."
    try:
        first.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _killProcess(first)
    if first.stderr is not None:
        try:
            first.stderr.close()
        except OSError:
            pass
    text = (stdout or b"").decode("utf-8", errors="replace")
    if second.returncode not in (0, None):
        return second.returncode, text
    return 0, text


def run7z(args, cwd=None, timeout=120):
    """Run 7-Zip to completion. Returns (code, output). code is None on launch failure."""
    try:
        proc = popen7z(args, cwd=cwd)
    except ArchiveToolError as exc:
        return None, str(exc)
    try:
        stdout, _stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _killProcess(proc)
        return 1, "7-Zip timed out."
    text = (stdout or b"").decode("utf-8", errors="replace")
    return proc.returncode, text


# ------------------------------------------------------------
# Function: listArchive
# Purpose: Cached tree for one archive file.
#          The cache key includes mtime, size, and password, so
#          browsing folders inside the archive does not rerun 7z.
# Output: (ArchiveNode or None, error). error is "" on success.
# ------------------------------------------------------------
def listArchive(archive_file, password="", cancel_check=None):
    archive_file = os.path.normpath(archive_file)
    try:
        st = os.stat(archive_file)
    except OSError as exc:
        return None, exc.strerror or str(exc)

    used_password = password if password else getArchivePassword(archive_file)
    stamp = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    key = (_archiveKey(archive_file), stamp, st.st_size, used_password)
    cached = _LISTING_CACHE.get(key)
    if cached is not None:
        return cached, ""
    if cancel_check is not None and cancel_check():
        return None, ""

    if archiveExtension(archive_file) in WRAPPED_TAR_EXTENSIONS:
        code, output = _listWrappedTar(archive_file, used_password)
    else:
        code, output = run7z(buildListArgs(archive_file, used_password))
    if cancel_check is not None and cancel_check():
        return None, ""
    if code is None:
        return None, output or missing7zHint()
    if code != 0:
        return None, _short7zError(output) or f"7-Zip failed (exit {code})."
    tree = buildArchiveTree(parseSltRecords(output))
    _rememberListing(key, tree)
    return tree, ""


# ------------------------------------------------------------
# Function: listArchiveFolder
# Purpose: One level of an archive, in the same shape as
#          listFolderEntries. Extra keys: in_archive, archive_path,
#          member, encrypted.
# ------------------------------------------------------------
def listArchiveFolder(path, show_hidden, cancel_check=None, password=""):
    split = splitArchivePath(path)
    if split is None:
        return [], "Not an archive."
    archive_file, inner = split
    tree, error = listArchive(archive_file, password=password, cancel_check=cancel_check)
    if error:
        return [], error
    if tree is None:
        return [], ""
    node = _findNode(tree, inner)
    if node is None or not node.is_dir:
        return [], "Folder not found in the archive."

    from file_panel import getFileTypeDescription

    entries = []
    for name, child in node.children.items():
        if cancel_check is not None and cancel_check():
            break
        if not show_hidden and name.startswith("."):
            continue
        member = child.member or (f"{inner}/{name}" if inner else name)
        full_path = os.path.join(archive_file, *member.split("/"))
        entries.append({
            "name": name,
            "size": -1 if child.is_dir else child.size,
            "type": getFileTypeDescription(name, child.is_dir),
            "mod_time": child.mod_time,
            "is_dir": child.is_dir,
            "full_path": full_path,
            "in_archive": True,
            "archive_path": archive_file,
            "member": member,
            "encrypted": child.encrypted,
        })
    return entries, ""


def memberSize(archive_file, member, password=""):
    """Byte size of one member, or None when it is missing."""
    tree, error = listArchive(archive_file, password=password)
    if error or tree is None:
        return None, error
    node = _findNode(tree, member)
    if node is None or node.is_dir:
        return None, "File not found in the archive."
    return node.size, ""


# ------------------------------------------------------------
# Temp cache for F3, quick view, and "open this member".
# Cleared when the window closes.
# ------------------------------------------------------------
def archiveCacheDir():
    path = os.path.join(tempfile.gettempdir(), "tcc-archive-cache")
    os.makedirs(path, exist_ok=True)
    return path


def _cacheFolder(archive_file, member, password):
    try:
        st = os.stat(archive_file)
        stamp = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
        size = st.st_size
    except OSError:
        stamp = 0
        size = 0
    token = f"{_archiveKey(archive_file)}|{stamp}|{size}|{member}|{password}"
    digest = hashlib.sha1(token.encode("utf-8", errors="replace")).hexdigest()[:20]
    return os.path.join(archiveCacheDir(), digest)


def cachedMemberPath(archive_file, member, password=""):
    member = (member or "").replace("\\", "/").strip("/")
    folder = _cacheFolder(archive_file, member, password)
    return os.path.join(folder, *member.split("/")) if member else folder


# ------------------------------------------------------------
# Function: extractToCache
# Purpose: Extract one member into the temp cache.
#          max_bytes refuses large previews before 7-Zip runs.
# Output: (path, error). error is "" on success.
# ------------------------------------------------------------
def extractToCache(archive_file, member, password="", max_bytes=None):
    archive_file = os.path.normpath(archive_file)
    member = (member or "").replace("\\", "/").strip("/")
    if not member:
        return "", "Nothing to extract."
    used_password = password if password else getArchivePassword(archive_file)
    if max_bytes is not None:
        size, error = memberSize(archive_file, member, used_password)
        if error:
            return "", error
        if size is not None and size > max_bytes:
            return "", (
                "This file is too large to preview from the archive. "
                "Extract it first."
            )

    out_path = cachedMemberPath(archive_file, member, used_password)
    if os.path.isfile(out_path):
        return out_path, ""

    dest_dir = _cacheFolder(archive_file, member, used_password)
    os.makedirs(dest_dir, exist_ok=True)
    code, output = run7z(
        buildExtractArgs(archive_file, dest_dir, members=[member], password=used_password)
    )
    if code is None:
        return "", output or missing7zHint()
    if os.path.isfile(out_path):
        return out_path, ""
    if code != 0:
        return "", _short7zError(output) or f"7-Zip failed (exit {code})."
    return "", "Could not extract the file."


# ------------------------------------------------------------
# Function: prepareViewPath
# Purpose: Path the viewer can open. Archive members are extracted
#          into the temp cache, up to ARCHIVE_PREVIEW_MAX_BYTES.
# Output: (path, error).
# ------------------------------------------------------------
def prepareViewPath(path):
    split = splitArchivePath(path)
    if not split or not split[1]:
        return path, ""
    archive_file, member = split
    return extractToCache(
        archive_file,
        member,
        max_bytes=ARCHIVE_PREVIEW_MAX_BYTES,
    )


def clearArchiveCache():
    """Delete extracted preview files. Called when the window closes."""
    cache = os.path.join(tempfile.gettempdir(), "tcc-archive-cache")
    shutil.rmtree(cache, ignore_errors=True)


def clearListingCache():
    """Drop parsed archive trees. Used by tests."""
    _LISTING_CACHE.clear()
