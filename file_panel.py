"""
Total Commander Clone - File Panel Widget
A single file-browser pane with address bar, navigation buttons,
file table, sorting, filtering, in-place rename, and drag-and-drop.
"""

import fnmatch
import html
import os
import platform
import re
import stat
import string
import subprocess
import time
from datetime import datetime

from filter_spec import FilterSpec
from theme import themeColor
from name_filter import (
    match_exclude_terms,
    match_extension,
    match_include_terms,
    parse_extensions,
    parse_filter_terms,
)
from recursive_scan_worker import RecursiveScanThread
from thumbnail_loader import ThumbnailLoader, isThumbnailCandidate


# Pattern for splitting names into text vs digit runs (natural sort).
_NATURAL_SORT_SPLIT = re.compile(r"(\d+)")

# Date Modified column display formats: key -> (strftime pattern, menu label).
DATE_MODIFIED_FORMATS = {
    "yyyy_mm_dd": ("%Y/%m/%d", "YYYY/MM/DD"),
    "yy_mm_dd": ("%y/%m/%d", "YY/MM/DD"),
    "yyyy_mm_dd_hm": ("%Y/%m/%d %H:%M", "YYYY/MM/DD hh:mm"),
    "yy_mm_dd_hm": ("%y/%m/%d %H:%M", "YY/MM/DD hh:mm"),
    "dd_mm_yyyy": ("%d/%m/%Y", "DD/MM/YYYY"),
    "dd_mm_yy": ("%d/%m/%y", "DD/MM/YY"),
    "dd_mm_yyyy_hm": ("%d/%m/%Y %H:%M", "DD/MM/YYYY hh:mm"),
    "mm_dd_yyyy": ("%m/%d/%Y", "MM/DD/YYYY"),
}
DEFAULT_DATE_MODIFIED_FORMAT = "yyyy_mm_dd_hm"


def resolve_date_modified_format_key(key):
    """Return a valid date_modified_format settings key."""
    if key in DATE_MODIFIED_FORMATS:
        return key
    return DEFAULT_DATE_MODIFIED_FORMAT


def format_date_modified(timestamp, format_key):
    """Format a Unix timestamp for the Date Modified column."""
    key = resolve_date_modified_format_key(format_key)
    pattern = DATE_MODIFIED_FORMATS[key][0]
    return datetime.fromtimestamp(timestamp).strftime(pattern)

# ------------------------------------------------------------
# Helper: natural_sort_key
# Purpose: Sort key so embedded numbers compare numerically
#          (e.g. KT-167 before KT-1665, file2 before file10).
#          Each segment is (0, int) or (1, str) so list compare
#          never mixes bare int with str (e.g. "33112_x" vs "a_1").
# ------------------------------------------------------------
def path_under_root(root, rel):
    """Build an absolute path under root from a relative display path (may contain subdirs)."""
    if not rel:
        return root
    rel = rel.replace("/", os.sep).strip()
    parts = [p for p in rel.split(os.sep) if p and p != "."]
    if not parts:
        return root
    return os.path.normpath(os.path.join(root, *parts))


def natural_sort_key(name):
    parts = []
    for part in _NATURAL_SORT_SPLIT.split(name):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.lower()))
    return parts


# ------------------------------------------------------------
# Helper: list Windows drive letters (e.g. ["C:\\", "D:\\"])
# ------------------------------------------------------------
def getWindowsDrives():
    if os.name != "nt":
        return []
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QAbstractItemView, QHeaderView, QFrame, QLabel,
    QStyledItemDelegate, QStyle, QApplication, QComboBox,
    QFileIconProvider, QInputDialog, QMessageBox, QProgressDialog,
    QMenu, QAction, QActionGroup, QCheckBox,
)
from PyQt5.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QVariant, QMimeData,
    QUrl, pyqtSignal, QSortFilterProxyModel, QPoint, QTimer, QEvent,
    QItemSelectionModel, QSize, QItemSelection, QItemSelectionRange,
    QFileInfo, QMimeDatabase, QFileSystemWatcher,
)
from PyQt5.QtGui import (
    QDrag, QDesktopServices, QIcon, QKeySequence,
    QFontMetrics,
)


def _setDynamicProperty(widget, name, value):
    """Apply a Qt dynamic property and refresh stylesheet."""
    if widget is None:
        return
    widget.setProperty(name, value)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()

# ------------------------------------------------------------
# Helper: human-readable file size
# ------------------------------------------------------------
def formatFileSize(size_bytes):
    if size_bytes < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            if unit == "B":
                return f"{size_bytes} B"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


# ------------------------------------------------------------
# Helper: normalize path from user input (handles quotes, file:// URLs)
# ------------------------------------------------------------
def normalizePathInput(text):
    """Convert user input (paste/type) to a valid local path for navigation."""
    if not text or not isinstance(text, str):
        return ""
    path = text.strip().strip('"\'')
    if path.lower().startswith("file:///"):
        path = path[8:].replace("/", os.sep)
    elif path.lower().startswith("file://"):
        path = path[7:].replace("/", os.sep)
    return os.path.normpath(path) if path else ""


# ------------------------------------------------------------
# Helper: file type description from extension
# ------------------------------------------------------------
def getFileTypeDescription(file_path, is_dir):
    if is_dir:
        return "Folder"
    _, ext = os.path.splitext(file_path)
    if ext:
        return f"{ext[1:].upper()} File"
    return "File"


# ------------------------------------------------------------
# Helper: Windows associated application friendly name (optional)
# ------------------------------------------------------------
def _windows_associated_app_name(path):
    if os.name != "nt" or not path or not os.path.isfile(path):
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        ASSOCF_INIT_DEFAULTTOSTAR = 0x00000004
        ASSOCSTR_FRIENDLYAPPNAME = 8
        shell32 = ctypes.windll.shell32
        buf = ctypes.create_unicode_buffer(1024)
        pcch = wintypes.DWORD(len(buf))
        p = os.path.normpath(path)
        hr = shell32.AssocQueryStringW(
            ASSOCF_INIT_DEFAULTTOSTAR,
            ASSOCSTR_FRIENDLYAPPNAME,
            p,
            None,
            buf,
            ctypes.byref(pcch),
        )
        if hr == 0 and buf.value:
            return buf.value.strip()
    except Exception:
        pass
    return ""


# ------------------------------------------------------------
# Helper: byte size of files directly in a folder (non-recursive)
# ------------------------------------------------------------
def _folder_immediate_files_size_bytes(path):
    """
    Sum st_size for entries that are regular files in `path` only.
    Does not descend into subfolders (keeps tooltips fast). Symlinks are not followed.
    Returns None if the path is unusable or listing fails.
    """
    if not path or not os.path.isdir(path):
        return None
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        return None
    return total


# ------------------------------------------------------------
# Helper: Rich HTML tooltip for file list rows (summary card)
# ------------------------------------------------------------
def build_entry_tooltip_html(entry, recursive=False):
    name = entry["name"]
    full = entry["full_path"]
    is_dir = entry["is_dir"]
    dt = datetime.fromtimestamp(entry["mod_time"])
    date_s = dt.strftime("%Y-%m-%d %H:%M:%S")

    esc_name = html.escape(name)
    esc_full = html.escape(full)
    parent = os.path.dirname(full)
    esc_parent = html.escape(parent) if parent else "—"

    rows_html = []
    if recursive and name and ("\\" in name or "/" in name):
        rows_html.append(
            f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Relative</td>"
            f"<td style='padding:2px 0;'>{esc_name}</td></tr>"
        )
    rows_html.append(
        f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Full path</td>"
        f"<td style='padding:2px 0;'>{esc_full}</td></tr>"
    )
    rows_html.append(
        f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Parent</td>"
        f"<td style='padding:2px 0;'>{esc_parent}</td></tr>"
    )
    rows_html.append(
        f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Modified</td>"
        f"<td style='padding:2px 0;'>{html.escape(date_s)}</td></tr>"
    )
    rows_html.append(
        f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Listed type</td>"
        f"<td style='padding:2px 0;'>{html.escape(entry['type'])}</td></tr>"
    )

    title = "Folder" if is_dir else "File"
    icon = "&#128193;" if is_dir else "&#128196;"
    display_title = html.escape(os.path.basename(full) if full else name)

    if is_dir:
        qb = _folder_immediate_files_size_bytes(full)
        if qb is not None:
            sz = formatFileSize(qb)
            rows_html.insert(
                2 if (recursive and name and ("\\" in name or "/" in name)) else 1,
                f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Size</td>"
                f"<td style='padding:2px 0;'>{html.escape(sz)} "
                f"<span style='color:#888;font-size:11px;'>(files here only)</span></td></tr>",
            )
        foot = [
            "Select this row for full tree size and file counts.",
            "Use Compare with other panel for left/right comparison.",
            "Double-click to open this folder in the panel.",
        ]
        body_extra = (
            "<p style='margin:8px 0 0 0;color:#888;font-size:11px;'>"
            + "<br/>".join(foot)
            + "</p>"
        )
    else:
        sz = formatFileSize(entry["size"])
        insert_at = 2 if (recursive and name and ("\\" in name or "/" in name)) else 1
        rows_html.insert(
            insert_at,
            f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Size</td>"
            f"<td style='padding:2px 0;'>{html.escape(sz)}</td></tr>",
        )
        db = QMimeDatabase()
        mt = db.mimeTypeForFile(full)
        raw_name = mt.name()
        raw_comment = mt.comment() or ""
        rows_html.append(
            f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>MIME</td>"
            f"<td style='padding:2px 0;'>{html.escape(raw_name)}</td></tr>"
        )
        if raw_comment and raw_comment != raw_name:
            rows_html.append(
                f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Kind</td>"
                f"<td style='padding:2px 0;'>{html.escape(raw_comment)}</td></tr>"
            )
        opens = _windows_associated_app_name(full)
        if opens:
            rows_html.append(
                f"<tr><td style='color:#aaa;padding:2px 10px 2px 0;'>Opens with</td>"
                f"<td style='padding:2px 0;'>{html.escape(opens)}</td></tr>"
            )
        body_extra = (
            "<p style='margin:8px 0 0 0;color:#888;font-size:11px;'>"
            "Double-click to open with the default application. "
            "Select the row for path details; use Compare for left/right.</p>"
        )

    table = (
        "<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;'>"
        + "".join(rows_html)
        + "</table>"
    )

    return (
        f"<html><head/><body style='color:{themeColor('text', '#dce0ee')};'>"
        f"<div style='min-width:280px;max-width:520px;'>"
        f"<div style='font-size:13px;font-weight:600;margin-bottom:6px;'>"
        f"{icon} {display_title} <span style='color:#888;font-weight:normal;'>"
        f"({title})</span></div>"
        f"<div style='height:1px;background:#555;margin:4px 0 8px 0;'></div>"
        f"{table}"
        f"{body_extra}"
        "</div></body></html>"
    )


# ============================================================
# Class: DriveLineEdit
# Purpose: Embedded editor for the drive QComboBox; clicking the
#          letter/field opens the dropdown (default Qt only opens
#          from the combo's arrow sub-control).
# ============================================================
class DriveLineEdit(QLineEdit):

    def __init__(self, combo, parent=None):
        super().__init__(parent)
        self._drive_combo = combo

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and self._drive_combo is not None
            and self._drive_combo.isVisible()
        ):
            self._drive_combo.showPopup()
        super().mousePressEvent(event)


# ============================================================
# Class: DrivePickerCombo
# Purpose: Drive QComboBox that opens the list on any left-click on
#          the widget (e.g. drop-down button area inside the control).
#          Optional on_before_popup runs when the list is about to open
#          (e.g. re-scan drive letters on Windows).
# ============================================================
class DrivePickerCombo(QComboBox):

    def __init__(self, parent=None, on_before_popup=None):
        super().__init__(parent)
        self._on_before_popup = on_before_popup

    def showPopup(self):
        if self._on_before_popup is not None:
            self._on_before_popup()
        super().showPopup()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isVisible():
            self.showPopup()
        super().mousePressEvent(event)


# ============================================================
# Class: FileSystemModel
# Purpose: Custom QAbstractTableModel that reads a directory
#          and presents its contents as table rows with columns
#          for Name, Size, Type, and Date Modified.
# ============================================================
class FileSystemModel(QAbstractTableModel):

    recursiveScanRequested = pyqtSignal(str, int)
    recursiveScanAbortRequested = pyqtSignal()

    COLUMNS = ["Name", "Size", "Type", "Date Modified"]
    COLUMN_TOOLTIPS = [
        "Name — File or folder as listed (includes subpaths when Subfolders search is on).",
        "Size — File size on disk; folders show &lt;DIR&gt;.",
        "Type — Extension or category (e.g. PY File, Folder).",
        "Date Modified — Last time the item was modified.",
    ]

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = ""
        self._entries = []
        self._show_hidden = False
        self._recursive = False
        self._icon_provider = QFileIconProvider()
        self._thumbnails = ThumbnailLoader(self)
        self._thumbnails.thumbnailReady.connect(self._onThumbnailReady)
        self._show_thumbnails = False
        self._thumbnail_size = 48
        self._thumb_row_hints = {}
        self._scan_generation = 0
        self._date_modified_format_key = DEFAULT_DATE_MODIFIED_FORMAT
        self._quiet_scan = False
        self._listing_from_cache = False
        self._load_error = ""

    # --------------------------------------------------------
    # Method: showHiddenFiles
    # --------------------------------------------------------
    def showHiddenFiles(self):
        return self._show_hidden

    # --------------------------------------------------------
    # Method: showThumbnails
    # Purpose: True when image files should show a preview icon.
    # --------------------------------------------------------
    def showThumbnails(self):
        return self._show_thumbnails

    # --------------------------------------------------------
    # Method: setShowThumbnails
    # Purpose: Turn previews on or off and repaint the Name column.
    # --------------------------------------------------------
    def setShowThumbnails(self, show):
        show = bool(show)
        if show == self._show_thumbnails:
            return
        self._show_thumbnails = show
        if not show:
            self._thumbnails.cancelPending()
        self._emitNameDecorationsChanged()

    # --------------------------------------------------------
    # Method: setThumbnailSize
    # Purpose: Pixel size of previews. Follows the UI scale.
    # --------------------------------------------------------
    def setThumbnailSize(self, size):
        size = max(1, int(size))
        if size == self._thumbnail_size:
            return
        self._thumbnail_size = size
        if self._show_thumbnails:
            self._emitNameDecorationsChanged()

    def _emitNameDecorationsChanged(self):
        rows = len(self._entries)
        if rows <= 0:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(rows - 1, 0),
            [Qt.DecorationRole],
        )

    def _onThumbnailReady(self, path):
        """Repaint the row whose preview just finished loading."""
        if not self._show_thumbnails or not path:
            return
        norm = os.path.normcase(os.path.normpath(path))
        hint = self._thumb_row_hints.get(norm, -1)
        if 0 <= hint < len(self._entries):
            hinted = self._entries[hint].get("full_path") or ""
            if os.path.normcase(os.path.normpath(hinted)) == norm:
                index = self.index(hint, 0)
                self.dataChanged.emit(index, index, [Qt.DecorationRole])
                return
        for row, entry in enumerate(self._entries):
            full = entry.get("full_path") or ""
            if os.path.normcase(os.path.normpath(full)) == norm:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [Qt.DecorationRole])
                return

    # --------------------------------------------------------
    # Method: _iconForEntry
    # Purpose: Preview icon for an image when thumbnails are on,
    #          otherwise the normal file icon.
    # --------------------------------------------------------
    def _iconForEntry(self, entry, row):
        full_path = entry.get("full_path") or ""
        if (
            self._show_thumbnails
            and not entry.get("is_dir")
            and isThumbnailCandidate(entry.get("name") or "", entry.get("size", -1))
        ):
            if full_path:
                norm = os.path.normcase(os.path.normpath(full_path))
                self._thumb_row_hints[norm] = row
            icon = self._thumbnails.request(
                full_path,
                entry.get("mod_time") or 0,
                self._thumbnail_size,
            )
            if icon is not None:
                return icon
        return self._icon_provider.icon(QFileInfo(full_path))

    def listingFromCache(self):
        return bool(self._listing_from_cache)

    def loadError(self):
        """Reason the last flat listing failed, or "" when it succeeded."""
        return self._load_error

    def quietScanPending(self):
        return bool(self._quiet_scan)

    # --------------------------------------------------------
    # Method: applyRecursiveScanResult
    # Purpose: Apply worker result on the GUI thread if generation matches.
    # --------------------------------------------------------
    def applyRecursiveScanResult(self, gen, entries):
        if gen != self._scan_generation:
            return
        self._thumbnails.cancelPending()
        self._thumb_row_hints.clear()
        self.beginResetModel()
        self._entries = list(entries)
        self._entries.sort(
            key=lambda e: (not e["is_dir"], natural_sort_key(e["name"]))
        )
        self.endResetModel()
        self._listing_from_cache = False
        self._quiet_scan = False
        self._storeScanCache()

    def _storeScanCache(self):
        if not self._recursive or not self._current_path:
            return
        try:
            from scan_cache import putScanCache

            putScanCache(self._current_path, self._show_hidden, self._entries)
        except Exception:
            pass

    def _syncScanCacheAfterMutation(self):
        if not self._recursive or not self._current_path:
            return
        try:
            from scan_cache import updateScanCacheFromEntries

            updateScanCacheFromEntries(
                self._current_path, self._show_hidden, self._entries
            )
        except Exception:
            pass

    # --------------------------------------------------------
    # Method: removeEntriesByPaths
    # Purpose: Drop entries whose full_path equals or is under paths.
    # --------------------------------------------------------
    def removeEntriesByPaths(self, paths):
        if not paths or not self._entries:
            return 0
        norms = []
        for p in paths:
            if not p:
                continue
            norms.append(os.path.normcase(os.path.normpath(p)))
        if not norms:
            return 0

        def should_remove(full):
            fp = os.path.normcase(os.path.normpath(full))
            for n in norms:
                if fp == n or fp.startswith(n + os.sep):
                    return True
            return False

        kept = [e for e in self._entries if not should_remove(e.get("full_path") or "")]
        removed = len(self._entries) - len(kept)
        if removed <= 0:
            return 0
        self.beginResetModel()
        self._entries = kept
        self.endResetModel()
        self._listing_from_cache = False
        self._syncScanCacheAfterMutation()
        return removed

    # --------------------------------------------------------
    # Method: upsertEntryFromPath
    # Purpose: Stat one path and insert/update its listing row.
    # Output: True on success, False if stat/path fails (caller may refresh).
    # --------------------------------------------------------
    def upsertEntryFromPath(self, full_path, relative_path=None):
        if not self._current_path or not full_path:
            return False
        full_path = os.path.normpath(full_path)
        root = os.path.normpath(self._current_path)
        try:
            st = os.stat(full_path)
        except OSError:
            return False
        is_dir = stat.S_ISDIR(st.st_mode)
        size = -1 if is_dir else st.st_size
        mod_time = st.st_mtime
        if relative_path:
            display = relative_path.replace("/", os.sep).strip()
            parts = [p for p in display.split(os.sep) if p and p != "."]
            if not parts or ".." in parts:
                return False
            display = os.path.join(*parts)
        else:
            try:
                display = os.path.relpath(full_path, root)
            except ValueError:
                return False
            display = display.replace("/", os.sep)
            if display in (".", "") or display.startswith(".." + os.sep) or display == "..":
                return False
        name_key = os.path.basename(full_path)
        if self._skip_hidden_stat(full_path, name_key):
            # Hidden and currently hidden — ensure absent from list.
            self.removeEntriesByPaths([full_path])
            return True

        full_norm = os.path.normcase(full_path)
        updated = False
        for entry in self._entries:
            if os.path.normcase(os.path.normpath(entry.get("full_path") or "")) == full_norm:
                entry["name"] = display
                entry["size"] = size
                entry["type"] = getFileTypeDescription(full_path, is_dir)
                entry["mod_time"] = mod_time
                entry["is_dir"] = is_dir
                entry["full_path"] = full_path
                updated = True
                break
        if not updated:
            self._entries.append({
                "name": display,
                "size": size,
                "type": getFileTypeDescription(full_path, is_dir),
                "mod_time": mod_time,
                "is_dir": is_dir,
                "full_path": full_path,
            })
        self.beginResetModel()
        self._entries.sort(
            key=lambda e: (not e["is_dir"], natural_sort_key(e["name"]))
        )
        self.endResetModel()
        self._listing_from_cache = False
        self._syncScanCacheAfterMutation()
        return True

    # --------------------------------------------------------
    # Method: setRecursive
    # Purpose: When True, list all files/folders under current path (tree walk).
    # --------------------------------------------------------
    def setRecursive(self, recursive):
        recursive = bool(recursive)
        if self._recursive == recursive:
            return
        self._recursive = recursive
        if self._current_path:
            self.loadDirectory(self._current_path, force_rescan=True)

    def isRecursive(self):
        return self._recursive

    # --------------------------------------------------------
    # Method: setDateModifiedFormatKey
    # Purpose: Select strftime preset for the Date Modified column.
    # --------------------------------------------------------
    def setDateModifiedFormatKey(self, format_key):
        key = resolve_date_modified_format_key(format_key)
        if key == self._date_modified_format_key:
            return
        self._date_modified_format_key = key
        self._refreshDateModifiedColumn()

    def dateModifiedFormatKey(self):
        return self._date_modified_format_key

    def _refreshDateModifiedColumn(self):
        if not self._entries:
            return
        col = 3
        top_left = self.index(0, col)
        bottom_right = self.index(len(self._entries) - 1, col)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    # --------------------------------------------------------
    # Method: setShowHidden
    # Purpose: Toggles visibility of hidden files/dotfiles.
    # --------------------------------------------------------
    def setShowHidden(self, show):
        self._show_hidden = show
        if self._current_path:
            self.loadDirectory(self._current_path, force_rescan=True)

    def _skip_hidden_stat(self, full_path, name):
        if self._show_hidden:
            return False
        if name.startswith("."):
            return True
        if os.name == "nt":
            try:
                st = os.stat(full_path)
                attrs = getattr(st, "st_file_attributes", 0)
                if attrs & stat.FILE_ATTRIBUTE_HIDDEN:
                    return True
            except OSError:
                return True
        return False

    def _append_entry(self, full_path, display_name, is_dir, size, mod_time):
        file_type = getFileTypeDescription(full_path, is_dir)
        self._entries.append({
            "name": display_name,
            "size": size,
            "type": file_type,
            "mod_time": mod_time,
            "is_dir": is_dir,
            "full_path": full_path,
        })

    # --------------------------------------------------------
    # Method: loadDirectory
    # Purpose: Scans the given directory and populates the model.
    # Recursive mode uses session/disk cache when possible, then
    # optionally quietly re-scans in the background.
    # Input: path (str), force_rescan (bool) - skip cache.
    # --------------------------------------------------------
    def loadDirectory(self, path, force_rescan=False):
        path = os.path.normpath(path)
        self._thumbnails.cancelPending()
        self._thumb_row_hints.clear()
        self.recursiveScanAbortRequested.emit()
        self._quiet_scan = False
        self._listing_from_cache = False
        self._load_error = ""

        if not self._recursive:
            self._loadDirectoryFlatSync(path)
            return

        self._scan_generation += 1
        gen = self._scan_generation
        self._current_path = path

        if not force_rescan:
            try:
                from scan_cache import getScanCache

                cached = getScanCache(path, self._show_hidden)
            except Exception:
                cached = None
            if cached is not None:
                self.beginResetModel()
                self._entries = list(cached)
                self._entries.sort(
                    key=lambda e: (not e["is_dir"], natural_sort_key(e["name"]))
                )
                self.endResetModel()
                self._listing_from_cache = True
                self._quiet_scan = False
                return

        self.beginResetModel()
        self._entries = []
        self.endResetModel()
        self.recursiveScanRequested.emit(path, gen)

    def _loadDirectoryFlatSync(self, path):
        self.beginResetModel()
        self._current_path = path
        self._entries = []
        self._loadDirectoryFlat(path)
        self._entries.sort(
            key=lambda e: (not e["is_dir"], natural_sort_key(e["name"]))
        )
        self.endResetModel()

    def _loadDirectoryFlat(self, path):
        try:
            items = os.listdir(path)
        except OSError as exc:
            self._load_error = exc.strerror or str(exc)
            return

        for name in items:
            if self._skip_hidden_stat(os.path.join(path, name), name):
                continue

            full_path = os.path.join(path, name)
            try:
                st = os.stat(full_path)
                is_dir = stat.S_ISDIR(st.st_mode)
                size = st.st_size if not is_dir else -1
                mod_time = st.st_mtime
                self._append_entry(full_path, name, is_dir, size, mod_time)
            except (PermissionError, OSError):
                continue

    # --------------------------------------------------------
    # Method: currentPath
    # --------------------------------------------------------
    def currentPath(self):
        return self._current_path

    # --------------------------------------------------------
    # Method: entryAt
    # Purpose: Returns the entry dict for a given row index.
    # --------------------------------------------------------
    def entryAt(self, row):
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    # --------------------------------------------------------
    # Method: getEntryByName
    # Purpose: Finds an entry by file name and returns its row.
    # --------------------------------------------------------
    def getEntryByName(self, name):
        for i, entry in enumerate(self._entries):
            if entry["name"] == name:
                return i
        return -1

    # --------------------------------------------------------
    # Method: renameEntry
    # Purpose: Updates the name of an entry after a rename.
    # --------------------------------------------------------
    def renameEntry(self, row, new_name):
        if 0 <= row < len(self._entries):
            entry = self._entries[row]
            old_path = entry.get("full_path") or ""
            new_path = path_under_root(self._current_path, new_name)
            entry["name"] = new_name
            entry["full_path"] = new_path
            entry["type"] = getFileTypeDescription(new_path, entry["is_dir"])
            first_row, last_row = row, row
            if entry["is_dir"] and self._recursive and old_path:
                if self._renameDescendants(old_path, new_path):
                    first_row, last_row = 0, len(self._entries) - 1
            idx_start = self.index(first_row, 0)
            idx_end = self.index(last_row, len(self.COLUMNS) - 1)
            self.dataChanged.emit(idx_start, idx_end)
            self._syncScanCacheAfterMutation()

    # --------------------------------------------------------
    # Method: _renameDescendants
    # Purpose: In Subfolders mode, point rows under a renamed
    #          folder at the new folder path.
    # Output: bool - True when any row changed.
    # --------------------------------------------------------
    def _renameDescendants(self, old_dir, new_dir):
        prefix = os.path.normcase(os.path.normpath(old_dir)) + os.sep
        changed = False
        for entry in self._entries:
            full = os.path.normpath(entry.get("full_path") or "")
            if not os.path.normcase(full).startswith(prefix):
                continue
            moved = os.path.join(new_dir, full[len(prefix):])
            entry["full_path"] = moved
            try:
                entry["name"] = os.path.relpath(moved, self._current_path)
            except ValueError:
                entry["name"] = os.path.basename(moved)
            changed = True
        return changed

    # --------------------------------------------------------
    # Qt Model Interface
    # --------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return QVariant()

        entry = self._entries[index.row()]
        col = index.column()

        if role == Qt.ToolTipRole:
            return build_entry_tooltip_html(entry, recursive=self._recursive)

        if role == Qt.DisplayRole:
            if col == 0:
                return entry["name"]
            elif col == 1:
                if entry["is_dir"]:
                    return "<DIR>"
                return formatFileSize(entry["size"])
            elif col == 2:
                return entry["type"]
            elif col == 3:
                return format_date_modified(
                    entry["mod_time"], self._date_modified_format_key
                )

        if role == Qt.DecorationRole and col == 0:
            return self._iconForEntry(entry, index.row())

        if role == Qt.UserRole:
            return entry

        if role == Qt.TextAlignmentRole:
            if col == 1:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return QVariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.COLUMNS[section]
            if role == Qt.ToolTipRole:
                if 0 <= section < len(self.COLUMN_TOOLTIPS):
                    return self.COLUMN_TOOLTIPS[section]
        return QVariant()

    def flags(self, index):
        default_flags = super().flags(index)
        if index.isValid():
            return default_flags | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return default_flags | Qt.ItemIsDropEnabled

    # --------------------------------------------------------
    # Drag and Drop MIME support
    # --------------------------------------------------------
    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        mime_data = QMimeData()
        urls = []
        seen_rows = set()
        for index in indexes:
            if index.row() not in seen_rows:
                seen_rows.add(index.row())
                entry = self._entries[index.row()]
                urls.append(QUrl.fromLocalFile(entry["full_path"]))
        mime_data.setUrls(urls)
        return mime_data

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction


# ============================================================
# Class: FileSortFilterProxy
# Purpose: QSortFilterProxyModel that allows real-time text
#          filtering by file name and custom sort behavior
#          (folders always on top).
# ============================================================
class FileSortFilterProxy(QSortFilterProxyModel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self._filter_exclude_text = ""
        self._filter_extensions_text = ""
        self._filter_extensions = []
        self._filter_words_combine_and = True
        self._filter_mode = "contains"
        self._entry_kind = "all"
        self._regex_obj = None
        self._regex_invalid = False
        self._include_regex_cache = {}
        self._exclude_regex_cache = {}
        self._filter_spec = FilterSpec()
        self.setDynamicSortFilter(True)

    # --------------------------------------------------------
    # Method: setFilterText
    # --------------------------------------------------------
    def setFilterText(self, text):
        self._filter_text = text or ""
        self._regex_obj = None
        self._regex_invalid = False
        self._include_regex_cache = {}
        if self._filter_mode == "regex" and self._filter_text.strip():
            try:
                self._regex_obj = re.compile(
                    self._filter_text, re.IGNORECASE | re.UNICODE
                )
            except re.error:
                self._regex_invalid = True
        self.invalidateFilter()

    def setFilterExcludeText(self, text):
        self._filter_exclude_text = text or ""
        self._exclude_regex_cache = {}
        self.invalidateFilter()

    def filterExcludeText(self):
        return self._filter_exclude_text

    def setFilterExtensionsText(self, text):
        self._filter_extensions_text = text or ""
        self._filter_extensions = parse_extensions(self._filter_extensions_text)
        self.invalidateFilter()

    def filterExtensionsText(self):
        return self._filter_extensions_text

    def setFilterWordsCombineAnd(self, combine_and):
        self._filter_words_combine_and = bool(combine_and)
        self.invalidateFilter()

    def filterWordsCombineAnd(self):
        return self._filter_words_combine_and

    # --------------------------------------------------------
    # Method: setFilterMode
    # Purpose: "contains" | "wildcard" | "regex" — how name is matched.
    # --------------------------------------------------------
    def setFilterMode(self, mode):
        if mode not in ("contains", "wildcard", "regex"):
            return
        self._filter_mode = mode
        self._include_regex_cache = {}
        self._exclude_regex_cache = {}
        self.setFilterText(self._filter_text)

    def filterMode(self):
        return self._filter_mode

    # --------------------------------------------------------
    # Method: setEntryKindFilter
    # Purpose: "all" | "dirs" | "files" — limit rows before name match.
    # --------------------------------------------------------
    def setEntryKindFilter(self, kind):
        if kind not in ("all", "dirs", "files"):
            return
        self._entry_kind = kind
        self.invalidateFilter()

    def entryKindFilter(self):
        return self._entry_kind

    # --------------------------------------------------------
    # Method: setFilterSpec / filterSpec
    # Purpose: Optional size/date rules (FilterSpec); AND with name + kind.
    # --------------------------------------------------------
    def setFilterSpec(self, spec):
        self._filter_spec = spec if spec is not None else FilterSpec()
        self.invalidateFilter()

    def filterSpec(self):
        return self._filter_spec

    # --------------------------------------------------------
    # Method: filterAcceptsRow
    # --------------------------------------------------------
    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        entry = model.entryAt(source_row)
        if entry is None:
            return False

        if self._entry_kind == "dirs" and not entry["is_dir"]:
            return False
        if self._entry_kind == "files" and entry["is_dir"]:
            return False

        name = entry["name"]

        if self._filter_extensions and not entry["is_dir"]:
            if not match_extension(name, self._filter_extensions):
                return False

        exclude_terms = parse_filter_terms(self._filter_exclude_text)
        if exclude_terms and match_exclude_terms(
            name,
            exclude_terms,
            self._filter_mode,
            self._exclude_regex_cache,
        ):
            return False

        if self._filter_mode == "regex":
            # One pattern: splitting on spaces/commas would break e.g. "a{1,3}".
            if self._filter_text.strip():
                if self._regex_invalid or self._regex_obj is None:
                    return False
                if self._regex_obj.search(name) is None:
                    return False
        else:
            include_terms = parse_filter_terms(self._filter_text)
            if include_terms and not match_include_terms(
                name,
                include_terms,
                self._filter_mode,
                self._filter_words_combine_and,
                self._include_regex_cache,
            ):
                return False

        if self._filter_spec is not None and not self._filter_spec.is_empty():
            if not self._filter_spec.matches(entry):
                return False
        return True

    # --------------------------------------------------------
    # Method: lessThan
    # Purpose: Custom sort keeping folders before files.
    # --------------------------------------------------------
    def lessThan(self, left, right):
        model = self.sourceModel()
        left_entry = model.entryAt(left.row())
        right_entry = model.entryAt(right.row())

        if left_entry is None or right_entry is None:
            return False

        if left_entry["is_dir"] != right_entry["is_dir"]:
            return left_entry["is_dir"]

        col = left.column()
        if col == 0:
            return natural_sort_key(left_entry["name"]) < natural_sort_key(right_entry["name"])
        elif col == 1:
            return left_entry["size"] < right_entry["size"]
        elif col == 2:
            return left_entry["type"].lower() < right_entry["type"].lower()
        elif col == 3:
            return left_entry["mod_time"] < right_entry["mod_time"]
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        src = self.sourceModel()
        if (
            src is not None
            and orientation == Qt.Horizontal
            and role == Qt.ToolTipRole
        ):
            return src.headerData(section, orientation, role)
        return super().headerData(section, orientation, role)


# ============================================================
# Class: FileTableItemDelegate
# Purpose: Elide long names in the middle; other columns elide on
#          the right only when the column is narrower than the text.
# ============================================================
class FileTableItemDelegate(QStyledItemDelegate):

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.column() == 0:
            option.textElideMode = Qt.ElideMiddle
        else:
            option.textElideMode = Qt.ElideRight

    def paint(self, painter, option, index):
        view = self.parent()
        renaming_row = getattr(view, "renamingRow", None)
        if (
            index.column() == 0
            and callable(renaming_row)
            and renaming_row() == index.row()
        ):
            self.initStyleOption(option, index)
            option.text = ""
            super().paint(painter, option, index)
            return
        super().paint(painter, option, index)


# ============================================================
# Class: FileTableView
# Purpose: QTableView subclass with drag-and-drop initiation,
#          drop target visual feedback, and slow-click-to-rename
#          (clicking an already-selected file starts rename
#          after a short delay, like Windows Explorer).
# ============================================================
class FileTableView(QTableView):

    filesDropped = pyqtSignal(list, str, bool)
    slowClickRenameRequested = pyqtSignal()
    emptyAreaPressed = pyqtSignal()
    panelPressed = pyqtSignal()
    viewportResized = pyqtSignal()

    RENAME_CLICK_DELAY_MS = 600

    # --------------------------------------------------------
    # Pixels from top/bottom of viewport that trigger auto-scroll when dragging selection.
    EDGE_SCROLL_ZONE = 24
    SCROLL_STEP_PX = 12
    SCROLL_TIMER_MS = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos = None
        self._selection_anchor_row = -1
        self._press_was_on_selected_row = False  # True only when file-drag is intended
        self._scroll_direction = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(self.SCROLL_TIMER_MS)
        self._scroll_timer.timeout.connect(self._onScrollTimeout)

        self._slow_click_row = -1
        self._renaming_row = -1
        self._rename_timer = QTimer(self)
        self._rename_timer.setSingleShot(True)
        self._rename_timer.timeout.connect(self._onRenameTimerFired)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewportResized.emit()

    def renamingRow(self):
        return self._renaming_row

    def setRenamingRow(self, row):
        if self._renaming_row == row:
            return
        old_row = self._renaming_row
        self._renaming_row = row
        model = self.model()
        if model is None:
            return
        for r in (old_row, row):
            if r >= 0:
                idx = model.index(r, 0)
                if idx.isValid():
                    self.viewport().update(self.visualRect(idx))

    # --------------------------------------------------------
    # Slow-click-to-rename logic:
    # First click selects the row. A second single-click on the
    # same already-selected row (not a double-click) starts a
    # short timer. If the timer fires, rename begins.
    # Double-clicking cancels the timer so it navigates instead.
    # --------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
            clicked_index = self.indexAt(event.pos())
            if clicked_index.isValid():
                self._selection_anchor_row = clicked_index.row()
                selected_rows = self.selectionModel().selectedRows()
                self._press_was_on_selected_row = any(
                    sr.row() == clicked_index.row() for sr in selected_rows
                )
            else:
                self._selection_anchor_row = -1
                self._press_was_on_selected_row = False

            selected_rows = self.selectionModel().selectedRows()
            is_single_selected = (
                len(selected_rows) == 1
                and clicked_index.isValid()
                and selected_rows[0].row() == clicked_index.row()
            )

            if is_single_selected and not self._rename_timer.isActive():
                self._slow_click_row = clicked_index.row()
                self._rename_timer.start(self.RENAME_CLICK_DELAY_MS)
            else:
                self._rename_timer.stop()
                self._slow_click_row = -1

        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.panelPressed.emit()
            if not self.indexAt(event.pos()).isValid():
                self.emptyAreaPressed.emit()

    def mouseDoubleClickEvent(self, event):
        self._rename_timer.stop()
        self._slow_click_row = -1
        super().mouseDoubleClickEvent(event)

    def _onRenameTimerFired(self):
        selected_rows = self.selectionModel().selectedRows()
        if (
            len(selected_rows) == 1
            and selected_rows[0].row() == self._slow_click_row
        ):
            self.slowClickRenameRequested.emit()
        self._slow_click_row = -1

    # --------------------------------------------------------
    # Cancel any pending rename timer (called externally when
    # the panel loses active state or navigation occurs).
    # --------------------------------------------------------
    def cancelPendingRename(self):
        self._rename_timer.stop()
        self._slow_click_row = -1

    # --------------------------------------------------------
    # Edge auto-scroll during drag-to-select
    # --------------------------------------------------------
    def _updateEdgeScroll(self, active, direction):
        if active and direction != 0:
            self._scroll_direction = direction
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        else:
            self._scroll_direction = 0
            self._scroll_timer.stop()

    def _onScrollTimeout(self):
        if self._scroll_direction == 0:
            self._scroll_timer.stop()
            return
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() + self._scroll_direction * self.SCROLL_STEP_PX)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._selection_anchor_row = -1
            self._updateEdgeScroll(False, 0)
        super().mouseReleaseEvent(event)

    # --------------------------------------------------------
    # Drag initiation
    # --------------------------------------------------------
    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._drag_start_pos is None:
            self._updateEdgeScroll(False, 0)
            super().mouseMoveEvent(event)
            return

        distance = (event.pos() - self._drag_start_pos).manhattanLength()
        # Drag-to-select: when user did not press on an already-selected row, always
        # extend selection by drag. Only start file-drag when they pressed on a selected row.
        doing_select_drag = not self._press_was_on_selected_row

        if doing_select_drag or distance < QApplication.startDragDistance():
            # Extend selection from anchor to current row (and optionally auto-scroll)
            if self._selection_anchor_row >= 0:
                current_index = self.indexAt(event.pos())
                if current_index.isValid():
                    model = self.model()
                    r1 = min(self._selection_anchor_row, current_index.row())
                    r2 = max(self._selection_anchor_row, current_index.row())
                    col_count = model.columnCount()
                    if col_count > 0:
                        top_left = model.index(r1, 0)
                        bottom_right = model.index(r2, col_count - 1)
                        sel = QItemSelection(top_left, bottom_right)
                        self.selectionModel().select(
                            sel,
                            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
                        )
                y = event.pos().y()
                vh = self.viewport().height()
                if y < self.EDGE_SCROLL_ZONE:
                    self._updateEdgeScroll(True, -1)
                elif y > vh - self.EDGE_SCROLL_ZONE:
                    self._updateEdgeScroll(True, 1)
                else:
                    self._updateEdgeScroll(False, 0)
            if doing_select_drag:
                event.accept()
                return
            super().mouseMoveEvent(event)
            return

        # File-drag: user pressed on a selected row and moved past threshold
        self._selection_anchor_row = -1
        self._updateEdgeScroll(False, 0)
        self._rename_timer.stop()
        self._slow_click_row = -1

        selected_indexes = self.selectionModel().selectedRows()
        if not selected_indexes:
            super().mouseMoveEvent(event)
            return

        drag = QDrag(self)
        mime_data = self.model().mimeData(selected_indexes)
        drag.setMimeData(mime_data)

        drag.exec_(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction)

    # --------------------------------------------------------
    # Drop handling
    # --------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    # --------------------------------------------------------
    # Method: _resolveDropIsCopy
    # Purpose: Normalize copy/move semantics for both internal
    #          panel drags and external Explorer drags.
    # --------------------------------------------------------
    def _resolveDropIsCopy(self, event):
        if event.dropAction() == Qt.CopyAction:
            return True
        if event.dropAction() == Qt.MoveAction:
            return False
        if event.proposedAction() == Qt.CopyAction:
            return True
        if event.proposedAction() == Qt.MoveAction:
            return False

        modifiers = event.keyboardModifiers()
        if modifiers & Qt.ControlModifier:
            return True
        if modifiers & Qt.ShiftModifier:
            return False

        # External drags default to copy, internal panel drags keep move.
        return event.source() is None

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        urls = event.mimeData().urls()
        file_paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if not file_paths:
            event.ignore()
            return

        is_copy = self._resolveDropIsCopy(event)

        proxy = self.model()
        drop_index = self.indexAt(event.pos())
        drop_target = ""
        if drop_index.isValid():
            source_index = proxy.mapToSource(drop_index)
            entry = proxy.sourceModel().entryAt(source_index.row())
            if entry and entry["is_dir"]:
                drop_target = entry["full_path"]

        if not drop_target:
            drop_target = proxy.sourceModel().currentPath()

        self.panelPressed.emit()
        self.filesDropped.emit(file_paths, drop_target, is_copy)
        event.acceptProposedAction()


# ============================================================
# Class: _RenameLineEdit
# Purpose: Inline editor for file renaming. Emits distinct
#          signals for Enter (commit), Escape (cancel), and
#          focus-lost (cancel), so the caller can handle each
#          case independently.
# ============================================================
class _RenameLineEdit(QLineEdit):

    enterPressed = pyqtSignal()
    escapePressed = pyqtSignal()
    focusLostSignal = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.enterPressed.emit()
            return
        if event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusLostSignal.emit()


# ============================================================
# Class: FilePanel
# Purpose: Complete file browser panel widget combining the
#          address bar, navigation buttons, filter input,
#          file table, and status summary.
# ============================================================
class FilePanel(QWidget):

    pathChanged = pyqtSignal(str)
    pathCopied = pyqtSignal(str)
    folderCreated = pyqtSignal(str)
    fileDoubleClicked = pyqtSignal(dict)
    selectionChanged = pyqtSignal()
    filesDropped = pyqtSignal(list, str, bool)
    activated = pyqtSignal()
    dateModifiedFormatChanged = pyqtSignal(str)

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, panel_side="left", parent=None, settings_manager=None):
        super().__init__(parent)
        self._panel_side = panel_side
        self._settings_manager = settings_manager
        self._history = []
        self._history_index = -1
        self._is_active = False
        self._rename_edit = None
        self._scan_thread = None
        self._scan_progress = None
        self._column_width_clamping = False
        self._freeze_column_widths = False
        self._column_width_locked = {k: False for k in self.COLUMN_VISIBILITY_KEYS}
        self._locked_column_width_px = {}
        self._viewport_layout_timer = QTimer(self)
        self._viewport_layout_timer.setSingleShot(True)
        self._viewport_layout_timer.setInterval(50)
        self._viewport_layout_timer.timeout.connect(self._fitColumnsToViewport)
        self._column_width_save_timer = QTimer(self)
        self._column_width_save_timer.setSingleShot(True)
        self._column_width_save_timer.setInterval(400)
        self._column_width_save_timer.timeout.connect(self._persistColumnWidthsToState)
        # Wait for a burst of changes (a copy, a download) to settle.
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setSingleShot(True)
        self._auto_refresh_timer.setInterval(300)
        self._auto_refresh_timer.timeout.connect(self._applyPendingAutoRefresh)
        self._auto_refresh_deferred = False
        self._dir_watcher = QFileSystemWatcher(self)
        self._dir_watcher.directoryChanged.connect(self._onWatchedDirectoryChanged)

        self._initUI()
        self._connectSignals()
        if self._settings_manager is not None:
            fmt_key = resolve_date_modified_format_key(
                self._settings_manager.getSetting(
                    "date_modified_format", DEFAULT_DATE_MODIFIED_FORMAT
                )
            )
            self._source_model.setDateModifiedFormatKey(fmt_key)
        self._path_edit.installEventFilter(self)
        self._filter_edit.installEventFilter(self)
        self._installActivationEventFilters()
        self._updateFrameStyle()

    # --------------------------------------------------------
    # Method: _initUI
    # Purpose: Builds and lays out all child widgets.
    # --------------------------------------------------------
    def _initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        NAV_BAR_HEIGHT = 28
        NAV_ICON_SIZE = 18
        style = QApplication.instance().style()

        # --- Path bar (full width: path input + copy + paste) ---
        path_layout = QHBoxLayout()
        path_layout.setSpacing(4)

        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("panelPathEdit")
        self._path_edit.setPlaceholderText("Enter or paste path, press Enter to go...")
        self._path_edit.setMinimumHeight(NAV_BAR_HEIGHT)
        self._path_edit.setAlignment(Qt.AlignVCenter)
        self._path_edit.setToolTip(
            "Address bar\n\n"
            "Shows the folder open in this panel. Type or paste a path and press Enter "
            "to navigate. Use the copy/paste buttons to work with the clipboard."
        )

        self._btn_copy_path = QPushButton()
        self._btn_copy_path.setObjectName("navButton")
        self._btn_copy_path.setFixedSize(30, NAV_BAR_HEIGHT)
        self._btn_copy_path.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self._btn_copy_path.setToolTip(
            "Copy path\n\nCopy the current folder path to the clipboard."
        )
        self._btn_copy_path.setAutoDefault(False)
        self._btn_copy_path.setDefault(False)
        copy_icon = QIcon.fromTheme("edit-copy")
        if copy_icon.isNull():
            copy_icon = QIcon.fromTheme("document-copy")
        if copy_icon.isNull():
            self._btn_copy_path.setText("\U0001F4CB")
        else:
            self._btn_copy_path.setIcon(copy_icon)
        self._btn_copy_path.clicked.connect(self._copyPathToClipboard)

        self._btn_paste_path = QPushButton()
        self._btn_paste_path.setObjectName("navButton")
        self._btn_paste_path.setFixedSize(30, NAV_BAR_HEIGHT)
        self._btn_paste_path.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self._btn_paste_path.setToolTip(
            "Paste path\n\nPaste a path from the clipboard and navigate to that folder if it exists."
        )
        self._btn_paste_path.setAutoDefault(False)
        self._btn_paste_path.setDefault(False)
        paste_icon = QIcon.fromTheme("edit-paste")
        if paste_icon.isNull():
            paste_icon = QIcon.fromTheme("document-paste")
        if paste_icon.isNull():
            self._btn_paste_path.setText("\U0001F4E5")
        else:
            self._btn_paste_path.setIcon(paste_icon)
        self._btn_paste_path.clicked.connect(self._pastePathAndNavigate)

        self._btn_browse_folder = QPushButton()
        self._btn_browse_folder.setObjectName("navButton")
        self._btn_browse_folder.setFixedSize(30, NAV_BAR_HEIGHT)
        self._btn_browse_folder.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self._btn_browse_folder.setToolTip(
            "Open in Explorer\n\nOpen this folder in the operating system's file manager "
            "(Windows Explorer, Finder, etc.)."
        )
        self._btn_browse_folder.setAutoDefault(False)
        self._btn_browse_folder.setDefault(False)
        self._btn_browse_folder.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self._btn_browse_folder.clicked.connect(self._openCurrentFolderInSystemExplorer)

        path_layout.addWidget(self._path_edit, 1)
        path_layout.addWidget(self._btn_copy_path)
        path_layout.addWidget(self._btn_paste_path)
        path_layout.addWidget(self._btn_browse_folder)
        layout.addLayout(path_layout)

        # --- Models (needed before filter options menu) ---
        self._source_model = FileSystemModel(self)
        self._proxy_model = FileSortFilterProxy(self)
        self._proxy_model.setSourceModel(self._source_model)

        # --- Navigation bar (back, forward, up, home, new folder, drive, filter…) ---
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(4)

        for btn_attr in ("_btn_back", "_btn_forward", "_btn_up", "_btn_home"):
            btn = QPushButton()
            btn.setObjectName("navButton")
            btn.setFixedSize(30, NAV_BAR_HEIGHT)
            btn.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
            btn.setAutoDefault(False)
            btn.setDefault(False)
            setattr(self, btn_attr, btn)
        self._btn_back.setToolTip(
            "Back\n\nGo to the previous folder in this panel's history. Shortcut: Alt+Left."
        )
        self._btn_back.setIcon(style.standardIcon(QStyle.SP_ArrowBack))
        self._btn_back.setEnabled(False)
        self._btn_forward.setToolTip(
            "Forward\n\nGo to the next folder in this panel's history. Shortcut: Alt+Right."
        )
        self._btn_forward.setIcon(style.standardIcon(QStyle.SP_ArrowForward))
        self._btn_forward.setEnabled(False)
        self._btn_up.setToolTip(
            "Up\n\nOpen the parent folder. Shortcut: Backspace."
        )
        self._btn_up.setIcon(style.standardIcon(QStyle.SP_ArrowUp))
        self._btn_home.setToolTip(
            "Home\n\nJump to your user home directory."
        )
        self._btn_home.setText("\U0001F3E0")
        self._btn_home.clicked.connect(self._goHome)

        self._drive_combo = DrivePickerCombo(
            on_before_popup=self._refreshDrives if os.name == "nt" else None,
        )
        self._drive_combo.setObjectName("driveCombo")
        self._drive_combo.setToolTip(
            "Drive\n\nChoose a drive letter to jump to its root. "
            "On Windows the list refreshes when you open the menu."
        )
        self._drive_combo.setFixedSize(58, NAV_BAR_HEIGHT)
        self._drive_combo.setMinimumContentsLength(2)
        self._drive_combo.setEditable(True)
        drive_line_edit = DriveLineEdit(self._drive_combo, self._drive_combo)
        drive_line_edit.setReadOnly(True)
        drive_line_edit.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        drive_line_edit.setFrame(False)
        self._drive_combo.setLineEdit(drive_line_edit)
        self._drive_line_edit = drive_line_edit
        drives = getWindowsDrives()
        if drives:
            self._drive_combo.addItems(drives)
            self._drive_combo.currentIndexChanged.connect(self._onDriveChanged)
        else:
            self._drive_combo.setVisible(False)

        self._drive_arrow = QLabel("\u25BC")
        self._drive_arrow.setObjectName("driveArrow")
        self._drive_arrow.setFixedSize(14, NAV_BAR_HEIGHT)
        self._drive_arrow.setCursor(Qt.PointingHandCursor)
        self._drive_arrow.mousePressEvent = self._onDriveArrowClicked
        self._drive_arrow.setVisible(bool(drives))
        self._drive_arrow.setToolTip(
            "Open drive list\n\nClick to show the same drive menu as the field beside it."
        )

        self._drive_container = QWidget()
        self._drive_container.setFixedSize(72, NAV_BAR_HEIGHT)
        drive_container_layout = QHBoxLayout(self._drive_container)
        drive_container_layout.setContentsMargins(0, 0, 0, 0)
        drive_container_layout.setSpacing(0)
        drive_container_layout.addWidget(self._drive_combo, 0, Qt.AlignVCenter)
        drive_container_layout.addWidget(self._drive_arrow, 0, Qt.AlignVCenter)

        self._filter_edit = QLineEdit()
        self._filter_edit.setObjectName("panelFilterEdit")
        self._filter_edit.setPlaceholderText("\U0001F50D Filter...")
        self._filter_edit.setMinimumWidth(120)
        self._filter_edit.setMinimumHeight(NAV_BAR_HEIGHT)
        self._filter_edit.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._filter_edit.setClearButtonEnabled(False)
        self._filter_edit.setToolTip(
            "Filter\n\n"
            "Narrow the file list by name. Separate multiple words with spaces; "
            "open Settings for AND/OR, exclude terms, extensions, match mode, "
            "files/folders, subfolders (recursive search), size, date, and saved presets."
        )

        self._btn_clear_filter = QPushButton("\u2715 Clear")
        self._btn_clear_filter.setObjectName("filterClearButton")
        self._btn_clear_filter.setFixedHeight(NAV_BAR_HEIGHT)
        self._btn_clear_filter.setAutoDefault(False)
        self._btn_clear_filter.setDefault(False)
        self._btn_clear_filter.setToolTip(
            "Clear filter\n\n"
            "Remove all active search and filter settings for this panel."
        )
        self._btn_clear_filter.clicked.connect(self.clearFilter)
        self._btn_clear_filter.setVisible(False)

        self._btn_filter_options = QPushButton("\u2699 Settings")
        self._btn_filter_options.setObjectName("filterSettingsButton")
        self._btn_filter_options.setFixedHeight(NAV_BAR_HEIGHT)
        self._btn_filter_options.setAutoDefault(False)
        self._btn_filter_options.setDefault(False)
        self._btn_filter_options.setToolTip(
            "Filter settings\n\n"
            "Open the filter dialog: include/exclude words (AND/OR), file extensions, "
            "match mode, files or folders only, include subfolders (recursive search), "
            "size and modified date (with AND/OR), and saved presets."
        )
        self._btn_filter_options.clicked.connect(self._onOpenFilterOptions)
        filter_opts_icon = QIcon.fromTheme("view-filter")
        if filter_opts_icon.isNull():
            filter_opts_icon = style.standardIcon(QStyle.SP_FileDialogContentsView)
        if not filter_opts_icon.isNull():
            self._btn_filter_options.setIcon(filter_opts_icon)
            self._btn_filter_options.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
            self._btn_filter_options.setText("Settings")

        self._btn_thumbnails = QPushButton("Thumbnails")
        self._btn_thumbnails.setObjectName("thumbnailButton")
        self._btn_thumbnails.setCheckable(True)
        self._btn_thumbnails.setFixedHeight(NAV_BAR_HEIGHT)
        self._btn_thumbnails.setAutoDefault(False)
        self._btn_thumbnails.setDefault(False)
        self._btn_thumbnails.setToolTip(
            "Thumbnails\n\n"
            "Show a small preview of image files in the Name column. "
            "Folders and other files keep their normal icon. "
            "This choice is saved for this panel."
        )
        thumb_icon = QIcon.fromTheme("image-x-generic")
        if thumb_icon.isNull():
            thumb_icon = style.standardIcon(QStyle.SP_FileDialogInfoView)
        if not thumb_icon.isNull():
            self._btn_thumbnails.setIcon(thumb_icon)
            self._btn_thumbnails.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self._btn_thumbnails.toggled.connect(self._onThumbnailsToggled)

        self._btn_new_folder = QPushButton()
        self._btn_new_folder.setObjectName("navButton")
        self._btn_new_folder.setFixedSize(30, NAV_BAR_HEIGHT)
        self._btn_new_folder.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self._btn_new_folder.setToolTip(
            "New folder\n\n"
            "Create a new subfolder in the folder shown in this panel. "
            "Shortcut: F8 when this panel is active."
        )
        self._btn_new_folder.setAutoDefault(False)
        self._btn_new_folder.setDefault(False)
        new_folder_icon = QIcon.fromTheme("folder-new")
        if new_folder_icon.isNull():
            new_folder_icon = style.standardIcon(QStyle.SP_FileDialogNewFolder)
        if new_folder_icon.isNull():
            self._btn_new_folder.setText("\U0001F4C1+")
        else:
            self._btn_new_folder.setIcon(new_folder_icon)

        nav_layout.addWidget(self._btn_back)
        nav_layout.addWidget(self._btn_forward)
        nav_layout.addWidget(self._btn_up)
        nav_layout.addWidget(self._btn_home)
        nav_layout.addWidget(self._btn_new_folder)
        nav_layout.addWidget(self._drive_container)
        nav_layout.addWidget(self._filter_edit, 1)
        nav_layout.addWidget(self._btn_clear_filter, 0, Qt.AlignVCenter)
        nav_layout.addWidget(self._btn_filter_options, 0, Qt.AlignVCenter)
        nav_layout.addWidget(self._btn_thumbnails, 0, Qt.AlignVCenter)

        layout.addLayout(nav_layout)

        # --- Filter-active banner (shown when any filter hides or restricts items) ---
        self._filter_banner = QWidget()
        self._filter_banner.setObjectName("panelFilterBanner")
        banner_layout = QHBoxLayout(self._filter_banner)
        banner_layout.setContentsMargins(10, 6, 10, 6)
        banner_layout.setSpacing(10)
        self._filter_banner_label = QLabel()
        self._filter_banner_label.setObjectName("panelFilterBannerText")
        self._filter_banner_label.setWordWrap(True)
        self._filter_banner_refresh_btn = QPushButton("\u21bb Refresh")
        self._filter_banner_refresh_btn.setObjectName("filterRefreshButton")
        self._filter_banner_refresh_btn.setAutoDefault(False)
        self._filter_banner_refresh_btn.setDefault(False)
        self._filter_banner_refresh_btn.setToolTip(
            "Refresh search\n\n"
            "Force a full re-scan of the current folder (and subfolders when that "
            "option is on), then re-apply all active filter rules. Use this if files "
            "changed outside the app; normal copy/move updates the list without a full scan."
        )
        self._filter_banner_refresh_btn.clicked.connect(self.refreshFilterSearch)
        self._filter_banner_btn = QPushButton("\u2715 Clear filter")
        self._filter_banner_btn.setObjectName("filterClearButton")
        self._filter_banner_btn.setAutoDefault(False)
        self._filter_banner_btn.setDefault(False)
        self._filter_banner_btn.setToolTip(
            "Clear filter\n\n"
            "Remove all active search and filter settings for this panel."
        )
        self._filter_banner_btn.clicked.connect(self.clearFilter)
        banner_layout.addWidget(self._filter_banner_label, 1)
        banner_layout.addWidget(self._filter_banner_refresh_btn, 0, Qt.AlignVCenter)
        banner_layout.addWidget(self._filter_banner_btn, 0, Qt.AlignVCenter)
        self._filter_banner.setVisible(False)
        layout.addWidget(self._filter_banner)

        # --- File table ---
        self._table = FileTableView(self)
        self._table.setObjectName("panelFileTable")
        self._table.setModel(self._proxy_model)
        self._table.setItemDelegate(FileTableItemDelegate(self._table))
        self._table.sortByColumn(0, Qt.AscendingOrder)
        self._header_section_mins = []
        self._refreshHeaderSectionMinimums()
        hdr = self._table.horizontalHeader()
        hdr.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._onTableHeaderContextMenu)

        layout.addWidget(self._table, 1)

        # --- Status label ---
        self._status_label = QLabel("0 items")
        self._status_label.setObjectName("panelLabel")
        layout.addWidget(self._status_label)

        self._frame = self
        self._updateFrameStyle()
        self._updateFilterUi()
        if self._settings_manager is not None:
            from theme import getUiMetrics, normalize_ui_scale
            fs = int(self._settings_manager.getSetting("font_size", 10))
            sc = normalize_ui_scale(self._settings_manager.getSetting("ui_scale", 100))
            self.applyUiMetrics(getUiMetrics(fs, sc))

    # --------------------------------------------------------
    # Method: applyUiMetrics
    # Purpose: Apply row height and nav bar sizes from Settings density.
    # --------------------------------------------------------
    def applyUiMetrics(self, metrics):
        if not metrics:
            return
        h = metrics["nav_bar_height"]
        icon = metrics["nav_icon_size"]
        icon_sz = QSize(icon, icon)
        btn_w = metrics.get("nav_button_width", 30)

        self._path_edit.setMinimumHeight(max(h, metrics.get("path_edit_height", h)))
        for btn in (
            self._btn_copy_path,
            self._btn_paste_path,
            self._btn_browse_folder,
            self._btn_back,
            self._btn_forward,
            self._btn_up,
            self._btn_home,
            self._btn_new_folder,
        ):
            btn.setFixedSize(btn_w, h)
            btn.setIconSize(icon_sz)
        self._btn_clear_filter.setFixedHeight(h)
        self._btn_filter_options.setFixedHeight(h)
        self._btn_filter_options.setIconSize(icon_sz)
        self._btn_thumbnails.setFixedHeight(h)
        self._btn_thumbnails.setIconSize(icon_sz)
        self._drive_combo.setFixedSize(metrics["drive_combo_width"], h)
        arrow_w = max(12, int(round(btn_w * 14 / 30)))
        self._drive_arrow.setFixedSize(arrow_w, h)
        self._drive_container.setFixedSize(metrics["drive_combo_width"] + arrow_w, h)
        self._filter_edit.setFixedHeight(h)
        if getattr(self, "_drive_line_edit", None) is not None:
            self._drive_line_edit.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self._filter_edit.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._ui_metrics = metrics
        self._layout_scale = float(metrics.get("layout_scale", 1.0))
        self._applyRowMetrics()
        self._refreshHeaderSectionMinimums()

    # --------------------------------------------------------
    # Method: _applyRowMetrics
    # Purpose: Row height and icon size. Thumbnails use a taller
    #          row so the preview fits; otherwise the normal list size.
    # --------------------------------------------------------
    def _applyRowMetrics(self):
        metrics = getattr(self, "_ui_metrics", None)
        if not metrics:
            return
        if self._source_model.showThumbnails():
            row_h = metrics["thumbnail_row_height"]
            icon = metrics["thumbnail_size"]
            self._source_model.setThumbnailSize(icon)
        else:
            row_h = metrics["table_row_height"]
            icon = metrics.get("table_icon_size", 16)
        vh = self._table.verticalHeader()
        vh.setMinimumSectionSize(max(16, row_h - 4))
        vh.setDefaultSectionSize(row_h)
        for row in range(vh.count()):
            if vh.sectionSize(row) != row_h:
                vh.resizeSection(row, row_h)
        self._table.setIconSize(QSize(icon, icon))

    # --------------------------------------------------------
    # Method: setShowThumbnails
    # Purpose: Toggle image previews for this panel and remember it.
    # --------------------------------------------------------
    def setShowThumbnails(self, enabled, persist=True):
        enabled = bool(enabled)
        self._btn_thumbnails.blockSignals(True)
        self._btn_thumbnails.setChecked(enabled)
        self._btn_thumbnails.blockSignals(False)
        metrics = getattr(self, "_ui_metrics", None)
        if enabled and metrics:
            self._source_model.setThumbnailSize(metrics["thumbnail_size"])
        self._source_model.setShowThumbnails(enabled)
        self._applyRowMetrics()
        if persist:
            self._persistShowThumbnails()

    def _onThumbnailsToggled(self, checked):
        self.setShowThumbnails(checked, persist=True)

    def _persistShowThumbnails(self):
        """Remember the toggle in this panel's saved state."""
        if self._settings_manager is None:
            return
        current = dict(self._settings_manager.getPanelState(self._panel_side))
        current["show_thumbnails"] = self._source_model.showThumbnails()
        self._settings_manager.setPanelState(self._panel_side, current)
        self._settings_manager.saveSettings()

    # --------------------------------------------------------
    # Column width persistence (all columns; state.json per panel).
    # After first layout or a manual resize, widths are frozen and may exceed
    # the viewport — horizontal scroll appears instead of shrinking columns.
    # --------------------------------------------------------
    COLUMN_WIDTH_KEYS = ("name", "size", "type", "date_modified")
    COLUMN_VISIBILITY_KEYS = ("name", "size", "type", "date_modified")
    # Minimum column width as a fraction of table viewport (sum of mins must fit in vw).
    COLUMN_VIEWPORT_MIN_FRACTION = 0.05
    NAME_COLUMN_VIEWPORT_MIN_FRACTION = 0.22
    # Ignore / do not persist widths below this (avoids corrupt state from pre-layout saves).
    MIN_PERSISTED_COLUMN_WIDTH = 48
    DEFAULT_NAME_COLUMN_WIDTH = 260
    DATE_COLUMN_MAX_WIDTH = 168
    COLUMN_MIN_PIXELS = {
        "name": 96,
        "size": 54,
        "type": 50,
        "date_modified": 124,
    }

    def _refreshHeaderSectionMinimums(self):
        """Pixel minimums so headers (Size, Type, Date Modified) are not clipped."""
        hdr = self._table.horizontalHeader()
        fm = hdr.fontMetrics()
        scale = getattr(self, "_layout_scale", 1.0)
        pad = max(12, int(round(18 * scale)))
        self._header_section_mins = []
        for label in FileSystemModel.COLUMNS:
            self._header_section_mins.append(fm.horizontalAdvance(label) + pad)

    def _minWidthForColumn(self, col, vw=None):
        """Per-column floor: header text width and configured minimums."""
        keys = self.COLUMN_VISIBILITY_KEYS
        key = keys[col] if col < len(keys) else None
        header_min = (
            self._header_section_mins[col]
            if col < len(self._header_section_mins)
            else 24
        )
        scale = getattr(self, "_layout_scale", 1.0)
        cfg_base = self.COLUMN_MIN_PIXELS.get(key, 24) if key else 24
        cfg_min = max(24, int(round(cfg_base * scale)))
        floor = max(header_min, cfg_min, 24)
        if col == 0 and vw is not None:
            pct = max(1, int(round(vw * self.NAME_COLUMN_VIEWPORT_MIN_FRACTION)))
            floor = max(floor, pct)
        return floor

    def _updateColumnStretchBehavior(self):
        """Interactive resize on every column; no stretch-to-viewport modes."""
        hdr = self._table.horizontalHeader()
        n = self._source_model.columnCount()
        hdr.setStretchLastSection(False)
        for col in range(n):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)

    def _columnKeyAt(self, logical_index):
        """Logical column index -> persistence key (name/size/type/date_modified)."""
        keys = self.COLUMN_VISIBILITY_KEYS
        if 0 <= logical_index < len(keys):
            return keys[logical_index]
        return None

    @classmethod
    def _sanitizeColumnVisibility(cls, vis_dict):
        """Ensure the Name column stays visible; fix corrupt %APPDATA% state."""
        if not vis_dict:
            return None
        out = dict(vis_dict)
        if out.get("name") is False:
            out["name"] = True
        visible = [out.get(k, True) for k in cls.COLUMN_VISIBILITY_KEYS]
        if not any(visible):
            out["name"] = True
        return out

    @classmethod
    def _sanitizeColumnWidths(cls, widths_dict):
        """Replace collapsed name/size/type widths from bad saves."""
        if not widths_dict:
            return None
        out = dict(widths_dict)
        min_w = cls.MIN_PERSISTED_COLUMN_WIDTH
        name_w = out.get("name")
        if name_w is None or not isinstance(name_w, (int, float)) or int(name_w) < min_w:
            out["name"] = cls.DEFAULT_NAME_COLUMN_WIDTH
        for key in cls.COLUMN_WIDTH_KEYS:
            w = out.get(key)
            if w is not None and isinstance(w, (int, float)) and 0 < int(w) < min_w:
                out.pop(key, None)
        return out

    def getColumnWidthLockState(self):
        """Return locked flags and pixel widths for persistence."""
        locked = {
            k: bool(self._column_width_locked.get(k))
            for k in self.COLUMN_VISIBILITY_KEYS
        }
        widths = {
            k: int(self._locked_column_width_px[k])
            for k in self.COLUMN_VISIBILITY_KEYS
            if self._column_width_locked.get(k) and k in self._locked_column_width_px
        }
        return {"column_width_locked": locked, "locked_column_widths": widths}

    def applyColumnWidthLockState(self, data):
        """Restore column lock flags and stored widths from panel state."""
        if not data:
            return
        locked_in = data.get("column_width_locked") or {}
        widths_in = data.get("locked_column_widths") or {}
        for k in self.COLUMN_VISIBILITY_KEYS:
            if k in locked_in:
                self._column_width_locked[k] = bool(locked_in[k])
            else:
                self._column_width_locked[k] = False
        self._locked_column_width_px.clear()
        min_w = self.MIN_PERSISTED_COLUMN_WIDTH
        for k, w in widths_in.items():
            if (
                k in self.COLUMN_VISIBILITY_KEYS
                and isinstance(w, (int, float))
                and int(w) >= min_w
            ):
                self._locked_column_width_px[k] = int(w)
            elif k in self.COLUMN_VISIBILITY_KEYS:
                self._column_width_locked[k] = False

    def _wouldLeaveNoUnlockedVisibleColumn(self, logical_index_being_locked):
        """
        True if every visible column except the one being locked is already locked,
        so locking it would leave no flexible column for layout.
        """
        n = self._source_model.columnCount()
        for c in range(n):
            if self._table.isColumnHidden(c):
                continue
            k = self._columnKeyAt(c)
            if not k:
                continue
            if c == logical_index_being_locked:
                continue
            if not self._column_width_locked.get(k):
                return False
        return True

    def _scheduleFitColumnsToViewport(self):
        """Coalesce rapid viewport resizes before the one-time initial fit."""
        self._viewport_layout_timer.start()

    def _onTableViewportResized(self):
        if self._freeze_column_widths:
            self._applyColumnMinimumWidthsOnly()
        else:
            self._scheduleFitColumnsToViewport()

    def _applyColumnMinimumWidthsOnly(self):
        """
        Raise columns only when below header/config minimums.
        Never shrink or stretch columns to match the viewport.
        """
        n = self._source_model.columnCount()
        visible = [c for c in range(n) if not self._table.isColumnHidden(c)]
        if not visible:
            return
        hdr = self._table.horizontalHeader()
        hdr.setMinimumSectionSize(
            min(self._minWidthForColumn(c) for c in visible)
        )
        self._column_width_clamping = True
        try:
            hdr.blockSignals(True)
            for c in visible:
                floor = self._minWidthForColumn(c)
                if self._table.columnWidth(c) < floor:
                    self._table.setColumnWidth(c, floor)
        finally:
            hdr.blockSignals(False)
            self._column_width_clamping = False

    def _persistColumnWidthsToState(self):
        if self._settings_manager is None:
            return
        lock_state = self.getColumnWidthLockState()
        panel_key = f"{self._panel_side}_panel"
        current = dict(self._settings_manager.getPanelState(self._panel_side))
        current.update(
            {
                "column_widths": self.getColumnWidths(),
                "column_width_locked": lock_state["column_width_locked"],
                "locked_column_widths": lock_state["locked_column_widths"],
            }
        )
        self._settings_manager.setPanelState(self._panel_side, current)
        self._settings_manager.saveSettings()

    def _setColumnWidthLock(self, logical_index, locked):
        """Lock or unlock column width; when locking, store current pixel width."""
        key = self._columnKeyAt(logical_index)
        if not key:
            return
        if locked and self._wouldLeaveNoUnlockedVisibleColumn(logical_index):
            QMessageBox.information(
                self,
                "Lock column width",
                "At least one visible column must stay unlocked so the panel can adjust "
                "when you resize the window or the sidebar.",
            )
            act = self.sender()
            if isinstance(act, QAction):
                act.blockSignals(True)
                act.setChecked(False)
                act.blockSignals(False)
            return
        self._column_width_locked[key] = bool(locked)
        if locked:
            self._locked_column_width_px[key] = max(
                1, self._table.columnWidth(logical_index)
            )
        else:
            self._locked_column_width_px.pop(key, None)
        if self._freeze_column_widths:
            self._applyColumnMinimumWidthsOnly()
        else:
            self._fitColumnsToViewport()

    def _fitColumnsToViewport(self):
        """
        One-time / explicit layout: fit visible columns into the viewport width.
        Not used after saved or user-set widths (_freeze_column_widths).
        """
        if self._column_width_clamping:
            return
        vw = max(1, self._table.viewport().width())
        hdr = self._table.horizontalHeader()
        n = self._source_model.columnCount()
        keys = self.COLUMN_VISIBILITY_KEYS
        visible = [c for c in range(n) if not self._table.isColumnHidden(c)]
        m = len(visible)
        if m == 0:
            return

        def col_floor(c):
            return self._minWidthForColumn(c, vw)

        hdr.setMinimumSectionSize(
            min(col_floor(c) for c in visible) if visible else 24
        )

        locked_set = set()
        for c in visible:
            k = self._columnKeyAt(c)
            if k and self._column_width_locked.get(k):
                locked_set.add(c)

        flex = [c for c in visible if c not in locked_set]

        w = {}
        for c in visible:
            floor = self._minWidthForColumn(c, vw)
            w[c] = max(floor, self._table.columnWidth(c))
        for c in locked_set:
            k = keys[c]
            px = self._locked_column_width_px.get(k)
            if px is not None:
                w[c] = max(col_floor(c), int(px))

        def total_width():
            return sum(w[c] for c in visible)

        total = total_width()
        if total > vw:
            sum_l = sum(w[c] for c in locked_set)
            sum_f = sum(w[c] for c in flex)
            min_flex_total = sum(col_floor(c) for c in flex)

            if not flex:
                if total > 0:
                    factor = vw / total
                    for c in visible:
                        w[c] = max(col_floor(c), int(w[c] * factor))
                    drift = vw - sum(w[c] for c in visible)
                    if drift != 0:
                        last = visible[-1]
                        w[last] = max(col_floor(last), w[last] + drift)
            else:
                max_lock_sum = max(0, vw - min_flex_total)
                if sum_l > max_lock_sum and locked_set:
                    factor = max_lock_sum / sum_l if sum_l else 0
                    for c in locked_set:
                        w[c] = max(col_floor(c), int(w[c] * factor))
                    sum_l = sum(w[c] for c in locked_set)

                rem = vw - sum_l
                sum_f = sum(w[c] for c in flex)
                if rem < min_flex_total:
                    base = rem // len(flex)
                    rmd = rem % len(flex)
                    for i, c in enumerate(flex):
                        w[c] = max(col_floor(c), base + (1 if i < rmd else 0))
                elif sum_f > 0:
                    factor = rem / sum_f
                    for c in flex:
                        w[c] = max(col_floor(c), int(w[c] * factor))
                    drift = rem - sum(w[c] for c in flex)
                    if drift != 0:
                        last_flex = flex[-1]
                        w[last_flex] = max(col_floor(last_flex), w[last_flex] + drift)

            while total_width() > vw:
                pool = [c for c in flex if w[c] > col_floor(c)]
                if not pool:
                    pool = [c for c in locked_set if w[c] > col_floor(c)]
                if not pool:
                    pool = [c for c in visible if w[c] > 1]
                if not pool:
                    break
                w[max(pool, key=lambda x: w[x])] -= 1

        total = total_width()
        if total < vw:
            extra = vw - total
            date_col = self.COLUMN_VISIBILITY_KEYS.index("date_modified")
            if date_col in visible:
                date_cap = max(
                    self._minWidthForColumn(date_col, vw),
                    int(round(self.DATE_COLUMN_MAX_WIDTH * getattr(self, "_layout_scale", 1.0))),
                )
                if w[date_col] > date_cap:
                    extra += w[date_col] - date_cap
                    w[date_col] = date_cap
            if 0 in visible and extra > 0:
                w[0] += extra
            elif flex and extra > 0:
                w[flex[-1]] += extra
            elif extra > 0:
                w[visible[-1]] += extra
        elif total > vw:
            last = visible[-1]
            w[last] -= total - vw
            w[last] = max(col_floor(last), w[last])

        self._column_width_clamping = True
        try:
            hdr.blockSignals(True)
            for c in visible:
                self._table.setColumnWidth(c, max(1, w[c]))
            for c in locked_set:
                k = keys[c]
                self._locked_column_width_px[k] = self._table.columnWidth(c)
            self._updateColumnStretchBehavior()
        finally:
            hdr.blockSignals(False)
            self._column_width_clamping = False

    def applyColumnVisibility(self, vis_dict):
        """Show/hide columns from saved state (keys: name, size, type, date_modified)."""
        vis_dict = self._sanitizeColumnVisibility(vis_dict)
        if not vis_dict:
            return
        for col, key in enumerate(self.COLUMN_VISIBILITY_KEYS):
            if col >= self._source_model.columnCount():
                break
            v = vis_dict.get(key)
            if v is not None:
                self._table.setColumnHidden(col, not bool(v))
        if self._freeze_column_widths:
            self._applyColumnMinimumWidthsOnly()
        else:
            self._fitColumnsToViewport()

    def getColumnVisibility(self):
        """Return visibility flags for each column."""
        return {
            key: not self._table.isColumnHidden(col)
            for col, key in enumerate(self.COLUMN_VISIBILITY_KEYS)
            if col < self._source_model.columnCount()
        }

    def relayoutColumns(self):
        """Initial viewport fit once, then only enforce column minimum widths."""
        if self._freeze_column_widths:
            self._applyColumnMinimumWidthsOnly()
        else:
            self._fitColumnsToViewport()
            self._freeze_column_widths = True

    def applyColumnWidths(self, widths_dict):
        """Apply saved column widths without shrinking to the viewport."""
        widths_dict = self._sanitizeColumnWidths(widths_dict)
        if not widths_dict:
            return
        min_w = self.MIN_PERSISTED_COLUMN_WIDTH
        for col, key in enumerate(self.COLUMN_WIDTH_KEYS):
            if col >= self._source_model.columnCount():
                break
            w = widths_dict.get(key)
            if (
                w is not None
                and isinstance(w, (int, float))
                and int(w) >= min_w
            ):
                self._table.setColumnWidth(col, int(w))
        self._freeze_column_widths = True
        self._applyColumnMinimumWidthsOnly()

    def getColumnWidths(self):
        """Return column widths for persistence (all visible logical columns)."""
        min_w = self.MIN_PERSISTED_COLUMN_WIDTH
        return {
            key: self._table.columnWidth(col)
            for col, key in enumerate(self.COLUMN_WIDTH_KEYS)
            if col < self._source_model.columnCount()
            and self._table.columnWidth(col) >= min_w
        }

    # --------------------------------------------------------
    # Method: _connectSignals
    # --------------------------------------------------------
    def _connectSignals(self):
        self._btn_back.clicked.connect(self.goBack)
        self._btn_forward.clicked.connect(self.goForward)
        self._btn_up.clicked.connect(self.goUp)
        self._btn_new_folder.clicked.connect(self.createNewFolder)
        self._path_edit.returnPressed.connect(self._onPathEdited)
        self._filter_edit.textChanged.connect(self._onFilterChanged)
        self._table.doubleClicked.connect(self._onItemDoubleClicked)
        self._table.filesDropped.connect(self._onFilesDropped)
        self._table.panelPressed.connect(self.activated.emit)
        self._table.slowClickRenameRequested.connect(self.startRename)
        self._table.emptyAreaPressed.connect(self.activated.emit)

        selection_model = self._table.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self._onSelectionChanged)

        self._source_model.modelReset.connect(self._updateStatusLabel)
        self._source_model.recursiveScanAbortRequested.connect(
            self._cancelRecursiveScanThread
        )
        self._source_model.recursiveScanRequested.connect(self._onRecursiveScanRequested)

        self._table.viewportResized.connect(self._onTableViewportResized)
        self._table.horizontalHeader().sectionResized.connect(self._onColumnSectionResized)
        QTimer.singleShot(0, self.relayoutColumns)

    def _onColumnSectionResized(self, _logical_index, _old_size, _new_size):
        if self._column_width_clamping:
            return
        self._freeze_column_widths = True
        self._applyColumnMinimumWidthsOnly()
        self._column_width_save_timer.start()

    # --------------------------------------------------------
    # Method: _installActivationEventFilters
    # Purpose: Makes clicks and focus on panel chrome activate
    #          the panel even when no file is selected.
    # --------------------------------------------------------
    def _installActivationEventFilters(self):
        activation_widgets = [
            self._path_edit,
            self._filter_edit,
            self._btn_copy_path,
            self._btn_paste_path,
            self._btn_browse_folder,
            self._btn_back,
            self._btn_forward,
            self._btn_up,
            self._btn_home,
            self._btn_filter_options,
            self._btn_new_folder,
            self._drive_combo,
            self._drive_arrow,
            self._table.horizontalHeader(),
        ]

        combo_line_edit = self._drive_combo.lineEdit()
        if combo_line_edit is not None:
            activation_widgets.append(combo_line_edit)

        for widget in activation_widgets:
            widget.installEventFilter(self)

    # --------------------------------------------------------
    # Method: _scrollFileTableToTop
    # Purpose: Resets vertical (and horizontal) scroll after
    #          opening a folder so the list starts at the top.
    # --------------------------------------------------------
    def _scrollFileTableToTop(self):
        self._table.scrollToTop()
        hbar = self._table.horizontalScrollBar()
        if hbar is not None:
            hbar.setValue(0)

    # --------------------------------------------------------
    # Method: navigateTo
    # Purpose: Loads a directory and pushes it to the history.
    # --------------------------------------------------------
    def navigateTo(self, path, add_to_history=True):
        """Returns True when the folder was opened."""
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            return False

        if self.isRenaming():
            self._commitRename()
        self._table.cancelPendingRename()

        if add_to_history:
            if self._history_index >= 0 and self._history_index < len(self._history) - 1:
                self._history = self._history[:self._history_index + 1]
            self._history.append(path)
            self._history_index = len(self._history) - 1

        self._source_model.loadDirectory(path)
        self._path_edit.setText(path)
        self._updateNavButtons()
        self._updateStatusLabel()
        self._syncDriveCombo(path)
        self._watchCurrentFolder()
        self.pathChanged.emit(path)
        QTimer.singleShot(0, self._scrollFileTableToTop)
        return True

    # --------------------------------------------------------
    # Method: refresh
    # Purpose: Reloads the current directory. force_rescan skips
    #          the recursive scan cache (used by F5 / banner Refresh).
    #          Rows selected before the reload stay selected.
    # --------------------------------------------------------
    def refresh(self, force_rescan=True):
        current = self._source_model.currentPath()
        if current:
            selected = self.selectedPaths()
            # Invalidate cache when the user explicitly forces a rescan.
            if force_rescan and self._source_model.isRecursive():
                try:
                    from scan_cache import invalidateScanCache

                    invalidateScanCache(
                        current, self._source_model.showHiddenFiles()
                    )
                except Exception:
                    pass
            self._source_model.loadDirectory(current, force_rescan=force_rescan)
            self._reselectPaths(selected)
            self._updateStatusLabel()

    # --------------------------------------------------------
    # Method: setAutoRefreshEnabled
    # Purpose: Turn the folder watcher on or off. When it is on,
    #          a change made outside the app reloads this panel.
    # --------------------------------------------------------
    def setAutoRefreshEnabled(self, enabled):
        if enabled:
            self._watchCurrentFolder()
            return
        self._auto_refresh_timer.stop()
        self._auto_refresh_deferred = False
        self._clearDirectoryWatch()

    # --------------------------------------------------------
    # Method: _autoRefreshEnabled
    # Purpose: The setting defaults to on. Panels with no
    #          settings manager follow that default.
    # --------------------------------------------------------
    def _autoRefreshEnabled(self):
        if self._settings_manager is None:
            return True
        return bool(self._settings_manager.getSetting("auto_refresh_panels", True))

    # --------------------------------------------------------
    # Method: _watchCurrentFolder
    # Purpose: Watch only the folder open in this panel.
    #          Subfolders are not watched; a tree watch is
    #          too expensive, and the scan cache is marked
    #          stale instead.
    # --------------------------------------------------------
    def _watchCurrentFolder(self):
        if not self._autoRefreshEnabled():
            self._clearDirectoryWatch()
            return
        current = self._source_model.currentPath()
        if not current or not os.path.isdir(current):
            self._clearDirectoryWatch()
            return
        self._setWatchedDirectory(current)

    def _clearDirectoryWatch(self):
        watched = list(self._dir_watcher.directories())
        if watched:
            self._dir_watcher.removePaths(watched)

    def _setWatchedDirectory(self, path):
        wanted = os.path.normpath(path)
        wanted_key = os.path.normcase(wanted)
        for watched in list(self._dir_watcher.directories()):
            try:
                same = os.path.normcase(os.path.normpath(watched)) == wanted_key
            except (OSError, ValueError):
                same = False
            if not same:
                self._dir_watcher.removePath(watched)
        still = False
        for watched in self._dir_watcher.directories():
            try:
                if os.path.normcase(os.path.normpath(watched)) == wanted_key:
                    still = True
                    break
            except (OSError, ValueError):
                continue
        if not still:
            self._dir_watcher.addPath(wanted)

    # --------------------------------------------------------
    # Method: _onWatchedDirectoryChanged
    # Purpose: Coalesce a burst of changes, then reload.
    #          Windows sometimes drops the watch after an
    #          event, so the folder is added again.
    # --------------------------------------------------------
    def _onWatchedDirectoryChanged(self, path):
        if not self._autoRefreshEnabled():
            return
        current = self._source_model.currentPath()
        if current and os.path.isdir(current):
            self._setWatchedDirectory(current)
        elif path and os.path.isdir(path):
            self._setWatchedDirectory(path)
        self._auto_refresh_timer.start()

    # --------------------------------------------------------
    # Method: _renameInProgress
    # Purpose: True while the inline rename field exists.
    #          A reload would throw away the name being typed.
    # --------------------------------------------------------
    def _renameInProgress(self):
        return self._rename_edit is not None

    # --------------------------------------------------------
    # Method: _applyPendingAutoRefresh
    # Purpose: Reload the open folder after outside changes.
    #          The selection and the vertical scroll stay put.
    #          In Subfolders mode the tree is not walked again;
    #          the saved scan is dropped so the next Refresh
    #          reads the disk.
    # --------------------------------------------------------
    def _applyPendingAutoRefresh(self):
        if self._renameInProgress():
            self._auto_refresh_deferred = True
            return
        self._auto_refresh_deferred = False
        if not self._autoRefreshEnabled():
            return
        current = self._source_model.currentPath()
        if not current or not os.path.isdir(current):
            return
        if self._source_model.isRecursive():
            try:
                from scan_cache import invalidateScanCache

                invalidateScanCache(
                    current, self._source_model.showHiddenFiles()
                )
            except Exception:
                pass
            return

        bar = self._table.verticalScrollBar()
        scroll_value = bar.value() if bar is not None else 0

        self.refresh(force_rescan=False)

        if bar is None:
            return

        def restoreScroll():
            bar.setValue(min(scroll_value, bar.maximum()))

        restoreScroll()
        QTimer.singleShot(0, restoreScroll)

    # --------------------------------------------------------
    # Method: _reselectPaths
    # Purpose: Select the visible rows whose full_path is in paths.
    # --------------------------------------------------------
    def _reselectPaths(self, paths):
        if not paths:
            return
        wanted = {os.path.normcase(os.path.normpath(p)) for p in paths}
        selection = QItemSelection()
        for row in range(self._source_model.rowCount()):
            entry = self._source_model.entryAt(row)
            if not entry or os.path.normcase(os.path.normpath(entry["full_path"])) not in wanted:
                continue
            proxy_index = self._proxy_model.mapFromSource(self._source_model.index(row, 0))
            if proxy_index.isValid():
                selection.select(proxy_index, proxy_index)
        if not selection.isEmpty():
            self._table.selectionModel().select(
                selection,
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
            )

    # --------------------------------------------------------
    # Method: applyTransferResult
    # Purpose: After a successful copy/move/delete, patch the
    #          in-memory listing when possible (esp. Subfolders).
    # Output: "updated" | "unaffected" | "fallback"
    # --------------------------------------------------------
    def applyTransferResult(self, task):
        from file_operations import FileOperationWorker

        if task is None:
            return "fallback"
        op = getattr(task, "operation", "")
        sources = list(getattr(task, "source_paths", None) or [])
        dest_dir = getattr(task, "destination", "") or ""
        rels = getattr(task, "relative_paths", None)
        root = self.currentPath()
        if not root:
            return "unaffected"

        root_norm = os.path.normpath(root)

        def under_root(path):
            if not path:
                return False
            p = os.path.normcase(os.path.normpath(path))
            r = os.path.normcase(root_norm)
            return p == r or p.startswith(r + os.sep)

        dest_paths = []
        if dest_dir and op in (
            FileOperationWorker.OPERATION_COPY,
            FileOperationWorker.OPERATION_MOVE,
        ):
            if rels and len(rels) == len(sources):
                dest_paths = [
                    os.path.normpath(os.path.join(dest_dir, r)) for r in rels
                ]
            else:
                dest_paths = [
                    os.path.normpath(os.path.join(dest_dir, os.path.basename(s)))
                    for s in sources
                ]

        model = self._source_model
        if model.isRecursive():
            touched = False
            if op in (
                FileOperationWorker.OPERATION_MOVE,
                FileOperationWorker.OPERATION_DELETE,
            ):
                remove_list = [s for s in sources if under_root(s)]
                if remove_list:
                    model.removeEntriesByPaths(remove_list)
                    touched = True
            if op in (
                FileOperationWorker.OPERATION_COPY,
                FileOperationWorker.OPERATION_MOVE,
            ):
                for i, dp in enumerate(dest_paths):
                    if not under_root(dp):
                        continue
                    if not os.path.exists(dp):
                        return "fallback"
                    rel = None
                    if rels and i < len(rels):
                        # Relative to this panel root when dest is under root.
                        try:
                            rel = os.path.relpath(dp, root_norm).replace("/", os.sep)
                        except ValueError:
                            rel = rels[i]
                    if not model.upsertEntryFromPath(dp, relative_path=rel):
                        return "fallback"
                    touched = True
            if not touched:
                related = any(under_root(s) for s in sources)
                related = related or (dest_dir and under_root(dest_dir))
                related = related or any(under_root(d) for d in dest_paths)
                if related:
                    return "fallback"
                return "unaffected"
            self._proxy_model.invalidateFilter()
            self._updateFilterUi()
            return "updated"

        # Flat listing: cheap listdir refresh when this folder is involved.
        root_case = os.path.normcase(root_norm)
        dest_case = os.path.normcase(os.path.normpath(dest_dir)) if dest_dir else ""
        if dest_case and dest_case == root_case:
            self.refresh(force_rescan=False)
            return "updated"
        if op in (
            FileOperationWorker.OPERATION_MOVE,
            FileOperationWorker.OPERATION_DELETE,
        ):
            for s in sources:
                try:
                    parent = os.path.normcase(os.path.normpath(os.path.dirname(s)))
                except Exception:
                    continue
                if parent == root_case:
                    self.refresh(force_rescan=False)
                    return "updated"
        # Structure copy into this folder creates new top-level children.
        if dest_case == root_case or (
            dest_paths and any(
                os.path.normcase(os.path.normpath(os.path.dirname(d))) == root_case
                for d in dest_paths
            )
        ):
            self.refresh(force_rescan=False)
            return "updated"
        return "unaffected"

    # --------------------------------------------------------
    # Method: createNewFolder
    # Purpose: Prompts for a name and creates a subfolder in this
    #          panel's current directory (same behavior as F8 for
    #          the active panel).
    # --------------------------------------------------------
    def createNewFolder(self):
        current_path = self.currentPath()
        if not current_path:
            return
        dlg_parent = self.window()
        name, ok = QInputDialog.getText(
            dlg_parent, "New Folder", "Folder name:",
        )
        if not ok or not name.strip():
            return
        folder_name = name.strip()
        new_path = os.path.join(current_path, folder_name)
        try:
            os.makedirs(new_path, exist_ok=True)
            self.refresh()
            self.folderCreated.emit(folder_name)
        except OSError as e:
            QMessageBox.warning(
                dlg_parent, "Error", f"Could not create folder:\n{e}"
            )

    # --------------------------------------------------------
    # Method: currentPath
    # --------------------------------------------------------
    def currentPath(self):
        return self._source_model.currentPath()

    # --------------------------------------------------------
    # Method: selectedEntries
    # Purpose: Returns a list of entry dicts for selected rows.
    # --------------------------------------------------------
    def selectedEntries(self):
        entries = []
        for index in self._table.selectionModel().selectedRows():
            source_index = self._proxy_model.mapToSource(index)
            entry = self._source_model.entryAt(source_index.row())
            if entry:
                entries.append(entry)
        return entries

    # --------------------------------------------------------
    # Method: selectedPaths
    # Purpose: Returns a list of full paths for selected items.
    # --------------------------------------------------------
    def selectedPaths(self):
        return [e["full_path"] for e in self.selectedEntries()]

    # --------------------------------------------------------
    # Method: primaryFileEntry
    # Purpose: The file the viewer and the editor should open.
    #          Uses the first selected file. A selected folder
    #          is not a file, so this returns None.
    # --------------------------------------------------------
    def primaryFileEntry(self):
        for entry in self.selectedEntries():
            if entry and not entry.get("is_dir"):
                return entry
        return None

    # --------------------------------------------------------
    # Method: selectAdjacentFile
    # Purpose: Move the selection to the next or previous
    #          visible file, skipping folders. Used by the
    #          viewer (N / P).
    # Input: step (int) - 1 for next, -1 for previous.
    # Output: entry dict, or None at the end of the list.
    # --------------------------------------------------------
    def selectAdjacentFile(self, step):
        step = 1 if step >= 0 else -1
        proxy = self._proxy_model
        count = proxy.rowCount()
        if count <= 0:
            return None

        current = -1
        selected = self._table.selectionModel().selectedRows()
        if selected:
            current = selected[0].row()
        elif self._table.currentIndex().isValid():
            current = self._table.currentIndex().row()

        if current < 0:
            row = 0 if step > 0 else count - 1
        else:
            row = current + step

        while 0 <= row < count:
            source_index = proxy.mapToSource(proxy.index(row, 0))
            entry = self._source_model.entryAt(source_index.row())
            if entry and not entry.get("is_dir"):
                self._table.selectRow(row)
                self._table.scrollTo(proxy.index(row, 0))
                return entry
            row += step
        return None

    # --------------------------------------------------------
    # Method: selectedTransferSpecs
    # Purpose: Full path + relative path (from panel root) for
    #          each selected entry. In Subfolders mode, entry
    #          "name" is already relative; otherwise basename.
    # Output: list of {"full_path", "relative_path"} or error str.
    # --------------------------------------------------------
    def selectedTransferSpecs(self):
        root = self.currentPath()
        if not root:
            return [], "No folder open in this panel."
        root_norm = os.path.normcase(os.path.normpath(root))
        specs = []
        for entry in self.selectedEntries():
            full = entry.get("full_path") or ""
            if not full:
                continue
            full_norm = os.path.normpath(full)
            name = (entry.get("name") or "").replace("/", os.sep).strip()
            if self._source_model.isRecursive() and name:
                rel = name
            else:
                try:
                    rel = os.path.relpath(full_norm, root)
                except ValueError:
                    return [], f"Path is outside the panel folder:\n{full}"
                rel = rel.replace("/", os.sep)
            parts = [p for p in rel.split(os.sep) if p and p != "."]
            if not parts or ".." in parts or rel in (".", ""):
                return [], f"Invalid relative path for:\n{full}"
            # Ensure the absolute path is under the search root.
            try:
                common = os.path.commonpath([root_norm, os.path.normcase(full_norm)])
            except ValueError:
                return [], f"Path is outside the panel folder:\n{full}"
            if common != root_norm:
                return [], f"Path is outside the panel folder:\n{full}"
            specs.append({
                "full_path": full_norm,
                "relative_path": os.path.join(*parts),
            })
        if not specs:
            return [], "No files selected."
        return specs, ""

    # --------------------------------------------------------
    # Navigation Methods
    # --------------------------------------------------------
    def goBack(self):
        self._stepHistory(-1)

    def goForward(self):
        self._stepHistory(1)

    # --------------------------------------------------------
    # Method: _stepHistory
    # Purpose: Move back (-1) or forward (1) to the nearest history
    #          entry that still opens. The index only changes on a
    #          successful load, so it always matches the listing.
    # --------------------------------------------------------
    def _stepHistory(self, step):
        index = self._history_index + step
        while 0 <= index < len(self._history):
            if self.navigateTo(self._history[index], add_to_history=False):
                self._history_index = index
                self._updateNavButtons()
                return
            index += step

    def goUp(self):
        current = self._source_model.currentPath()
        if current:
            parent = os.path.dirname(current)
            if parent and parent != current:
                self.navigateTo(parent)

    # --------------------------------------------------------
    # Active State
    # --------------------------------------------------------
    def setActive(self, active):
        self._is_active = active
        self._updateFrameStyle()
        if not active:
            self._table.cancelPendingRename()
            if self.isRenaming():
                self._commitRename()

    def isActive(self):
        return self._is_active

    def panelSide(self):
        return self._panel_side

    # --------------------------------------------------------
    # Show / Hide Hidden Files
    # --------------------------------------------------------
    def setShowHidden(self, show):
        self._source_model.setShowHidden(show)

    # --------------------------------------------------------
    # In-Place Rename
    #
    # Triggered by:
    #   - F2 key or toolbar/menu "Rename"
    #   - Slow-click (click on already-selected file after delay)
    #
    # Behavior:
    #   - Enter  → commits the rename
    #   - Escape → cancels the rename
    #   - Click outside (focus lost) → commits the rename
    #   - Selects just the filename stem (not the extension)
    # --------------------------------------------------------
    def isRenaming(self):
        return self._rename_edit is not None and self._rename_edit.isVisible()

    def startRename(self):
        if self._rename_edit is not None:
            self._dismissRenameEditor()

        indexes = self._table.selectionModel().selectedRows()
        if len(indexes) != 1:
            return
        proxy_index = indexes[0]
        name_index = self._proxy_model.index(proxy_index.row(), 0)
        source_index = self._proxy_model.mapToSource(proxy_index)
        entry = self._source_model.entryAt(source_index.row())
        if entry is None:
            return

        self._rename_committed = False
        self._rename_source_row = source_index.row()
        self._rename_old_name = entry["name"]
        self._rename_old_full_path = entry["full_path"]

        self._table.setRenamingRow(proxy_index.row())

        self._rename_edit = _RenameLineEdit(self._table.viewport())
        self._rename_edit.setObjectName("panelRenameEdit")
        self._rename_edit.setAttribute(Qt.WA_StyledBackground, True)
        rect = self._table.visualRect(name_index)
        icon_offset = 28
        self._rename_edit.setGeometry(
            rect.x() + icon_offset, rect.y(),
            rect.width() - icon_offset, rect.height()
        )
        self._rename_edit.setText(entry["name"])

        name_part = os.path.basename(entry["name"])
        dot_pos = name_part.rfind(".")
        if dot_pos > 0 and not entry["is_dir"]:
            self._rename_edit.setSelection(0, dot_pos)
        else:
            self._rename_edit.selectAll()

        self._rename_edit.enterPressed.connect(self._commitRename)
        self._rename_edit.escapePressed.connect(self._cancelRename)
        self._rename_edit.focusLostSignal.connect(self._commitRename)

        self._rename_edit.setFocus()
        self._rename_edit.raise_()
        self._rename_edit.show()

    # --------------------------------------------------------
    # Method: commitRename  (public so the main window can
    #         call it when Enter is pressed at window level)
    # Purpose: Applies the new name. If a file with the same
    #          name already exists, auto-increments the name
    #          (e.g. "file (1).txt", "file (2).txt").
    # --------------------------------------------------------
    def commitRename(self):
        self._commitRename()

    def _commitRename(self):
        if self._rename_edit is None or self._rename_committed:
            return
        self._rename_committed = True
        new_name = self._rename_edit.text().strip()
        self._dismissRenameEditor()

        if not new_name or new_name == self._rename_old_name:
            return

        current_dir = self._source_model.currentPath()
        old_path = getattr(self, "_rename_old_full_path", None) or path_under_root(
            current_dir, self._rename_old_name
        )
        new_path = path_under_root(current_dir, new_name)

        if os.path.exists(new_path) and os.path.normcase(new_path) != os.path.normcase(old_path):
            parent = os.path.dirname(new_path)
            base = os.path.basename(new_path)
            new_base = self._resolveNameConflict(parent, base)
            new_path = os.path.join(parent, new_base)
            try:
                new_name = os.path.relpath(new_path, current_dir)
            except ValueError:
                new_name = new_base

        try:
            os.rename(old_path, new_path)
            self._source_model.renameEntry(self._rename_source_row, new_name)
        except OSError as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Rename Failed", str(e))

    # --------------------------------------------------------
    # Method: _resolveNameConflict
    # Purpose: If new_name already exists in the directory,
    #          appends an incrementing number until unique.
    #          e.g. "report.txt" → "report (1).txt"
    # --------------------------------------------------------
    def _resolveNameConflict(self, directory, name):
        base, ext = os.path.splitext(name)
        counter = 1
        candidate = name
        while os.path.exists(os.path.join(directory, candidate)):
            candidate = f"{base} ({counter}){ext}"
            counter += 1
        return candidate

    # --------------------------------------------------------
    # Method: _cancelRename
    # Purpose: Called only on Escape. Discards edits.
    # --------------------------------------------------------
    def _cancelRename(self):
        if self._rename_committed:
            return
        self._rename_committed = True
        self._dismissRenameEditor()

    # --------------------------------------------------------
    # Method: _dismissRenameEditor
    # Purpose: Safely hides and destroys the inline editor.
    # --------------------------------------------------------
    def _dismissRenameEditor(self):
        if self._rename_edit is not None:
            self._rename_edit.hide()
            self._rename_edit.deleteLater()
            self._rename_edit = None
        self._table.setRenamingRow(-1)
        if self._auto_refresh_deferred:
            self._auto_refresh_timer.start()

    # --------------------------------------------------------
    # History / State for Persistence
    # --------------------------------------------------------
    def getHistoryData(self):
        lock_state = self.getColumnWidthLockState()
        return {
            "current_path": self._source_model.currentPath(),
            "history": self._history,
            "history_index": self._history_index,
            "column_widths": self.getColumnWidths(),
            "column_visibility": self.getColumnVisibility(),
            "column_width_locked": lock_state["column_width_locked"],
            "locked_column_widths": lock_state["locked_column_widths"],
            "filter_mode": self._proxy_model.filterMode(),
            "filter_kind": self._proxy_model.entryKindFilter(),
            "filter_text": self._filter_edit.text(),
            "filter_exclude_text": self._proxy_model.filterExcludeText(),
            "filter_extensions": self._proxy_model.filterExtensionsText(),
            "filter_words_combine_and": self._proxy_model.filterWordsCombineAnd(),
            "filter_include_subfolders": self._source_model.isRecursive(),
            "filter_advanced": self._proxy_model.filterSpec().to_dict(),
            "show_thumbnails": self._source_model.showThumbnails(),
        }

    def _historyIndexFromState(self, data, current):
        """
        Restore the Back/Forward position. Prefer the saved index,
        clamped to the history list. Older state files have no index,
        so fall back to the current folder, then the last entry.
        """
        history = self._history if isinstance(self._history, list) else []
        if not history:
            return -1

        raw = data.get("history_index", None)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return max(0, min(raw, len(history) - 1))

        norm_current = os.path.normcase(os.path.normpath(current))
        for index, item in enumerate(history):
            if not isinstance(item, str):
                continue
            try:
                if os.path.normcase(os.path.normpath(item)) == norm_current:
                    return index
            except (OSError, ValueError):
                continue
        return len(history) - 1

    def restoreHistoryData(self, data):
        history = data.get("history", [])
        self._history = history if isinstance(history, list) else []
        self._source_model.setRecursive(
            bool(data.get("filter_include_subfolders", False))
        )

        current = data.get("current_path", "")
        if current and os.path.isdir(current):
            self._history_index = self._historyIndexFromState(data, current)
            self.navigateTo(current, add_to_history=False)
        column_widths = self._sanitizeColumnWidths(data.get("column_widths"))
        if column_widths:
            self.applyColumnWidths(column_widths)
        self.applyColumnWidthLockState(
            {
                "column_width_locked": data.get("column_width_locked"),
                "locked_column_widths": data.get("locked_column_widths"),
            }
        )
        column_visibility = self._sanitizeColumnVisibility(data.get("column_visibility"))
        if column_visibility:
            self.applyColumnVisibility(column_visibility)
        else:
            self._fitColumnsToViewport()
            self._freeze_column_widths = True
        fm = data.get("filter_mode")
        if fm in ("contains", "wildcard", "regex"):
            self._proxy_model.setFilterMode(fm)
        fk = data.get("filter_kind")
        if fk in ("all", "dirs", "files"):
            self._proxy_model.setEntryKindFilter(fk)
        self._filter_edit.blockSignals(True)
        self._filter_edit.setText(data.get("filter_text") or "")
        self._filter_edit.blockSignals(False)
        self._proxy_model.setFilterText(self._filter_edit.text())
        self._proxy_model.setFilterExcludeText(data.get("filter_exclude_text") or "")
        self._proxy_model.setFilterExtensionsText(data.get("filter_extensions") or "")
        if "filter_words_combine_and" in data:
            self._proxy_model.setFilterWordsCombineAnd(
                bool(data.get("filter_words_combine_and", True))
            )
        self._proxy_model.setFilterSpec(
            FilterSpec.from_dict(data.get("filter_advanced"))
        )
        self.setShowThumbnails(bool(data.get("show_thumbnails", False)), persist=False)
        self._updateFilterUi()

    # --------------------------------------------------------
    # Focus handling for active panel detection
    # --------------------------------------------------------
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.activated.emit()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.activated.emit()

    # --------------------------------------------------------
    # Event filter: Up/Down in path or filter moves file selection
    # --------------------------------------------------------
    def eventFilter(self, obj, event):
        activation_events = (QEvent.MouseButtonPress, QEvent.FocusIn)
        if event.type() in activation_events and obj in (
            self._path_edit,
            self._filter_edit,
            self._btn_copy_path,
            self._btn_paste_path,
            self._btn_browse_folder,
            self._btn_back,
            self._btn_forward,
            self._btn_up,
            self._btn_home,
            self._btn_filter_options,
            self._btn_new_folder,
            self._drive_combo,
            self._drive_arrow,
            self._table.horizontalHeader(),
            self._drive_combo.lineEdit(),
        ):
            self.activated.emit()

        if event.type() == QEvent.KeyPress and obj in (self._path_edit, self._filter_edit):
            if event.key() == Qt.Key_Up:
                self._table.setFocus()
                self._moveFileSelection(-1)
                return True
            if event.key() == Qt.Key_Down:
                self._table.setFocus()
                self._moveFileSelection(1)
                return True
        return super().eventFilter(obj, event)

    # --------------------------------------------------------
    # Method: _moveFileSelection
    # Purpose: Moves the current selection up or down by one row.
    #          direction: -1 = up, 1 = down.
    # --------------------------------------------------------
    def _moveFileSelection(self, direction):
        model = self._table.model()
        row_count = model.rowCount()
        if row_count == 0:
            return
        current = self._table.currentIndex()
        row = current.row() if current.isValid() else 0
        new_row = max(0, min(row_count - 1, row + direction))
        new_index = model.index(new_row, 0)
        self._table.setCurrentIndex(new_index)
        self._table.selectionModel().select(
            new_index,
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
        )
        self._table.scrollTo(new_index, QAbstractItemView.PositionAtCenter)

    # --------------------------------------------------------
    # Internal Slots
    # --------------------------------------------------------
    def _onPathEdited(self):
        path = normalizePathInput(self._path_edit.text())
        if path and os.path.isdir(path):
            self.navigateTo(path)

    def _copyPathToClipboard(self):
        """Copy current folder path to clipboard."""
        path = self._source_model.currentPath()
        if path:
            clipboard = QApplication.clipboard()
            clipboard.setText(path)
            self.pathCopied.emit(path)

    def _pastePathAndNavigate(self):
        """Paste path from clipboard and navigate to that folder."""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        path = normalizePathInput(text)
        if not path:
            return
        if os.path.isdir(path):
            self._path_edit.setText(path)
            self.navigateTo(path)
        elif os.path.isfile(path):
            parent = os.path.dirname(path)
            if parent and os.path.isdir(parent):
                self._path_edit.setText(parent)
                self.navigateTo(parent)

    def _openCurrentFolderInSystemExplorer(self):
        """Open this panel's current folder in the OS file manager (no dialog)."""
        path = self._source_model.currentPath()
        if not path or not os.path.isdir(path):
            return
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", os.path.normpath(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except OSError:
            pass

    def _onDriveChanged(self, index):
        if index < 0 or not self._drive_combo.isVisible():
            return
        drive = self._drive_combo.currentText()
        if drive and os.path.isdir(drive):
            self.navigateTo(drive)

    def _onDriveArrowClicked(self, event):
        if self._drive_combo.isVisible():
            self._drive_combo.showPopup()

    def _refreshDrives(self):
        """Re-scan for drives (USB, external disks) and update the dropdown.

        On Windows, called automatically when the drive menu is opened.
        """
        if not self._drive_combo.isVisible() and os.name != "nt":
            return
        drives = getWindowsDrives()
        self._drive_combo.blockSignals(True)
        self._drive_combo.clear()
        if drives:
            self._drive_combo.addItems(drives)
            self._drive_combo.setVisible(True)
            self._drive_arrow.setVisible(True)
            self._syncDriveCombo(self._source_model.currentPath())
        self._drive_combo.blockSignals(False)

    def _syncDriveCombo(self, path):
        """Keep drive dropdown in sync with current path (Windows)."""
        if not self._drive_combo.isVisible():
            return
        path = os.path.normpath(path)
        root, _ = os.path.splitdrive(path)
        if not root:
            return
        drive = (root + "\\") if not root.endswith("\\") else root
        drive_upper = drive.upper()
        for i in range(self._drive_combo.count()):
            if self._drive_combo.itemText(i).upper() == drive_upper:
                self._drive_combo.blockSignals(True)
                self._drive_combo.setCurrentIndex(i)
                self._drive_combo.blockSignals(False)
                break

    def _goHome(self):
        """Navigate to the user's home directory (OS-dependent)."""
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            self.navigateTo(home)

    # --------------------------------------------------------
    # Date Modified column format (settings.json)
    # --------------------------------------------------------
    def currentDateModifiedFormatKey(self):
        return self._source_model.dateModifiedFormatKey()

    def applyDateModifiedFormat(self, format_key, persist=False):
        key = resolve_date_modified_format_key(format_key)
        if persist and self._settings_manager is not None:
            self._settings_manager.setSetting("date_modified_format", key)
            self._settings_manager.saveSettings()
        self._source_model.setDateModifiedFormatKey(key)
        if persist:
            self.dateModifiedFormatChanged.emit(key)

    # --------------------------------------------------------
    # Column header context menu (show/hide columns)
    # --------------------------------------------------------
    def _onTableHeaderContextMenu(self, pos):
        menu = QMenu(self)
        n = self._source_model.columnCount()
        hdr = self._table.horizontalHeader()
        for col in range(n):
            label = FileSystemModel.COLUMNS[col]
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(not self._table.isColumnHidden(col))
            act.toggled.connect(
                lambda checked, c=col, a=act: self._applyColumnVisibilityToggle(c, checked, a)
            )
            menu.addAction(act)
        menu.addSeparator()
        idx = hdr.logicalIndexAt(pos.x())
        if 0 <= idx < n:
            key = self._columnKeyAt(idx)
            if key:
                act_lock = QAction("Lock column width", menu)
                act_lock.setCheckable(True)
                act_lock.setChecked(bool(self._column_width_locked.get(key)))
                act_lock.setToolTip(
                    "When locked, this column keeps its width when you resize other columns "
                    "or the panel."
                )
                act_lock.toggled.connect(
                    lambda checked, col=idx: self._setColumnWidthLock(col, checked)
                )
                menu.addAction(act_lock)
            if key == "date_modified":
                menu.addSeparator()
                fmt_menu = menu.addMenu("Date format")
                fmt_menu.setToolTip(
                    "Date format\n\n"
                    "How dates appear in the Date Modified column. Saved in settings."
                )
                current_fmt = self.currentDateModifiedFormatKey()
                fmt_group = QActionGroup(fmt_menu)
                fmt_group.setExclusive(True)
                for fmt_key, (_, label) in DATE_MODIFIED_FORMATS.items():
                    act_fmt = QAction(label, fmt_menu)
                    act_fmt.setCheckable(True)
                    act_fmt.setChecked(fmt_key == current_fmt)
                    fmt_group.addAction(act_fmt)
                    act_fmt.triggered.connect(
                        lambda checked, k=fmt_key: (
                            self.applyDateModifiedFormat(k, persist=True) if checked else None
                        )
                    )
                    fmt_menu.addAction(act_fmt)
                menu.addSeparator()
        act_even = QAction("Distribute columns evenly", menu)
        act_even.setToolTip(
            "Distribute columns evenly\n\n"
            "Resize all visible columns to the same width so together they fill the panel."
        )
        act_even.triggered.connect(self._distributeColumnsEvenly)
        menu.addAction(act_even)
        menu.exec_(hdr.mapToGlobal(pos))

    def _applyColumnVisibilityToggle(self, col, visible, action):
        if not visible:
            others = sum(
                1
                for c in range(self._source_model.columnCount())
                if c != col and not self._table.isColumnHidden(c)
            )
            if others == 0:
                QMessageBox.information(
                    self,
                    "Columns",
                    "At least one column must stay visible.",
                )
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
                return
        self._table.setColumnHidden(col, not visible)
        self._freeze_column_widths = True
        self._applyColumnMinimumWidthsOnly()

    def _distributeColumnsEvenly(self):
        """Give each unlocked visible column an equal share; locked widths stay fixed."""
        hdr = self._table.horizontalHeader()
        n = self._source_model.columnCount()
        visible = [c for c in range(n) if not self._table.isColumnHidden(c)]
        m = len(visible)
        if m == 0:
            return
        vw = max(1, self._table.viewport().width())
        keys = self.COLUMN_VISIBILITY_KEYS
        locked = set()
        for c in visible:
            k = self._columnKeyAt(c)
            if k and self._column_width_locked.get(k):
                locked.add(c)
        flex = [c for c in visible if c not in locked]
        if not flex:
            self._fitColumnsToViewport()
            self._freeze_column_widths = True
            return
        fixed_sum = sum(max(1, self._table.columnWidth(c)) for c in locked)
        rem = max(1, vw - fixed_sum)
        base = rem // len(flex)
        extra = rem % len(flex)
        self._column_width_clamping = True
        try:
            hdr.blockSignals(True)
            for i, col in enumerate(flex):
                wcol = base + (1 if i < extra else 0)
                self._table.setColumnWidth(col, max(1, wcol))
        finally:
            hdr.blockSignals(False)
            self._column_width_clamping = False
        self._fitColumnsToViewport()
        self._freeze_column_widths = True

    # --------------------------------------------------------
    # Filter options dialog and state
    # --------------------------------------------------------
    def getFilterState(self):
        return {
            "filter_text": self._filter_edit.text(),
            "filter_exclude_text": self._proxy_model.filterExcludeText(),
            "filter_extensions": self._proxy_model.filterExtensionsText(),
            "filter_words_combine_and": self._proxy_model.filterWordsCombineAnd(),
            "filter_mode": self._proxy_model.filterMode(),
            "filter_kind": self._proxy_model.entryKindFilter(),
            "filter_include_subfolders": self._source_model.isRecursive(),
            "filter_advanced": self._proxy_model.filterSpec().to_dict(),
        }

    def applyFilterState(self, data):
        if not data:
            return
        ft = data.get("filter_text") or ""
        self._filter_edit.blockSignals(True)
        self._filter_edit.setText(ft)
        self._filter_edit.blockSignals(False)
        self._proxy_model.setFilterText(ft)
        self._proxy_model.setFilterExcludeText(data.get("filter_exclude_text") or "")
        self._proxy_model.setFilterExtensionsText(data.get("filter_extensions") or "")
        self._proxy_model.setFilterWordsCombineAnd(
            bool(data.get("filter_words_combine_and", True))
        )
        fm = data.get("filter_mode")
        if fm in ("contains", "wildcard", "regex"):
            self._proxy_model.setFilterMode(fm)
        fk = data.get("filter_kind")
        if fk in ("all", "dirs", "files"):
            self._proxy_model.setEntryKindFilter(fk)
        self._proxy_model.setFilterSpec(
            FilterSpec.from_dict(data.get("filter_advanced"))
        )
        sub = bool(data.get("filter_include_subfolders", False))
        if not self._setIncludeSubfolders(sub):
            sub = False
        self._updateFilterUi()

    def clearFilter(self):
        self.applyFilterState({
            "filter_text": "",
            "filter_exclude_text": "",
            "filter_extensions": "",
            "filter_words_combine_and": True,
            "filter_mode": "contains",
            "filter_kind": "all",
            "filter_include_subfolders": False,
            "filter_advanced": {},
        })

    def _onOpenFilterOptions(self):
        from filter_options_dialog import FilterOptionsDialog

        dlg = FilterOptionsDialog(self, self._settings_manager, self)
        dlg.exec_()

    # --------------------------------------------------------
    # Method: refreshFilterSearch
    # Purpose: Re-run the current search: reload the folder listing
    #          (re-scanning subfolders when enabled) and re-apply
    #          proxy filter rules.
    # --------------------------------------------------------
    def refreshFilterSearch(self):
        self.refresh(force_rescan=True)
        self._proxy_model.invalidateFilter()
        self._updateFilterUi()

    # --------------------------------------------------------
    # Method: _setIncludeSubfolders
    # Purpose: Enable or disable recursive listing. Shows a
    #          first-time warning when enabling. Returns False
    #          if the user cancelled the warning (left disabled).
    # --------------------------------------------------------
    def _setIncludeSubfolders(self, enabled):
        enabled = bool(enabled)
        if enabled and not self._source_model.isRecursive() and self._settings_manager:
            if not self._settings_manager.getSetting(
                "subfolders_warning_dismissed", False
            ):
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Subfolders search")
                msg.setText(
                    "When enabled, this panel lists every file and folder under the "
                    "current path. Large locations (for example drive roots) can take a "
                    "long time. A progress window with Cancel appears while scanning."
                )
                cb = QCheckBox("Don't show this again")
                msg.setCheckBox(cb)
                msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
                msg.setDefaultButton(QMessageBox.Ok)
                r = msg.exec_()
                if cb.isChecked():
                    self._settings_manager.setSetting(
                        "subfolders_warning_dismissed", True
                    )
                    self._settings_manager.saveSettings()
                if r != QMessageBox.Ok:
                    self._source_model.setRecursive(False)
                    return False
        self._source_model.setRecursive(enabled)
        return True

    # --------------------------------------------------------
    # Method: _hasActiveFilter
    # Purpose: True when any filter setting differs from the
    #          default (empty name, all kinds, no advanced rules).
    # --------------------------------------------------------
    def _hasActiveFilter(self):
        if (self._filter_edit.text() or "").strip():
            return True
        if (self._proxy_model.filterExcludeText() or "").strip():
            return True
        if (self._proxy_model.filterExtensionsText() or "").strip():
            return True
        if self._proxy_model.filterMode() != "contains":
            return True
        if self._proxy_model.entryKindFilter() != "all":
            return True
        if self._source_model.isRecursive():
            return True
        spec = self._proxy_model.filterSpec()
        if spec is not None and not spec.is_empty():
            return True
        return False

    # --------------------------------------------------------
    # Method: _filterActiveSummary
    # Purpose: Human-readable list of active filter settings.
    # --------------------------------------------------------
    def _filterActiveSummary(self):
        parts = []
        include = (self._filter_edit.text() or "").strip()
        if include:
            parts.append(f'name "{include}"')
        kind = self._proxy_model.entryKindFilter()
        if kind == "files":
            parts.append("files only")
        elif kind == "dirs":
            parts.append("folders only")
        mode = self._proxy_model.filterMode()
        if mode == "wildcard":
            parts.append("wildcard")
        elif mode == "regex":
            parts.append("regex")
        exclude = (self._proxy_model.filterExcludeText() or "").strip()
        if exclude:
            parts.append(f'exclude "{exclude}"')
        extensions = (self._proxy_model.filterExtensionsText() or "").strip()
        if extensions:
            parts.append(f"ext: {extensions}")
        if parse_filter_terms(include):
            if self._proxy_model.filterWordsCombineAnd():
                parts.append("AND words")
            else:
                parts.append("OR words")
        if self._source_model.isRecursive():
            parts.append("subfolders")
        spec = self._proxy_model.filterSpec()
        if spec is not None and not spec.is_empty():
            parts.append("size/date")
        return ", ".join(parts) if parts else "active"

    # --------------------------------------------------------
    # Method: _updateFilterUi
    # Purpose: Placeholder, banner, clear buttons, and highlight
    #          when any filter/search is restricting the list.
    # --------------------------------------------------------
    def _updateFilterUi(self):
        active = self._hasActiveFilter()
        summary = self._filterActiveSummary() if active else ""
        total = self._source_model.rowCount()
        shown = self._proxy_model.rowCount() if active else total
        hidden = max(0, total - shown)

        hint = []
        mode = self._proxy_model.filterMode()
        kind = self._proxy_model.entryKindFilter()
        if mode == "wildcard":
            hint.append("* ?")
        elif mode == "regex":
            hint.append("regex")
        if kind == "dirs":
            hint.append("folders")
        elif kind == "files":
            hint.append("files")
        if self._source_model.isRecursive():
            hint.append("subfolders")
        if self._proxy_model.filterExcludeText().strip():
            hint.append("exclude")
        if self._proxy_model.filterExtensionsText().strip():
            hint.append("ext")
        if parse_filter_terms(self._filter_edit.text()):
            if self._proxy_model.filterWordsCombineAnd():
                hint.append("AND")
            else:
                hint.append("OR")
        spec = self._proxy_model.filterSpec()
        if spec is not None and not spec.is_empty():
            hint.append("size/date")
        extra = (" · " + ", ".join(hint)) if hint else ""
        if active:
            self._filter_edit.setPlaceholderText(f"\u26A0 Filter active{extra}…")
        else:
            self._filter_edit.setPlaceholderText(f"\U0001F50D Filter{extra}…")

        self._btn_clear_filter.setVisible(active)
        self._filter_banner.setVisible(active)
        if active:
            if hidden > 0:
                banner = (
                    f"\u26A0 Filter active ({summary}) — "
                    f"{hidden} item(s) hidden ({shown} of {total} visible)"
                )
            else:
                banner = f"\u26A0 Filter active ({summary})"
            self._filter_banner_label.setText(banner)

        _setDynamicProperty(self._filter_edit, "filterActive", active)
        _setDynamicProperty(self._btn_filter_options, "filterActive", active)
        self._updateStatusLabel()

    def _onFilterChanged(self, text):
        self._proxy_model.setFilterText(text)
        self._updateFilterUi()

    def _onItemDoubleClicked(self, proxy_index):
        source_index = self._proxy_model.mapToSource(proxy_index)
        entry = self._source_model.entryAt(source_index.row())
        if entry is None:
            return
        if entry["is_dir"]:
            self.navigateTo(entry["full_path"])
        else:
            self.fileDoubleClicked.emit(entry)

    def _onFilesDropped(self, file_paths, drop_target, is_copy):
        self.activated.emit()
        self.filesDropped.emit(file_paths, drop_target, is_copy)

    def _onSelectionChanged(self):
        self.selectionChanged.emit()

    def _updateNavButtons(self):
        self._btn_back.setEnabled(self._history_index > 0)
        self._btn_forward.setEnabled(
            self._history_index < len(self._history) - 1
        )
        current = self._source_model.currentPath()
        parent = os.path.dirname(current) if current else ""
        self._btn_up.setEnabled(bool(parent) and parent != current)

    def _updateStatusLabel(self):
        total = self._source_model.rowCount()
        dirs = sum(
            1 for i in range(total)
            if self._source_model.entryAt(i) and self._source_model.entryAt(i)["is_dir"]
        )
        files = total - dirs
        text = f"{files} file(s), {dirs} folder(s)"
        filter_warning = False
        if self._hasActiveFilter():
            shown = self._proxy_model.rowCount()
            hidden = max(0, total - shown)
            if hidden > 0:
                filter_warning = True
                text = (
                    f"\u26A0 {hidden} hidden \u00b7 {shown} shown \u00b7 "
                    f"{files} file(s), {dirs} folder(s) in folder"
                )
            else:
                text = f"Filter on \u00b7 {text}"
        if self._source_model.isRecursive():
            if self._source_model.listingFromCache():
                text += "  \u00b7  Subfolders (cached)"
            elif self._source_model.quietScanPending():
                text += "  \u00b7  Subfolders (updating\u2026)"
            else:
                text += "  \u00b7  Subfolders scan"
        load_error = self._source_model.loadError()
        if load_error:
            text = f"\u26A0 Cannot read folder: {load_error}"
            filter_warning = True
        self._status_label.setText(text)
        _setDynamicProperty(self._status_label, "filterWarning", filter_warning)

    # --------------------------------------------------------
    # Recursive subfolder scan (background thread + progress)
    # --------------------------------------------------------
    def _closeScanProgress(self):
        if self._scan_progress is not None:
            self._scan_progress.close()
            self._scan_progress.deleteLater()
            self._scan_progress = None

    def _cancelRecursiveScanThread(self):
        self._closeScanProgress()
        if self._scan_thread is None:
            return
        thr = self._scan_thread
        if thr.isRunning():
            thr.cancel()
            thr.wait(120000)
        QApplication.processEvents()
        thr.deleteLater()
        self._scan_thread = None

    def _onRecursiveScanRequested(self, path, gen):
        quiet = self._source_model.quietScanPending()
        self._cancelRecursiveScanThread()
        if not quiet:
            self._scan_progress = QProgressDialog(self)
            self._scan_progress.setWindowTitle("Scanning subfolders")
            self._scan_progress.setLabelText("Starting…")
            self._scan_progress.setCancelButtonText("Cancel")
            self._scan_progress.setRange(0, 0)
            self._scan_progress.setMinimumDuration(0)
            self._scan_progress.setWindowModality(Qt.WindowModal)
            self._scan_progress.canceled.connect(self._onScanProgressCanceled)

        self._scan_thread = RecursiveScanThread(
            gen,
            path,
            self._source_model.showHiddenFiles(),
            self,
        )
        self._scan_thread.progress.connect(self._onRecursiveScanProgress)
        self._scan_thread.finishedScan.connect(self._onRecursiveScanFinished)
        self._scan_thread.scanCancelled.connect(self._onRecursiveScanCancelled)
        self._scan_thread.start()
        if quiet:
            self._updateStatusLabel()

    def _onScanProgressCanceled(self):
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.cancel()

    def _onRecursiveScanProgress(self, count, current_dir):
        if self._scan_progress is None:
            return
        short = current_dir
        if len(short) > 70:
            short = "…" + short[-67:]
        self._scan_progress.setLabelText(
            f"{count} items scanned\n{short}"
        )

    def _onRecursiveScanFinished(self, gen, entries):
        if gen != self._source_model._scan_generation:
            return
        self._closeScanProgress()
        self._source_model.applyRecursiveScanResult(gen, entries)
        self._proxy_model.invalidateFilter()
        self._updateFilterUi()
        thr = self._scan_thread
        self._scan_thread = None
        if thr is not None:
            thr.deleteLater()

    def _restoreCachedListingAfterCancel(self):
        """Put the last cached subfolder listing back when a scan is cancelled."""
        if self._source_model.listingFromCache():
            return
        path = self._source_model.currentPath()
        if not path:
            return
        try:
            from scan_cache import getScanCache

            cached = getScanCache(path, self._source_model.showHiddenFiles())
        except Exception:
            cached = None
        if cached is not None:
            self._source_model.loadDirectory(path, force_rescan=False)

    def _onRecursiveScanCancelled(self, gen):
        if gen != self._source_model._scan_generation:
            return
        self._closeScanProgress()
        # Quiet reconcile cancel: keep cached listing visible.
        if self._source_model.listingFromCache():
            self._source_model._quiet_scan = False
        else:
            self._restoreCachedListingAfterCancel()
        self._updateStatusLabel()
        if self._scan_thread is None:
            return
        thr = self._scan_thread
        self._scan_thread = None
        thr.deleteLater()

    def _updateFrameStyle(self):
        if self._is_active:
            self.setObjectName("filePanelActive")
        else:
            self.setObjectName("filePanel")
        style = self.style()
        if style is not None:
            for w in (self, self._path_edit, self._table):
                style.unpolish(w)
                style.polish(w)
        self.update()

    # --------------------------------------------------------
    # Public accessors for child widgets (used by main window)
    # --------------------------------------------------------
    def tableView(self):
        return self._table

    def sourceModel(self):
        return self._source_model

    def proxyModel(self):
        return self._proxy_model

    def pathEdit(self):
        return self._path_edit

    def filterEdit(self):
        return self._filter_edit
