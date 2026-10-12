"""
Tabbed Properties dialog for files and folders: location, size, dates,
attributes, MIME and system metadata, optional checksums for files.
"""

import hashlib
import os
import stat
import sys

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QApplication,
    QMessageBox,
    QSizePolicy,
)
from PyQt5.QtCore import QFileInfo, QMimeDatabase, Qt
from PyQt5.QtGui import QFont

from file_panel import formatFileSize
from folder_stats import (
    FolderSizeWorker,
    folderImmediateItemCount,
    folderTreeStats as _folder_tree_stats,
)


# ------------------------------------------------------------
def _format_dt(ts):
    """Format epoch timestamp as local date/time string, or em dash if invalid."""
    if ts is None or ts <= 0:
        return "—"
    try:
        from datetime import datetime

        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return "—"


def _qdatetime_to_ts(qdt):
    """Convert QDateTime to Unix seconds (PyQt5 compatible)."""
    if qdt is None or not qdt.isValid():
        return None
    try:
        return qdt.toSecsSinceEpoch()
    except AttributeError:
        return int(qdt.toTime_t())


# ------------------------------------------------------------
def _folder_item_count(path):
    return folderImmediateItemCount(path)


# ------------------------------------------------------------
def _windows_attribute_labels(path):
    if os.name != "nt":
        return []
    try:
        import ctypes

        INVALID = 0xFFFFFFFF
        attrs = ctypes.windll.kernel32.GetFileAttributesW(os.fsdecode(path))
        if attrs == INVALID:
            return []
        labels = []
        mapping = [
            (0x1, "Read-only"),
            (0x2, "Hidden"),
            (0x4, "System"),
            (0x10, "Directory"),
            (0x20, "Archive"),
            (0x40, "Device"),
            (0x80, "Normal"),
            (0x100, "Temporary"),
            (0x200, "Sparse file"),
            (0x400, "Reparse point"),
            (0x800, "Compressed"),
            (0x1000, "Offline"),
            (0x2000, "Not content indexed"),
            (0x4000, "Encrypted"),
        ]
        for mask, name in mapping:
            if attrs & mask:
                labels.append(name)
        return labels or ["(none set)"]
    except Exception:
        return []


# ------------------------------------------------------------
def _symlink_target(path):
    if not os.path.islink(path):
        return None
    try:
        return os.readlink(path)
    except OSError:
        return None


# ------------------------------------------------------------
def _owner_group(path, st):
    owner, group = "—", "—"
    if sys.platform == "win32":
        return owner, group
    try:
        import pwd
        import grp

        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
    except (ImportError, AttributeError):
        pass
    return owner, group


# ------------------------------------------------------------
def _mime_description(path, is_dir):
    db = QMimeDatabase()
    if is_dir:
        return "inode/directory", "Folder"
    mime = db.mimeTypeForFile(path, QMimeDatabase.MatchDefault)
    name = mime.name()
    comment = mime.comment()
    if comment:
        return name, f"{name} — {comment}"
    return name, name


# ------------------------------------------------------------
class FilePropertiesDialog(QDialog):
    """
    Modal dialog with General, Details, and (for files) Checksums tabs.
    """

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self._entry = entry
        self._path = entry["full_path"]
        self._folder_size_worker = None
        self._size_label = None
        self.setWindowTitle(f"Properties — {entry['name']}")
        self.setMinimumSize(520, 440)
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._buildGeneralTab(), "General")
        tabs.addTab(self._buildDetailsTab(), "Details")
        if not entry["is_dir"]:
            tabs.addTab(self._buildChecksumsTab(), "Checksums")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if entry.get("is_dir"):
            self._startFolderSizeCalc()

    def done(self, result):
        self._stopFolderSizeWorker()
        super().done(result)

    def _stopFolderSizeWorker(self):
        """Stop the background size walk before the dialog is destroyed."""
        worker = self._folder_size_worker
        if worker is None:
            return
        self._folder_size_worker = None
        try:
            worker.cancel()
            if worker.isRunning():
                worker.wait(2000)
        except Exception:
            pass

    def _stat_safe(self):
        try:
            return os.stat(self._path, follow_symlinks=False)
        except OSError:
            return None

    def _stat_follow(self):
        try:
            return os.stat(self._path, follow_symlinks=True)
        except OSError:
            return None

    def _buildGeneralTab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        info = QFileInfo(self._path)
        st = self._stat_follow()

        # Name
        name_edit = QLineEdit(self._entry["name"])
        name_edit.setReadOnly(True)
        form.addRow("Name:", name_edit)

        # Type (from listing + MIME hint for files)
        type_label = QLabel(self._entry["type"])
        type_label.setWordWrap(True)
        form.addRow("Type:", type_label)

        parent_dir = os.path.dirname(self._path)
        loc_edit = QLineEdit(parent_dir)
        loc_edit.setReadOnly(True)
        form.addRow("Location:", loc_edit)

        path_edit = QLineEdit(self._path)
        path_edit.setReadOnly(True)
        form.addRow("Full path:", path_edit)

        is_dir = self._entry["is_dir"]
        if is_dir:
            self._size_label = QLabel("Calculating…")
            self._size_label.setWordWrap(True)
            form.addRow("Size:", self._size_label)

            cnt = _folder_item_count(self._path)
            if cnt is None:
                contains_text = "—"
            else:
                contains_text = (
                    f"{cnt:,} item{'s' if cnt != 1 else ''} in this folder"
                )
            form.addRow("Contains:", QLabel(contains_text))
        else:
            sz = self._entry["size"]
            human = formatFileSize(sz) if sz >= 0 else "—"
            exact = f"{sz:,} bytes" if sz >= 0 else "—"
            form.addRow("Size:", QLabel(f"{human}  ({exact})"))

        # Dates: os.stat for reliability; birth time when available
        mod_ts = self._entry.get("mod_time")
        acc_ts = None
        created_ts = None
        if st:
            mod_ts = st.st_mtime
            acc_ts = st.st_atime
            birth = info.birthTime()
            bts = _qdatetime_to_ts(birth) if birth.isValid() else None
            if bts is not None and bts > 0:
                created_ts = bts
            elif hasattr(st, "st_birthtime"):
                created_ts = st.st_birthtime
            else:
                created_ts = st.st_ctime
        else:
            lm = info.lastModified()
            if lm.isValid():
                mod_ts = _qdatetime_to_ts(lm)
            if hasattr(info, "lastRead"):
                lr = info.lastRead()
                if lr is not None and lr.isValid():
                    acc_ts = _qdatetime_to_ts(lr)
            birth = info.birthTime()
            if birth.isValid():
                created_ts = _qdatetime_to_ts(birth)

        form.addRow("Created:", QLabel(_format_dt(created_ts)))
        form.addRow("Modified:", QLabel(_format_dt(mod_ts)))
        form.addRow("Accessed:", QLabel(_format_dt(acc_ts)))

        attr_parts = []
        if info.isReadable():
            attr_parts.append("Readable")
        if info.isWritable():
            attr_parts.append("Writable")
        if not is_dir and info.isExecutable():
            attr_parts.append("Executable")
        if info.isHidden():
            attr_parts.append("Hidden")
        if info.isSymbolicLink():
            attr_parts.append("Symbolic link")
        if os.name == "nt":
            attr_parts.extend(_windows_attribute_labels(self._path))
        if attr_parts:
            form.addRow("Attributes:", QLabel(", ".join(dict.fromkeys(attr_parts))))

        return w

    # --------------------------------------------------------
    # Method: _startFolderSizeCalc
    # Purpose: Walk the folder tree in the background and fill Size.
    # --------------------------------------------------------
    def _startFolderSizeCalc(self):
        if self._size_label is None:
            return
        worker = FolderSizeWorker(self._path, self)
        worker.finishedOk.connect(self._onFolderSizeReady)
        worker.failed.connect(self._onFolderSizeFailed)
        self._folder_size_worker = worker
        worker.start()

    def _onFolderSizeReady(self, total_bytes, file_count, dir_count):
        if self._size_label is None:
            return
        human = formatFileSize(total_bytes)
        exact = f"{total_bytes:,} bytes"
        detail = (
            f"{human}  ({exact}) — "
            f"{file_count:,} file{'s' if file_count != 1 else ''}, "
            f"{dir_count:,} subfolder{'s' if dir_count != 1 else ''}"
        )
        self._size_label.setText(detail)
        self._size_label.setToolTip(detail)

    def _onFolderSizeFailed(self, message):
        if self._size_label is None:
            return
        self._size_label.setText(message or "—")

    def _buildDetailsTab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)

        rows = []
        st = self._stat_follow()
        st_l = self._stat_safe()

        mime_name, mime_pretty = _mime_description(self._path, self._entry["is_dir"])
        rows.append(("MIME type", mime_pretty))

        ext = os.path.splitext(self._entry["name"])[1]
        rows.append(("Extension", ext if ext else "—"))

        rows.append(("Path exists", "Yes" if os.path.lexists(self._path) else "No"))
        rows.append(("Absolute path", os.path.abspath(self._path)))

        target = _symlink_target(self._path)
        if target is not None:
            rows.append(("Link target", target))

        if st:
            if self._entry["is_dir"]:
                rows.append(("Size (bytes)", "See General tab (folder total)"))
            else:
                rows.append(("Size (bytes)", f"{st.st_size:,}"))
            try:
                rows.append(("Mode (octal)", oct(stat.S_IMODE(st.st_mode))))
                rows.append(("File mode", stat.filemode(st.st_mode)))
            except (AttributeError, ValueError):
                pass
            rows.append(("Inode", str(st.st_ino)))
            rows.append(("Device", str(st.st_dev)))
            rows.append(("Hard links", str(st.st_nlink)))

        if os.path.islink(self._path) and st_l:
            rows.append(("Inode (symbolic link)", str(st_l.st_ino)))

        own, grp = _owner_group(self._path, st) if st else ("—", "—")
        rows.append(("Owner", own))
        rows.append(("Group", grp))

        drv, root = os.path.splitdrive(self._path)
        if drv:
            rows.append(("Drive", drv))
        rows.append(("Parent name", os.path.basename(os.path.dirname(self._path)) or "—"))

        table.setRowCount(len(rows))
        for i, (k, val) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(k))
            item_val = QTableWidgetItem(str(val))
            item_val.setToolTip(str(val))
            table.setItem(i, 1, item_val)

        v.addWidget(table)
        return w

    def _buildChecksumsTab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(
            "Computes a cryptographic hash of the file contents. "
            "Large files may take a while; the UI may freeze until finished."
        )
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._hash_output = QPlainTextEdit()
        self._hash_output.setReadOnly(True)
        font = QFont("Consolas", 10)
        if not font.exactMatch():
            font = QFont("Courier", 10)
        self._hash_output.setFont(font)
        self._hash_output.setPlaceholderText("Hash results appear here.")
        self._hash_output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self._hash_output, 1)

        row = QHBoxLayout()
        for label, name in (
            ("MD5", "md5"),
            ("SHA-1", "sha1"),
            ("SHA-256", "sha256"),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, n=name: self._computeHash(n))
            row.addWidget(btn)
        row.addStretch()
        v.addLayout(row)
        return w

    def _computeHash(self, algorithm):
        path = self._path
        if self._entry["is_dir"] or not os.path.isfile(path):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            h = hashlib.new(algorithm)
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            line = f"{algorithm.upper()}: {digest}\n"
            self._hash_output.appendPlainText(line.rstrip())
            self._hash_output.appendPlainText("")
        except OSError as e:
            QMessageBox.warning(self, "Checksum", f"Could not read file:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()


def showFileProperties(entry, parent=None):
    """Show modal properties dialog for a file panel entry dict."""
    dlg = FilePropertiesDialog(entry, parent)
    dlg.exec_()
