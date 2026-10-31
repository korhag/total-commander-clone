"""
Total Commander Clone - File list icons

Nine icons are cut from the sheet in icons/. Folders are drawn and
filled with the theme accent, because the folder on that sheet is a
cropped white block.
"""

import os
import sys

from PyQt5.QtCore import Qt, QFileInfo, QRectF
from PyQt5.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QFileIconProvider

from theme import themeColor


# ------------------------------------------------------------
# Sheet layout (pixels on Flat Vector File Icon Set Strip.png).
# The first cell is the broken folder and is not used.
# ------------------------------------------------------------
_STRIP_NAME = "Flat Vector File Icon Set Strip.png"
_STRIP_Y = (220, 510)
_STRIP_CELLS = (
    ("archive", 261, 462),
    ("image", 469, 669),
    ("video", 676, 877),
    ("audio", 884, 1085),
    ("cad", 1091, 1293),
    ("sheet", 1299, 1500),
    ("document", 1507, 1708),
    ("pdf", 1715, 1916),
    ("file", 1923, 2124),
)

_ICON_PX = 64
_DEFAULT_ACCENT = "#89b4fa"

_EXTENSIONS = {
    "archive": (
        ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".txz",
        ".bz2", ".iso", ".tar.gz", ".tar.xz", ".tar.bz2",
    ),
    "image": (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
        ".tif", ".tiff",
    ),
    "video": (
        ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".mpg", ".mpeg",
    ),
    "audio": (
        ".mp3", ".flac", ".wav", ".ogg", ".aac", ".m4a",
    ),
    "cad": (".dwg", ".dxf"),
    "sheet": (".xls", ".xlsx", ".ods", ".csv"),
    "document": (".doc", ".docx", ".odt", ".rtf"),
    "pdf": (".pdf",),
}

_KIND_BY_EXT = {
    ext: kind
    for kind, exts in _EXTENSIONS.items()
    for ext in exts
}

_pixmaps = {}
_sheet_loaded = False
_strip_override = None
_accent = ""
_folder_icon = None
_fallback_provider = None


# ------------------------------------------------------------
# Function: iconsDir
# Purpose: Folder that holds the sheet. Dev uses the project
#          directory. A frozen build looks in the bundle first.
# ------------------------------------------------------------
def iconsDir():
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = os.path.join(meipass, "icons")
        if os.path.isdir(bundled):
            return bundled
    if getattr(sys, "frozen", False):
        beside_exe = os.path.join(os.path.dirname(sys.executable), "icons")
        if os.path.isdir(beside_exe):
            return beside_exe
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


# ------------------------------------------------------------
# Function: iconKind
# Purpose: Which picture a name uses. Folders are their own kind.
# ------------------------------------------------------------
def iconKind(name, is_dir=False):
    if is_dir:
        return "folder"
    return _KIND_BY_EXT.get(_suffix(name), "file")


# ------------------------------------------------------------
# Function: setAccent
# Purpose: Theme color for folders. Returns True when it changed,
#          so the lists can repaint.
# ------------------------------------------------------------
def setAccent(color):
    global _accent, _folder_icon
    text = (color or "").strip() or _DEFAULT_ACCENT
    if text.lower() == _accent.lower() and _folder_icon is not None:
        return False
    _accent = text
    _folder_icon = None
    return True


# ------------------------------------------------------------
# Function: applyThemeAccent
# Purpose: Read the accent from the theme that is on screen.
# ------------------------------------------------------------
def applyThemeAccent():
    return setAccent(themeColor("blue", _DEFAULT_ACCENT))


# ------------------------------------------------------------
# Function: iconFor
# Purpose: Icon for one file or folder. A missing sheet falls
#          back to the system icon and does not raise.
# ------------------------------------------------------------
def iconFor(name, is_dir=False):
    kind = iconKind(name, is_dir=is_dir)
    if kind == "folder":
        return _folderIcon()
    _ensureSheet()
    pixmap = _pixmaps.get(kind)
    if pixmap is not None and not pixmap.isNull():
        return QIcon(pixmap)
    return _systemIcon(name, is_dir)


# ------------------------------------------------------------
# Function: _suffix
# Purpose: Lower-case extension, keeping .tar.gz as one suffix.
# ------------------------------------------------------------
def _suffix(name):
    lower = os.path.basename(name or "").lower()
    for compound in (".tar.gz", ".tar.xz", ".tar.bz2"):
        if lower.endswith(compound):
            return compound
    return os.path.splitext(lower)[1]


def _stripPath():
    if _strip_override:
        return _strip_override
    return os.path.join(iconsDir(), _STRIP_NAME)


def _ensureSheet():
    global _sheet_loaded
    if _sheet_loaded:
        return
    _sheet_loaded = True
    image = QImage(_stripPath())
    if image.isNull():
        return
    y0, y1 = _STRIP_Y
    for kind, x0, x1 in _STRIP_CELLS:
        cell = image.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        _pixmaps[kind] = _fitSquare(_trimAlpha(cell), _ICON_PX)


def _trimAlpha(image):
    """Drop transparent margins so the glyph fills its square."""
    if image.isNull():
        return image
    width = image.width()
    height = image.height()
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            if image.pixelColor(x, y).alpha() > 16:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < min_x or max_y < min_y:
        return image
    return image.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def _fitSquare(image, size):
    if image.isNull() or image.width() < 1 or image.height() < 1:
        return QPixmap()
    scaled = image.scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    canvas = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(0)
    painter = QPainter(canvas)
    painter.drawImage(
        (size - scaled.width()) // 2,
        (size - scaled.height()) // 2,
        scaled,
    )
    painter.end()
    return QPixmap.fromImage(canvas)


def _folderIcon():
    global _folder_icon
    if not _accent:
        applyThemeAccent()
    if _folder_icon is None:
        _folder_icon = QIcon(_drawFolder(_accent or _DEFAULT_ACCENT))
    return _folder_icon


def _drawFolder(color_hex):
    """A closed folder. The tab is a darker shade of the same color."""
    color = QColor(color_hex)
    if not color.isValid():
        color = QColor(_DEFAULT_ACCENT)
    image = QImage(_ICON_PX, _ICON_PX, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(_darken(color, 0.78))
    painter.drawRoundedRect(QRectF(8, 14, 28, 16), 3, 3)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(6, 24, 52, 32), 4, 4)
    painter.end()
    return QPixmap.fromImage(image)


def _darken(color, factor):
    return QColor(
        int(color.red() * factor),
        int(color.green() * factor),
        int(color.blue() * factor),
    )


def _systemIcon(name, is_dir):
    """System icon when the sheet is missing. A blank result becomes a plain page."""
    global _fallback_provider
    if _fallback_provider is None:
        _fallback_provider = QFileIconProvider()
    if is_dir:
        icon = _fallback_provider.icon(QFileIconProvider.Folder)
    else:
        icon = _fallback_provider.icon(QFileInfo(name or "file"))
    if icon is not None and not icon.isNull():
        return icon
    if is_dir:
        return _folderIcon()
    return QIcon(_drawPlainPage())


def _drawPlainPage():
    """A gray page used only when the sheet and the system icon are both missing."""
    image = QImage(_ICON_PX, _ICON_PX, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#d5dae3"))
    painter.drawRoundedRect(QRectF(14, 8, 36, 48), 3, 3)
    painter.setBrush(QColor("#9aa3b2"))
    painter.drawRect(QRectF(14, 40, 36, 16))
    painter.end()
    return QPixmap.fromImage(image)


# ------------------------------------------------------------
# Function: _resetForTests
# Purpose: Drop the cache so a test can point at another strip.
# ------------------------------------------------------------
def _resetForTests():
    global _pixmaps, _sheet_loaded, _strip_override, _accent, _folder_icon
    _pixmaps = {}
    _sheet_loaded = False
    _strip_override = None
    _accent = ""
    _folder_icon = None
