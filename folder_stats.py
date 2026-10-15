"""
Shared folder tree size / count helpers and background workers.
Used by Properties, Compare, and the drive-space status label.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QThread, pyqtSignal

from drive_list import readDriveSpace


# ------------------------------------------------------------
# Function: folderTreeStats
# Purpose: Walk a folder tree; return (total_bytes, file_count, dir_count)
#          or None on failure. is_cancelled, when set, is checked between
#          directories so a closed dialog can stop the walk.
# ------------------------------------------------------------
def folderTreeStats(path, is_cancelled=None):
    total_bytes = 0
    file_count = 0
    dir_count = 0
    try:
        for root, dirs, files in os.walk(path):
            if is_cancelled is not None and is_cancelled():
                return None
            dir_count += len(dirs)
            for name in files:
                file_count += 1
                try:
                    total_bytes += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        return None
    return total_bytes, file_count, dir_count


# ------------------------------------------------------------
# Function: folderImmediateItemCount
# Purpose: Count entries directly in a folder (non-recursive).
# ------------------------------------------------------------
def folderImmediateItemCount(path):
    try:
        with os.scandir(path) as it:
            return sum(1 for _ in it)
    except OSError:
        return None


# ------------------------------------------------------------
# Class: FolderSizeWorker
# Purpose: Compute folder tree size off the UI thread.
# ------------------------------------------------------------
class FolderSizeWorker(QThread):

    finishedOk = pyqtSignal(int, int, int)  # bytes, files, dirs
    failed = pyqtSignal(str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        try:
            stats = folderTreeStats(
                self._path,
                is_cancelled=lambda: self._cancelled,
            )
            if self._cancelled:
                return
            if stats is None:
                self.failed.emit("Could not read folder.")
                return
            total_bytes, file_count, dir_count = stats
            if self._cancelled:
                return
            self.finishedOk.emit(total_bytes, file_count, dir_count)
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


# ------------------------------------------------------------
# Class: DriveSpaceWorker
# Purpose: Read used and free space off the UI thread. A stalled
#          network or cloud mount must not freeze the window.
# ------------------------------------------------------------
class DriveSpaceWorker(QThread):

    # path, DriveSpace or None
    finishedOk = pyqtSignal(str, object)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        try:
            space = readDriveSpace(self._path)
        except Exception:
            space = None
        if self._cancelled:
            return
        self.finishedOk.emit(self._path, space)
