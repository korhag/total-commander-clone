"""
Background recursive directory scan for FileSystemModel (Subfolders mode).
Runs on a QThread; supports cooperative cancel between os.walk iterations.
"""

import os
import stat
import time

from PyQt5.QtCore import QThread, pyqtSignal


def _skip_hidden(full_path, name, show_hidden):
    if show_hidden:
        return False
    if name.startswith("."):
        return True
    if os.name == "nt":
        try:
            st = os.stat(full_path)
            attrs = getattr(st, "st_file_attributes", 0)
            hidden_bit = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2)
            if attrs & hidden_bit:
                return True
        except OSError:
            return True
    return False


class RecursiveScanThread(QThread):
    """
    Walks root recursively building the same entry dicts as FileSystemModel._loadDirectoryRecursive.
    Emits progress periodically; checks cancel between os.walk iterations.
    """

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
        from file_panel import getFileTypeDescription

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
                        if not _skip_hidden(os.path.join(dirpath, d), d, self._show_hidden)
                    ]

                rel_dir = os.path.relpath(dirpath, root)
                if rel_dir == os.curdir:
                    rel_dir = ""

                for d in dirnames:
                    if self._cancel:
                        break
                    full_path = os.path.join(dirpath, d)
                    if _skip_hidden(full_path, d, self._show_hidden):
                        continue
                    try:
                        st = os.stat(full_path)
                        if not stat.S_ISDIR(st.st_mode):
                            continue
                        display = os.path.join(rel_dir, d) if rel_dir else d
                        entries.append({
                            "name": display,
                            "size": -1,
                            "type": getFileTypeDescription(full_path, True),
                            "mod_time": st.st_mtime,
                            "is_dir": True,
                            "full_path": full_path,
                        })
                        item_count += 1
                    except (OSError, PermissionError):
                        continue

                for f in filenames:
                    if self._cancel:
                        break
                    if _skip_hidden(os.path.join(dirpath, f), f, self._show_hidden):
                        continue
                    full_path = os.path.join(dirpath, f)
                    try:
                        st = os.stat(full_path)
                        if stat.S_ISDIR(st.st_mode):
                            continue
                        display = os.path.join(rel_dir, f) if rel_dir else f
                        entries.append({
                            "name": display,
                            "size": st.st_size,
                            "type": getFileTypeDescription(full_path, False),
                            "mod_time": st.st_mtime,
                            "is_dir": False,
                            "full_path": full_path,
                        })
                        item_count += 1
                    except (OSError, PermissionError):
                        continue

                maybe_emit(dirpath)

        except (OSError, PermissionError):
            pass

        if self._cancel:
            self.scanCancelled.emit(self._scan_id)
            return

        self.finishedScan.emit(self._scan_id, entries)
