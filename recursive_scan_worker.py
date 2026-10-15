"""
Background directory reads for FileSystemModel.

Flat listings and Subfolders scans both run on a QThread so a slow
disk (a cloud mount, a network share) cannot freeze the window.
A flat listing may still finish on the UI thread when it is fast.
Cancel is checked between entries; a listing that is already inside
one operating-system call finishes that call and then stops.
"""

import os
import stat
import time

from PyQt5.QtCore import QThread, pyqtSignal


# Threads still running after a short wait on window close stay here,
# so Qt does not destroy them together with the window.
_detached_threads = set()


# ------------------------------------------------------------
# Function: skipHidden
# Purpose: True when this name should not appear in the list.
#          Dot names are hidden everywhere. On Windows the
#          hidden file attribute counts too.
# ------------------------------------------------------------
def skipHidden(full_path, name, show_hidden):
    if show_hidden:
        return False
    if name.startswith("."):
        return True
    if os.name != "nt":
        return False
    try:
        st = os.stat(full_path)
        attrs = getattr(st, "st_file_attributes", 0)
        hidden_bit = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2)
        if attrs & hidden_bit:
            return True
    except OSError:
        return True
    return False


# ------------------------------------------------------------
# Function: makeEntry
# Purpose: One listing row, or None when the path cannot be
#          read or is not the kind of item the caller wants.
# Input: expect_dir - True (folders only), False (files only),
#        or None (either).
# ------------------------------------------------------------
def makeEntry(full_path, display_name, expect_dir=None):
    try:
        st = os.stat(full_path)
    except (OSError, PermissionError):
        return None
    is_dir = stat.S_ISDIR(st.st_mode)
    if expect_dir is not None and is_dir != expect_dir:
        return None
    from file_panel import getFileTypeDescription

    return {
        "name": display_name,
        "size": -1 if is_dir else st.st_size,
        "type": getFileTypeDescription(full_path, is_dir),
        "mod_time": st.st_mtime,
        "is_dir": is_dir,
        "full_path": full_path,
    }


# ------------------------------------------------------------
# Function: listFolderEntries
# Purpose: List one folder, not its children.
# Input: cancel_check() returns True when the caller has moved on.
# Output: (entries, error). error is "" when the folder was readable.
# ------------------------------------------------------------
def listFolderEntries(root, show_hidden, cancel_check=None):
    try:
        names = os.listdir(root)
    except OSError as exc:
        return [], (exc.strerror or str(exc))

    if cancel_check is not None and cancel_check():
        return [], ""

    entries = []
    for name in names:
        if cancel_check is not None and cancel_check():
            break
        full_path = os.path.join(root, name)
        if skipHidden(full_path, name, show_hidden):
            continue
        entry = makeEntry(full_path, name)
        if entry is not None:
            entries.append(entry)
    return entries, ""


# ------------------------------------------------------------
# Function: retireThread
# Purpose: Stop using a thread without waiting for it. It is
#          dropped from `retired` once it has actually finished.
# ------------------------------------------------------------
def retireThread(thread, retired):
    if thread is None:
        return
    cancel = getattr(thread, "cancel", None)
    if cancel is not None:
        cancel()
    if thread.isFinished():
        retired.discard(thread)
        thread.deleteLater()
        return

    retired.add(thread)

    def _onFinished(*_args, finished_thread=thread):
        retired.discard(finished_thread)
        _detached_threads.discard(finished_thread)
        finished_thread.deleteLater()

    thread.finished.connect(_onFinished)
    if thread.isFinished():
        _onFinished()


# ------------------------------------------------------------
# Function: waitForThreads
# Purpose: On window close, give each thread a share of
#          timeout_ms to finish. Anything still running is kept
#          alive in a process-wide set.
# ------------------------------------------------------------
def waitForThreads(threads, timeout_ms):
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    for thread in list(threads):
        if thread is None:
            continue
        cancel = getattr(thread, "cancel", None)
        if cancel is not None:
            cancel()
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if thread.isRunning() and remaining_ms > 0:
            thread.wait(remaining_ms)
        if thread.isRunning():
            _detached_threads.add(thread)
        else:
            _detached_threads.discard(thread)


# ============================================================
# Class: FolderListingThread
# Purpose: Read one folder off the UI thread.
#          finishedListing emits (scan_id, entries, error).
#          `entries` and `error` are also stored on the thread
#          so a caller that waited can read them without
#          waiting for the signal to be delivered.
# ============================================================
class FolderListingThread(QThread):

    finishedListing = pyqtSignal(int, list, str)

    def __init__(self, scan_id, root, show_hidden, parent=None):
        super().__init__(parent)
        self._scan_id = scan_id
        self._root = os.path.normpath(root)
        self._show_hidden = bool(show_hidden)
        self._cancel = False
        self.entries = []
        self.error = ""
        self.was_cancelled = False

    def cancel(self):
        self._cancel = True

    def run(self):
        entries, error = listFolderEntries(
            self._root,
            self._show_hidden,
            cancel_check=lambda: self._cancel,
        )
        self.entries = entries
        self.error = error
        self.was_cancelled = self._cancel
        self.finishedListing.emit(self._scan_id, entries, error)


# ============================================================
# Class: RecursiveScanThread
# Purpose: Walk a folder tree for Subfolders mode.
#          Emits progress periodically and checks cancel
#          between os.walk steps.
# ============================================================
class RecursiveScanThread(QThread):

    progress = pyqtSignal(int, str)
    finishedScan = pyqtSignal(int, list)
    scanCancelled = pyqtSignal(int)

    _PROGRESS_INTERVAL_SEC = 0.25
    _PROGRESS_EVERY_ITEMS = 4096

    def __init__(self, scan_id, root, show_hidden, parent=None):
        super().__init__(parent)
        self._scan_id = scan_id
        self._root = os.path.normpath(root)
        self._show_hidden = bool(show_hidden)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        root = self._root
        entries = []
        item_count = 0
        last_emit = time.monotonic()

        def maybe_emit(current_dir):
            nonlocal last_emit, item_count
            now = time.monotonic()
            if (
                now - last_emit >= self._PROGRESS_INTERVAL_SEC
                or item_count % self._PROGRESS_EVERY_ITEMS == 0
            ):
                self.progress.emit(item_count, current_dir)
                last_emit = now

        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if self._cancel:
                    self.scanCancelled.emit(self._scan_id)
                    return

                if not self._show_hidden:
                    dirnames[:] = [
                        d
                        for d in dirnames
                        if not skipHidden(os.path.join(dirpath, d), d, self._show_hidden)
                    ]

                rel_dir = os.path.relpath(dirpath, root)
                if rel_dir == os.curdir:
                    rel_dir = ""

                for d in dirnames:
                    if self._cancel:
                        break
                    full_path = os.path.join(dirpath, d)
                    if skipHidden(full_path, d, self._show_hidden):
                        continue
                    display = os.path.join(rel_dir, d) if rel_dir else d
                    entry = makeEntry(full_path, display, expect_dir=True)
                    if entry is None:
                        continue
                    entries.append(entry)
                    item_count += 1

                for filename in filenames:
                    if self._cancel:
                        break
                    full_path = os.path.join(dirpath, filename)
                    if skipHidden(full_path, filename, self._show_hidden):
                        continue
                    display = os.path.join(rel_dir, filename) if rel_dir else filename
                    entry = makeEntry(full_path, display, expect_dir=False)
                    if entry is None:
                        continue
                    entries.append(entry)
                    item_count += 1

                maybe_emit(dirpath)

        except (OSError, PermissionError):
            pass

        if self._cancel:
            self.scanCancelled.emit(self._scan_id)
            return

        self.finishedScan.emit(self._scan_id, entries)
