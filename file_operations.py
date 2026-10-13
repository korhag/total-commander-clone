"""
Total Commander Clone - File Operations
Provides threaded copy, move, and delete operations with
progress dialogs, conflict resolution (overwrite/cancel/keep both/skip),
and proper error handling.
"""

import errno
import os
import shutil
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QMessageBox, QApplication, QCheckBox, QGridLayout,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition

from folder_stats import FolderSizeWorker, folderTreeStats


# Conflict resolution choices (used between worker and main thread)
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_CANCEL = "cancel"
CONFLICT_KEEP_BOTH = "keep_both"
CONFLICT_SKIP = "skip"
CONFLICT_OVERWRITE_IF_SAME = "overwrite_if_same"
CONFLICT_SKIP_IF_SAME = "skip_if_same"

# Sentinel returned by _askConflict when the user skips this item.
_SKIP_ITEM = object()


class UserAbortError(Exception):
    """Raised when the user cancels the file operation from a conflict dialog."""


def _resolveConflictPath(dest_path):
    """Return a conflict-free path by appending (1), (2), etc."""
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    counter = 1
    while os.path.exists(dest_path):
        dest_path = f"{base} ({counter}){ext}"
        counter += 1
    return dest_path


# Chunk size for byte-level copy progress (1 MiB)
_COPY_CHUNK_SIZE = 1024 * 1024


def _formatByteSize(num_bytes):
    """Human-readable size for progress labels."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    size = float(num_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024.0
        if size < 1024.0:
            return f"{size:.1f} {unit}"
    return f"{size / 1024.0:.1f} PB"


def _pathByteSize(path):
    """Total bytes for a file or directory tree."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _sameVolume(path_a, path_b):
    """True when paths are on the same drive/volume (fast rename move)."""
    return (
        os.path.splitdrive(os.path.abspath(path_a))[0].lower()
        == os.path.splitdrive(os.path.abspath(path_b))[0].lower()
    )


# Windows ERROR_NOT_SAME_DEVICE: rename across mount points / junctions.
_WIN_ERROR_NOT_SAME_DEVICE = 17


def _tryRename(source, dest_path):
    """
    Rename source to dest_path. Returns False (nothing changed) when the OS
    reports the paths are on different devices; other errors are raised.
    """
    try:
        os.rename(source, dest_path)
        return True
    except OSError as exc:
        if exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == _WIN_ERROR_NOT_SAME_DEVICE:
            return False
        raise


def _destRelation(source, dest_path):
    """
    How dest_path sits relative to source.

    Returns "same" when they are the same path, "inside" when source is a
    folder and dest_path is strictly under it, otherwise None.
    """
    def _key(path):
        try:
            return os.path.normcase(os.path.normpath(os.path.abspath(path)))
        except (OSError, ValueError):
            return ""

    src = _key(source)
    dest = _key(dest_path)
    if not src or not dest:
        return None
    if src == dest:
        return "same"
    try:
        source_is_dir = os.path.isdir(source)
    except OSError:
        source_is_dir = False
    if source_is_dir and dest.startswith(src.rstrip("\\/") + os.sep):
        return "inside"
    return None


def _winLongPath(path):
    """Windows extended-length path prefix (\\\\?\\ / \\\\?\\UNC\\)."""
    if os.name != "nt" or not path:
        return path
    if path.startswith("\\\\?\\"):
        return path
    try:
        abs_path = os.path.abspath(path)
    except (OSError, ValueError):
        abs_path = path
    if abs_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abs_path[2:]
    return "\\\\?\\" + abs_path


def _displayPath(path):
    """Human-readable path without Windows \\\\?\\ prefix."""
    if not path:
        return ""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _pathCandidates(path):
    """Ordered path forms to try for existence / stat."""
    if not path or not str(path).strip():
        return []
    raw = str(path).strip()
    out = []
    try:
        normalized = os.path.normpath(os.path.abspath(raw))
    except (OSError, ValueError):
        normalized = os.path.normpath(raw)
    for c in (raw, normalized):
        if c and c not in out:
            out.append(c)
    if os.name == "nt" and normalized:
        long_p = _winLongPath(normalized)
        if long_p and long_p not in out:
            out.append(long_p)
    return out


def _normalizeFsPath(path):
    """
    Return a filesystem path that exists when possible (normpath/abspath,
    Windows long-path fallback). Otherwise the best normalized form.
    """
    candidates = _pathCandidates(path)
    if not candidates:
        return ""
    for c in candidates:
        try:
            if os.path.lexists(c) or os.path.exists(c):
                return c
        except OSError:
            continue
    return candidates[1] if len(candidates) > 1 else candidates[0]


def _conflictSideInfo(path):
    """Quick sync facts for one side of a conflict (robust path lookup)."""
    raw = (path or "").strip() if path else ""
    info = {
        "path": raw,
        "resolved_path": raw,
        "exists": False,
        "is_dir": False,
        "size": -1,
        "mod_time": None,
        "type_label": "Not found",
        "error": None,
    }
    if not raw:
        info["error"] = "No path provided."
        return info

    candidates = _pathCandidates(raw)
    last_err = None
    for c in candidates:
        try:
            if not (os.path.lexists(c) or os.path.exists(c)):
                continue
            info["resolved_path"] = c
            info["path"] = _displayPath(c)
            info["exists"] = True
            try:
                st = os.stat(c)
                info["is_dir"] = os.path.isdir(c)
                info["mod_time"] = st.st_mtime
                info["size"] = -1 if info["is_dir"] else st.st_size
                info["type_label"] = "Folder" if info["is_dir"] else "File"
                info["error"] = None
                return info
            except OSError as exc:
                info["type_label"] = "Unreadable"
                info["error"] = str(exc)
                return info
        except OSError as exc:
            last_err = exc
            continue

    display = _displayPath(candidates[-1] if candidates else raw)
    info["path"] = display
    info["resolved_path"] = candidates[-1] if candidates else raw
    if last_err:
        info["error"] = str(last_err)
    elif len(display) >= 240:
        info["error"] = "Path not found (may exceed Windows path length limits)."
    else:
        info["error"] = "Path not found on disk."
    return info


def _conflictSizeFileKey(path):
    """
    Return (total_bytes, file_count) for match policy, or None on failure.
    Files: (size, 1). Folders: tree totals from folderTreeStats.
    """
    info = _conflictSideInfo(path)
    if not info["exists"]:
        return None
    resolved = info["resolved_path"] or info["path"]
    if info["is_dir"]:
        stats = folderTreeStats(resolved)
        if stats is None:
            return None
        total_bytes, file_count, _dir_count = stats
        return total_bytes, file_count
    if info["size"] < 0:
        return None
    return info["size"], 1


def _conflictSidesMatch(source_path, dest_path):
    """True when size and file count match (folders ignore subfolder count)."""
    left = _conflictSizeFileKey(source_path)
    right = _conflictSizeFileKey(dest_path)
    if left is None or right is None:
        return False
    return left == right


def _formatConflictTime(ts):
    if ts is None or ts <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return "—"


# ============================================================
# Class: ConflictDialog
# Purpose: Modal dialog when an item already exists at destination.
#          Side-by-side Source vs Destination context; Overwrite,
#          Keep both, Skip, same-size bulk policies, or Cancel.
# ============================================================
class ConflictDialog(QDialog):

    def __init__(self, source_path, dest_path, operation_name, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._choice = None
        self._apply_to_all = False
        self._workers = []
        self._source_path = source_path or ""
        self._dest_path = dest_path or ""

        src = _conflictSideInfo(self._source_path)
        dst = _conflictSideInfo(self._dest_path)
        self._src_info = src
        self._dst_info = dst
        either_dir = src["is_dir"] or dst["is_dir"]
        self.setWindowTitle(
            "Item Already Exists" if either_dir else "File Already Exists"
        )
        self.resize(820, 460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        name = os.path.basename(dst["path"] or self._dest_path) or os.path.basename(
            src["path"] or self._source_path
        )
        op = (operation_name or "Copy").strip() or "Copy"
        intro = QLabel(
            f"{op}: \"{name}\" already exists at the destination.\n"
            "Compare source and destination below, then choose what to do."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)

        grid.addWidget(self._boldLabel("Source (incoming)"), 0, 1)
        grid.addWidget(self._boldLabel("Destination (existing)"), 0, 2)

        self._src_labels = {}
        self._dst_labels = {}
        fields = [
            ("Path", "path"),
            ("Type", "type"),
            ("Modified", "mod"),
            ("Size", "size"),
            ("Contents", "contents"),
        ]
        for row, (title, key) in enumerate(fields, start=1):
            grid.addWidget(QLabel(title), row, 0, Qt.AlignTop)
            left = QLabel()
            left.setWordWrap(True)
            left.setTextInteractionFlags(Qt.TextSelectableByMouse)
            right = QLabel()
            right.setWordWrap(True)
            right.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(left, row, 1, Qt.AlignTop)
            grid.addWidget(right, row, 2, Qt.AlignTop)
            self._src_labels[key] = left
            self._dst_labels[key] = right

        layout.addLayout(grid)

        self._diff_label = QLabel()
        self._diff_label.setWordWrap(True)
        layout.addWidget(self._diff_label)

        self._chk_apply_all = QCheckBox("Do this for all remaining conflicts")
        layout.addWidget(self._chk_apply_all)

        match_row = QHBoxLayout()
        self._btn_overwrite_if_same = QPushButton("Overwrite all matching size+files")
        self._btn_overwrite_if_same.setToolTip(
            "If this conflict matches on total size and file count, overwrite it "
            "and auto-overwrite later conflicts that also match. Non-matching "
            "conflicts still prompt."
        )
        self._btn_overwrite_if_same.clicked.connect(self._onOverwriteIfSame)
        match_row.addWidget(self._btn_overwrite_if_same)

        self._btn_skip_if_same = QPushButton("Skip all matching size+files")
        self._btn_skip_if_same.setToolTip(
            "If this conflict matches on total size and file count, skip it "
            "and auto-skip later conflicts that also match. Non-matching "
            "conflicts still prompt."
        )
        self._btn_skip_if_same.clicked.connect(self._onSkipIfSame)
        match_row.addWidget(self._btn_skip_if_same)
        match_row.addStretch()
        layout.addLayout(match_row)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_overwrite = QPushButton("Overwrite")
        self._btn_overwrite.setToolTip(
            "Replace the destination with the source."
        )
        self._btn_overwrite.clicked.connect(self._onOverwrite)
        btn_layout.addWidget(self._btn_overwrite)

        self._btn_keep_both = QPushButton("Keep both")
        self._btn_keep_both.setToolTip(
            "Keep the existing item and write the source under a new name."
        )
        self._btn_keep_both.clicked.connect(self._onKeepBoth)
        btn_layout.addWidget(self._btn_keep_both)

        self._btn_skip = QPushButton("Skip")
        self._btn_skip.setToolTip(
            "Leave the destination unchanged and continue with the next item."
        )
        self._btn_skip.clicked.connect(self._onSkip)
        btn_layout.addWidget(self._btn_skip)

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setToolTip("Abort the entire copy/move operation.")
        self._btn_cancel.clicked.connect(self._onCancel)
        btn_layout.addWidget(self._btn_cancel)

        layout.addLayout(btn_layout)

        self._fillSides(src, dst)
        self._startFolderWorkers(src, dst)
        self._updateMatchButtons()

    def _boldLabel(self, text):
        lbl = QLabel(f"<b>{text}</b>")
        return lbl

    def _fillSides(self, src, dst):
        self._src_labels["path"].setText(src["path"] or "—")
        self._dst_labels["path"].setText(dst["path"] or "—")
        self._src_labels["type"].setText(src["type_label"])
        self._dst_labels["type"].setText(dst["type_label"])
        self._src_labels["mod"].setText(_formatConflictTime(src.get("mod_time")))
        self._dst_labels["mod"].setText(_formatConflictTime(dst.get("mod_time")))

        if src["exists"] and not src["is_dir"]:
            self._src_labels["size"].setText(
                f"{_formatByteSize(src['size'])}  ({src['size']:,} bytes)"
            )
            self._src_labels["contents"].setText("—")
        elif src["exists"] and src["is_dir"]:
            self._src_labels["size"].setText("Calculating…")
            self._src_labels["contents"].setText("Calculating…")
        else:
            self._src_labels["size"].setText("—")
            self._src_labels["contents"].setText("—")

        if dst["exists"] and not dst["is_dir"]:
            self._dst_labels["size"].setText(
                f"{_formatByteSize(dst['size'])}  ({dst['size']:,} bytes)"
            )
            self._dst_labels["contents"].setText("—")
        elif dst["exists"] and dst["is_dir"]:
            self._dst_labels["size"].setText("Calculating…")
            self._dst_labels["contents"].setText("Calculating…")
        else:
            self._dst_labels["size"].setText("—")
            self._dst_labels["contents"].setText("—")

        diffs = []
        if src.get("error") and not src["exists"]:
            diffs.append(f"Source: {src['error']}")
        if dst.get("error") and not dst["exists"]:
            diffs.append(f"Destination: {dst['error']}")
        if src["exists"] and dst["exists"]:
            if src["is_dir"] != dst["is_dir"]:
                diffs.append("Types differ (file vs folder).")
            if (
                not src["is_dir"]
                and not dst["is_dir"]
                and src["size"] != dst["size"]
            ):
                diffs.append(
                    f"File sizes differ: {_formatByteSize(src['size'])} vs "
                    f"{_formatByteSize(dst['size'])}."
                )
            if src.get("mod_time") and dst.get("mod_time"):
                if abs(src["mod_time"] - dst["mod_time"]) >= 1.0:
                    diffs.append("Modified times differ.")
        self._pending_folder = (
            src["exists"]
            and dst["exists"]
            and (src["is_dir"] or dst["is_dir"])
        )
        self._src_stats = None if (src["exists"] and src["is_dir"]) else True
        self._dst_stats = None if (dst["exists"] and dst["is_dir"]) else True
        if diffs:
            self._diff_label.setText("Differences: " + " ".join(diffs))
        elif self._pending_folder:
            self._diff_label.setText("Comparing folder trees…")
        elif not src["exists"] or not dst["exists"]:
            self._diff_label.setText(
                "Cannot fully compare — one side was not found on disk."
            )
        else:
            self._diff_label.setText(
                "No obvious size/date differences in the fields above "
                "(names still collide at the destination)."
            )

    def _startFolderWorkers(self, src, dst):
        if src["exists"] and src["is_dir"]:
            w = FolderSizeWorker(src["resolved_path"] or src["path"], self)
            w.finishedOk.connect(
                lambda b, f, d: self._onStats("src", b, f, d)
            )
            w.failed.connect(lambda msg: self._onStatsFail("src", msg))
            self._workers.append(w)
            w.start()
        if dst["exists"] and dst["is_dir"]:
            w = FolderSizeWorker(dst["resolved_path"] or dst["path"], self)
            w.finishedOk.connect(
                lambda b, f, d: self._onStats("dst", b, f, d)
            )
            w.failed.connect(lambda msg: self._onStatsFail("dst", msg))
            self._workers.append(w)
            w.start()

    def _onStats(self, side, total_bytes, file_count, dir_count):
        labels = self._src_labels if side == "src" else self._dst_labels
        labels["size"].setText(
            f"{_formatByteSize(total_bytes)}  ({total_bytes:,} bytes)"
        )
        labels["contents"].setText(
            f"{file_count:,} file(s), {dir_count:,} subfolder(s)"
        )
        stats = (total_bytes, file_count, dir_count)
        if side == "src":
            self._src_stats = stats
        else:
            self._dst_stats = stats
        self._updateFolderDiff()
        self._updateMatchButtons()

    def _onStatsFail(self, side, msg):
        labels = self._src_labels if side == "src" else self._dst_labels
        labels["size"].setText("—")
        labels["contents"].setText(msg or "Failed")
        if side == "src":
            self._src_stats = False
        else:
            self._dst_stats = False
        self._updateFolderDiff()
        self._updateMatchButtons()

    def _updateFolderDiff(self):
        if not self._pending_folder:
            return
        if self._src_stats is None or self._dst_stats is None:
            return
        if self._src_stats is False or self._dst_stats is False:
            self._diff_label.setText(
                "Could not fully compare folder tree sizes on one or both sides."
            )
            return
        if self._src_stats is True or self._dst_stats is True:
            return
        sb, sf, sd = self._src_stats
        db, df, dd = self._dst_stats
        parts = []
        if sb != db:
            parts.append(
                f"Total size differs: {_formatByteSize(sb)} vs {_formatByteSize(db)}."
            )
        if sf != df:
            parts.append(f"File count differs: {sf:,} vs {df:,}.")
        if sd != dd:
            parts.append(f"Subfolder count differs: {sd:,} vs {dd:,}.")
        if parts:
            self._diff_label.setText("Differences: " + " ".join(parts))
        else:
            self._diff_label.setText(
                "Folder trees match in total size and file count "
                "(paths still collide)."
            )

    def _currentMatchState(self):
        """
        Return True / False / None (still calculating) for size+file match.
        """
        src = self._src_info
        dst = self._dst_info
        if not src["exists"] or not dst["exists"]:
            return False
        if src["is_dir"] != dst["is_dir"]:
            return False
        if not src["is_dir"]:
            return src["size"] >= 0 and src["size"] == dst["size"]
        if self._src_stats is None or self._dst_stats is None:
            return None
        if (
            self._src_stats is False
            or self._dst_stats is False
            or self._src_stats is True
            or self._dst_stats is True
        ):
            return False
        sb, sf, _sd = self._src_stats
        db, df, _dd = self._dst_stats
        return sb == db and sf == df

    def _updateMatchButtons(self):
        state = self._currentMatchState()
        ready = state is not None
        self._btn_overwrite_if_same.setEnabled(ready)
        self._btn_skip_if_same.setEnabled(ready)

    def _tryFinishIfSame(self, choice):
        state = self._currentMatchState()
        if state is None:
            QMessageBox.information(
                self,
                "Still calculating",
                "Folder sizes are still being calculated. Please wait a moment.",
            )
            return
        if not state:
            QMessageBox.information(
                self,
                "Not a match",
                "This conflict does not match on total size and file count.\n"
                "The bulk policy was not applied. Use Overwrite, Skip, or "
                "Keep both for this item instead.",
            )
            return
        self._finish(choice)

    def _finish(self, choice):
        self._choice = choice
        self._apply_to_all = self._chk_apply_all.isChecked()
        self._stopWorkers()
        self.accept()

    def _onOverwrite(self):
        self._finish(CONFLICT_OVERWRITE)

    def _onKeepBoth(self):
        self._finish(CONFLICT_KEEP_BOTH)

    def _onSkip(self):
        self._finish(CONFLICT_SKIP)

    def _onOverwriteIfSame(self):
        self._tryFinishIfSame(CONFLICT_OVERWRITE_IF_SAME)

    def _onSkipIfSame(self):
        self._tryFinishIfSame(CONFLICT_SKIP_IF_SAME)

    def _onCancel(self):
        self._finish(CONFLICT_CANCEL)

    def _stopWorkers(self):
        for w in self._workers:
            try:
                w.cancel()
                w.wait(1500)
            except Exception:
                pass
        self._workers = []

    def closeEvent(self, event):
        self._stopWorkers()
        super().closeEvent(event)

    def getChoice(self):
        """Returns (choice, apply_to_all)."""
        return self._choice, self._apply_to_all


# ============================================================
# Class: FileOperationWorker
# Purpose: QThread worker that performs copy/move/delete
#          operations in the background. For copy/move, when a
#          file already exists it signals the main thread to show
#          a conflict dialog and waits for the user's choice.
# ============================================================
class FileOperationWorker(QThread):

    progressChanged = pyqtSignal(int, str, str)
    operationFinished = pyqtSignal(bool, str)
    errorOccurred = pyqtSignal(str, str)
    conflictDetected = pyqtSignal(str, str, str)

    OPERATION_COPY = "copy"
    OPERATION_MOVE = "move"
    OPERATION_DELETE = "delete"

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, operation, file_paths, destination="", parent=None, relative_paths=None):
        super().__init__(parent)
        self._operation = operation
        self._file_paths = file_paths
        self._destination = destination
        self._relative_paths = list(relative_paths) if relative_paths else None
        self._cancelled = False
        self._errors = []
        self._conflict_mutex = QMutex()
        self._conflict_condition = QWaitCondition()
        self._conflict_choice = None
        self._conflict_new_dest = None
        self._apply_to_all_choice = None
        self._conflict_match_policy = None
        self._total_bytes = 0
        self._bytes_completed = 0

    # --------------------------------------------------------
    # Method: cancel
    # --------------------------------------------------------
    def cancel(self):
        self._conflict_mutex.lock()
        self._cancelled = True
        self._conflict_condition.wakeAll()
        self._conflict_mutex.unlock()

    # --------------------------------------------------------
    # Method: setConflictResponse
    # Purpose: Called from the main thread after user chooses.
    #          choice: OVERWRITE | CANCEL | KEEP_BOTH | SKIP |
    #                  OVERWRITE_IF_SAME | SKIP_IF_SAME
    #          new_dest: used when choice is KEEP_BOTH (can be None to auto-rename).
    # --------------------------------------------------------
    def setConflictResponse(self, choice, new_dest=None, apply_to_all=False):
        self._conflict_mutex.lock()
        if choice == CONFLICT_OVERWRITE_IF_SAME:
            self._conflict_match_policy = CONFLICT_OVERWRITE_IF_SAME
            self._conflict_choice = CONFLICT_OVERWRITE
            self._conflict_new_dest = None
        elif choice == CONFLICT_SKIP_IF_SAME:
            self._conflict_match_policy = CONFLICT_SKIP_IF_SAME
            self._conflict_choice = CONFLICT_SKIP
            self._conflict_new_dest = None
        else:
            self._conflict_choice = choice
            self._conflict_new_dest = new_dest
            if apply_to_all:
                self._apply_to_all_choice = choice
                self._conflict_match_policy = None
        self._conflict_condition.wakeOne()
        self._conflict_mutex.unlock()

    # --------------------------------------------------------
    # Method: run
    # --------------------------------------------------------
    def run(self):
        total = len(self._file_paths)
        if total == 0:
            self.operationFinished.emit(True, "No files to process.")
            return

        use_byte_progress = self._operation in (
            self.OPERATION_COPY,
            self.OPERATION_MOVE,
        )
        if use_byte_progress:
            self.progressChanged.emit(0, "", "Calculating size...")
            self._total_bytes = sum(_pathByteSize(p) for p in self._file_paths)
            self._bytes_completed = 0

        for i, source_path in enumerate(self._file_paths):
            if self._cancelled:
                self.operationFinished.emit(False, "Operation cancelled.")
                return

            file_name = os.path.basename(source_path)
            rel = None
            if self._relative_paths and i < len(self._relative_paths):
                rel = self._relative_paths[i]
            if rel:
                file_name = os.path.basename(rel.replace("/", os.sep)) or file_name
            if use_byte_progress:
                self._emitProgress(file_name, i, total, bytes_in_item=0)
            else:
                progress_pct = int((i / total) * 100)
                self._emitProgress(file_name, i, total, percent_override=progress_pct)

            try:
                if self._operation == self.OPERATION_COPY:
                    self._copyItem(
                        source_path, self._destination, i, total, relative_path=rel
                    )
                elif self._operation == self.OPERATION_MOVE:
                    self._moveItem(
                        source_path, self._destination, i, total, relative_path=rel
                    )
                elif self._operation == self.OPERATION_DELETE:
                    self._deleteItem(source_path)
                    self._emitProgress(file_name, i + 1, total, percent_override=int(((i + 1) / total) * 100))
            except UserAbortError:
                self.operationFinished.emit(False, "Operation cancelled.")
                return
            except Exception as e:
                error_msg = f"{file_name}: {str(e)}"
                self._errors.append(error_msg)
                self.errorOccurred.emit(file_name, str(e))

        if self._errors:
            error_summary = "\n".join(self._errors)
            self.operationFinished.emit(False, f"Completed with errors:\n{error_summary}")
        else:
            self._emitProgress("Done", total, total, percent_override=100)
            self.operationFinished.emit(True, f"Successfully processed {total} item(s).")

    # --------------------------------------------------------
    # Method: _askConflict
    # Purpose: Emit signal and block until main thread sets response.
    # Returns: dest path string, _SKIP_ITEM to leave dest alone, or
    #          raises UserAbortError on Cancel.
    # --------------------------------------------------------
    def _askConflict(self, source_path, dest_path, file_name):
        source_path = _normalizeFsPath(source_path) or source_path
        dest_path = _normalizeFsPath(dest_path) or dest_path

        if self._apply_to_all_choice is not None:
            choice = self._apply_to_all_choice
            if choice == CONFLICT_CANCEL:
                raise UserAbortError()
            if choice == CONFLICT_SKIP:
                return _SKIP_ITEM
            if choice == CONFLICT_OVERWRITE:
                return dest_path
            if choice == CONFLICT_KEEP_BOTH:
                return _resolveConflictPath(dest_path)
            return dest_path

        if self._conflict_match_policy:
            if _conflictSidesMatch(source_path, dest_path):
                if self._conflict_match_policy == CONFLICT_OVERWRITE_IF_SAME:
                    return dest_path
                if self._conflict_match_policy == CONFLICT_SKIP_IF_SAME:
                    return _SKIP_ITEM

        self._conflict_mutex.lock()
        self._conflict_choice = None
        self._conflict_mutex.unlock()
        self.conflictDetected.emit(source_path, dest_path, file_name)
        self._conflict_mutex.lock()
        while self._conflict_choice is None and not self._cancelled:
            self._conflict_condition.wait(self._conflict_mutex)
        choice = self._conflict_choice
        new_dest = self._conflict_new_dest
        self._conflict_choice = None
        self._conflict_new_dest = None
        self._conflict_mutex.unlock()

        if choice == CONFLICT_CANCEL or choice is None:
            raise UserAbortError()
        if choice == CONFLICT_SKIP:
            return _SKIP_ITEM
        if choice == CONFLICT_OVERWRITE:
            return dest_path
        if choice == CONFLICT_KEEP_BOTH:
            return new_dest if new_dest else _resolveConflictPath(dest_path)
        return dest_path
    # --------------------------------------------------------
    # Method: _emitProgress
    # Purpose: Emit percent, current name, and detail (items + bytes).
    # --------------------------------------------------------
    def _emitProgress(
        self,
        file_name,
        items_done,
        total_items,
        bytes_in_item=0,
        percent_override=None,
    ):
        if percent_override is not None:
            percent = percent_override
        elif self._total_bytes > 0:
            overall_bytes = min(
                self._bytes_completed + bytes_in_item,
                self._total_bytes,
            )
            percent = int(overall_bytes * 100 / self._total_bytes)
        elif total_items > 0:
            percent = int(items_done * 100 / total_items)
        else:
            percent = 0

        percent = max(0, min(100, percent))
        detail = f"{items_done} / {total_items} items"
        if self._total_bytes > 0:
            done_bytes = min(self._bytes_completed + bytes_in_item, self._total_bytes)
            detail += (
                f"  •  {_formatByteSize(done_bytes)} / {_formatByteSize(self._total_bytes)}"
            )
        self.progressChanged.emit(percent, file_name, detail)

    # --------------------------------------------------------
    # Method: _copyFileWithProgress
    # Purpose: Copy a single file in chunks with byte progress.
    # --------------------------------------------------------
    def _copyFileWithProgress(self, source, dest_path, display_name, item_index, total_items):
        item_size = 0
        try:
            item_size = os.path.getsize(source)
        except OSError:
            pass

        bytes_in_item = 0
        try:
            with open(source, "rb") as src_f, open(dest_path, "wb") as dst_f:
                while True:
                    if self._cancelled:
                        raise UserAbortError()
                    chunk = src_f.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    dst_f.write(chunk)
                    bytes_in_item += len(chunk)
                    self._emitProgress(display_name, item_index, total_items, bytes_in_item)
            shutil.copystat(source, dest_path)
        except Exception:
            self._removePartial(dest_path)
            raise

        self._bytes_completed += item_size

    # --------------------------------------------------------
    # Method: _copyDirectoryWithProgress
    # Purpose: Copy a directory tree file-by-file with byte progress.
    # --------------------------------------------------------
    def _copyDirectoryWithProgress(self, source, dest_path, item_index, total_items):
        root_name = os.path.basename(source.rstrip(os.sep)) or source
        for dir_root, dir_names, file_names in os.walk(source):
            if self._cancelled:
                raise UserAbortError()
            rel = os.path.relpath(dir_root, source)
            dest_dir = dest_path if rel == "." else os.path.join(dest_path, rel)
            os.makedirs(dest_dir, exist_ok=True)
            for dir_name in dir_names:
                os.makedirs(os.path.join(dest_dir, dir_name), exist_ok=True)
            for file_name in file_names:
                if self._cancelled:
                    raise UserAbortError()
                src_file = os.path.join(dir_root, file_name)
                dst_file = os.path.join(dest_dir, file_name)
                if rel == ".":
                    display = os.path.join(root_name, file_name) if file_name else root_name
                else:
                    display = os.path.join(root_name, rel, file_name)
                self._copyFileWithProgress(
                    src_file, dst_file, display, item_index, total_items
                )
        try:
            shutil.copystat(source, dest_path)
        except OSError:
            pass

    # --------------------------------------------------------
    # Method: _removePartial
    # Purpose: Remove incomplete destination on cancel/error.
    # --------------------------------------------------------
    def _removePartial(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError:
            pass

    # --------------------------------------------------------
    # Method: _finishItemProgress
    # Purpose: Mark top-level item bytes done after copy/move.
    # --------------------------------------------------------
    def _finishItemProgress(self, source, file_name, item_index, total_items):
        expected = sum(_pathByteSize(p) for p in self._file_paths[: item_index + 1])
        self._bytes_completed = min(expected, self._total_bytes)
        self._emitProgress(file_name, item_index + 1, total_items)

    # --------------------------------------------------------
    # Method: _destPathForItem
    # Purpose: Flat basename dest, or join(dest_dir, relative_path)
    #          when keeping folder structure. Creates parent dirs.
    # --------------------------------------------------------
    def _destPathForItem(self, source, dest_dir, relative_path=None):
        if relative_path:
            rel = relative_path.replace("/", os.sep).strip()
            parts = [p for p in rel.split(os.sep) if p and p != "."]
            if parts and ".." not in parts:
                dest_path = os.path.normpath(os.path.join(dest_dir, *parts))
                parent = os.path.dirname(dest_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                return dest_path, parts[-1]
        name = os.path.basename(source)
        return os.path.join(dest_dir, name), name

    # --------------------------------------------------------
    # Method: _copyItem
    # --------------------------------------------------------
    def _adjustDestination(self, source, dest_path, name, item_index, total_items):
        """
        Keep a copy/move from writing a path onto itself or into its own tree.
        Returns (dest_path, name), or None when a move has nothing to do.
        """
        relation = _destRelation(source, dest_path)
        if relation == "inside":
            raise OSError("Cannot copy/move a folder into itself.")
        if relation == "same" and self._operation == self.OPERATION_MOVE:
            self._finishItemProgress(source, name, item_index, total_items)
            return None
        if relation == "same":
            dest_path = _resolveConflictPath(dest_path)
            name = os.path.basename(dest_path)
        return dest_path, name

    def _copyDirectoryOrAbort(self, source, dest_path, item_index, total_items):
        """Copy a folder, and remove the partial destination if the user cancels."""
        try:
            os.makedirs(dest_path, exist_ok=True)
            self._copyDirectoryWithProgress(source, dest_path, item_index, total_items)
        except UserAbortError:
            self._removePartial(dest_path)
            raise

    # --------------------------------------------------------
    # Method: _writeWithBackup
    # Purpose: Run produce() to create dest_path. An existing
    #          dest_path is set aside first and only deleted after
    #          produce() succeeds, so a failed or cancelled
    #          overwrite restores the original destination.
    # --------------------------------------------------------
    def _writeWithBackup(self, dest_path, produce):
        backup = None
        if os.path.lexists(dest_path):
            backup = _resolveConflictPath(f"{dest_path}.tcc-old")
            os.rename(dest_path, backup)
        try:
            produce()
        except BaseException:
            if backup:
                self._removePartial(dest_path)
                os.rename(backup, dest_path)
            raise
        if backup:
            self._removePartial(backup)

    def _copyItem(self, source, dest_dir, item_index, total_items, relative_path=None):
        dest_path, name = self._destPathForItem(source, dest_dir, relative_path)
        adjusted = self._adjustDestination(source, dest_path, name, item_index, total_items)
        if adjusted is None:
            return
        dest_path, name = adjusted

        if os.path.exists(dest_path):
            resolved = self._askConflict(source, dest_path, name)
            if resolved is _SKIP_ITEM:
                self._finishItemProgress(source, name, item_index, total_items)
                return
            dest_path = resolved
            parent = os.path.dirname(dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        def produce():
            if os.path.isdir(source):
                self._copyDirectoryOrAbort(source, dest_path, item_index, total_items)
            else:
                self._copyFileWithProgress(source, dest_path, name, item_index, total_items)

        self._writeWithBackup(dest_path, produce)
        self._finishItemProgress(source, name, item_index, total_items)

    # --------------------------------------------------------
    # Method: _moveItem
    # --------------------------------------------------------
    def _moveItem(self, source, dest_dir, item_index, total_items, relative_path=None):
        dest_path, name = self._destPathForItem(source, dest_dir, relative_path)
        adjusted = self._adjustDestination(source, dest_path, name, item_index, total_items)
        if adjusted is None:
            return
        dest_path, name = adjusted

        if os.path.exists(dest_path):
            resolved = self._askConflict(source, dest_path, name)
            if resolved is _SKIP_ITEM:
                self._finishItemProgress(source, name, item_index, total_items)
                return
            dest_path = resolved
            parent = os.path.dirname(dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        copied = False

        def produce():
            nonlocal copied
            if _sameVolume(source, dest_path) and _tryRename(source, dest_path):
                return
            if os.path.isdir(source):
                self._copyDirectoryOrAbort(source, dest_path, item_index, total_items)
            else:
                self._copyFileWithProgress(source, dest_path, name, item_index, total_items)
            if self._cancelled:
                self._removePartial(dest_path)
                raise UserAbortError()
            copied = True

        self._writeWithBackup(dest_path, produce)
        if copied:
            self._removeMovedSource(source, dest_path)
        self._finishItemProgress(source, name, item_index, total_items)

    # --------------------------------------------------------
    # Method: _removeMovedSource
    # Purpose: Delete the original after a cross-volume move copy.
    #          A failure is reported as an error, never as success;
    #          the complete copy at dest_path is kept.
    # --------------------------------------------------------
    def _removeMovedSource(self, source, dest_path):
        try:
            if os.path.isdir(source):
                shutil.rmtree(source)
            else:
                os.remove(source)
        except OSError as exc:
            raise OSError(
                f"Copied to '{dest_path}' but could not remove the original: {exc}"
            ) from exc

    # --------------------------------------------------------
    # Method: _deleteItem
    # Purpose: Deletes a file or directory. Uses send2trash
    #          to move to the Recycle Bin when available.
    # --------------------------------------------------------
    def _deleteItem(self, path):
        try:
            from send2trash import send2trash
            send2trash(path)
        except ImportError:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

# ============================================================
# Class: FileOperationDialog
# Purpose: Modal progress dialog shown during long file
#          operations (copy, move, delete). Runs the worker
#          thread and reports progress.
# ============================================================
class FileOperationDialog(QDialog):

    # --------------------------------------------------------
    # Method: __init__
    # Input:  operation (str) - "copy", "move", or "delete"
    #         file_paths (list) - Source paths.
    #         destination (str) - Target directory (ignored for delete).
    #         parent - Parent widget.
    # --------------------------------------------------------
    def __init__(self, operation, file_paths, destination="", parent=None):
        super().__init__(parent)
        self._operation = operation
        self._file_paths = file_paths
        self._destination = destination
        self._result_success = False
        self._result_message = ""

        self._initUI()
        self._startOperation()

    # --------------------------------------------------------
    # Method: _initUI
    # --------------------------------------------------------
    def _initUI(self):
        op_titles = {
            "copy": "Copying Files",
            "move": "Moving Files",
            "delete": "Deleting Files",
        }
        self.setWindowTitle(op_titles.get(self._operation, "File Operation"))
        self.setMinimumWidth(450)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._title_label = QLabel(f"{op_titles.get(self._operation, 'Processing')}...")
        self._title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self._title_label)

        self._file_label = QLabel("Preparing...")
        layout.addWidget(self._file_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        self._count_label = QLabel(f"0 / {len(self._file_paths)} items")
        layout.addWidget(self._count_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._onCancel)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    # --------------------------------------------------------
    # Method: _startOperation
    # --------------------------------------------------------
    def _startOperation(self):
        self._worker = FileOperationWorker(
            self._operation, self._file_paths, self._destination, self
        )
        self._worker.progressChanged.connect(self._onProgress)
        self._worker.operationFinished.connect(self._onFinished)
        self._worker.errorOccurred.connect(self._onError)
        if self._operation in (FileOperationWorker.OPERATION_COPY, FileOperationWorker.OPERATION_MOVE):
            self._worker.conflictDetected.connect(self._onConflictDetected)
        self._worker.start()

    # --------------------------------------------------------
    # Method: _onConflictDetected
    # Purpose: Show conflict dialog and send user's choice to worker.
    # --------------------------------------------------------
    def _onConflictDetected(self, source_path, dest_path, file_name):
        op_name = "Copy" if self._operation == FileOperationWorker.OPERATION_COPY else "Move"
        dialog = ConflictDialog(source_path, dest_path, op_name, self)
        if dialog.exec_() != QDialog.Accepted:
            self._worker.setConflictResponse(CONFLICT_CANCEL, apply_to_all=False)
            return
        choice, apply_to_all = dialog.getChoice()
        if not choice or choice == CONFLICT_CANCEL:
            self._worker.setConflictResponse(CONFLICT_CANCEL, apply_to_all=False)
            return
        new_dest = None
        if choice == CONFLICT_KEEP_BOTH:
            new_dest = _resolveConflictPath(dest_path)
        self._worker.setConflictResponse(choice, new_dest, apply_to_all)

    # --------------------------------------------------------
    # Slots
    # --------------------------------------------------------
    def _onProgress(self, percent, file_name, detail):
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(percent)
        if file_name:
            self._file_label.setText(f"Processing: {file_name}")
        elif percent == 0 and detail:
            self._file_label.setText(detail)
        if detail:
            self._count_label.setText(detail)
        else:
            total = len(self._file_paths)
            done = int(percent * total / 100) if total else 0
            self._count_label.setText(f"{done} / {total} items")

    def _onFinished(self, success, message):
        self._result_success = success
        self._result_message = message
        self.accept()

    def _onError(self, file_name, error_msg):
        self._file_label.setText(f"Error: {file_name} - {error_msg}")

    def _onCancel(self):
        self._worker.cancel()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelling...")

    # --------------------------------------------------------
    # Public: result accessors
    # --------------------------------------------------------
    def wasSuccessful(self):
        return self._result_success

    def resultMessage(self):
        return self._result_message


# ============================================================
# Module-Level Convenience Functions
# Purpose: Simple wrappers that show a confirmation dialog,
#          run the operation, and return the result.
# ============================================================

def copyFiles(file_paths, destination, parent=None):
    """
    Shows a progress dialog and copies files to destination.
    Returns (success: bool, message: str).
    """
    if not file_paths:
        return True, "No files selected."

    dialog = FileOperationDialog("copy", file_paths, destination, parent)
    dialog.exec_()
    return dialog.wasSuccessful(), dialog.resultMessage()


# ------------------------------------------------------------
def moveFiles(file_paths, destination, parent=None):
    """
    Shows a progress dialog and moves files to destination.
    Returns (success: bool, message: str).
    """
    if not file_paths:
        return True, "No files selected."

    dialog = FileOperationDialog("move", file_paths, destination, parent)
    dialog.exec_()
    return dialog.wasSuccessful(), dialog.resultMessage()


# ------------------------------------------------------------
def deleteFiles(file_paths, parent=None, confirm=True):
    """
    Optionally confirms, then deletes files (to Recycle Bin).
    Returns (success: bool, message: str).
    """
    if not file_paths:
        return True, "No files selected."

    if confirm:
        names = "\n".join(os.path.basename(p) for p in file_paths[:10])
        if len(file_paths) > 10:
            names += f"\n... and {len(file_paths) - 10} more"

        reply = QMessageBox.question(
            parent,
            "Confirm Delete",
            f"Are you sure you want to delete {len(file_paths)} item(s)?\n\n{names}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False, "Delete cancelled."

    dialog = FileOperationDialog("delete", file_paths, "", parent)
    dialog.exec_()
    return dialog.wasSuccessful(), dialog.resultMessage()


# ------------------------------------------------------------
def renameFile(old_path, new_name, parent=None):
    """
    Renames a single file or directory.
    Returns (success: bool, new_path: str, message: str).
    """
    directory = os.path.dirname(old_path)
    new_path = os.path.join(directory, new_name)

    case_only = os.path.normcase(new_path) == os.path.normcase(old_path)
    if os.path.exists(new_path) and not case_only:
        return False, old_path, f"'{new_name}' already exists."

    try:
        os.rename(old_path, new_path)
        return True, new_path, "Renamed successfully."
    except OSError as e:
        return False, old_path, str(e)
