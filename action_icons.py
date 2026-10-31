"""
Total Commander Clone - Toolbar and button icons.

Three sheets live in icons/. Each is 6 columns by 4 rows.
Tiles are recolored to the theme accent. Line icons are
recolored to the theme text color. The choice is saved.
"""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

from file_icons import iconsDir
from theme import themeColor


# ------------------------------------------------------------
# Sheets and the 24 actions, left to right, top to bottom.
# ------------------------------------------------------------
ICON_SET_FILES = {
    "tile": "File Manager Icon Grid.png",
    "line": "Monochrome File Manager Icon Set.png",
    "mixed": "Monochrome File Utility Icon Sprite Sheet.png",
}

ICON_SET_LABELS = (
    ("tile", "Tiles"),
    ("line", "Line"),
    ("mixed", "Mixed"),
)

ACTION_IDS = (
    "copy",
    "move",
    "special",
    "swap",
    "mirror",
    "delete",
    "back",
    "forward",
    "up",
    "home",
    "refresh",
    "new_folder",
    "rename",
    "batch_rename",
    "bookmark",
    "reveal",
    "terminal",
    "settings",
    "copy_path",
    "paste_path",
    "filter",
    "filter_settings",
    "thumbnails",
    "clear",
)

_GRID_COLUMNS = 6
_GRID_ROWS = 4
_ICON_PX = 64
_DEFAULT_SET = "tile"
_DEFAULT_ACCENT = "#89b4fa"
_DEFAULT_TEXT = "#cdd6f4"
_OUTLINE = QColor("#1B1B1B")

_set_id = _DEFAULT_SET
_accent = ""
_text_color = ""
_cache = {}
_sources = {}
# Shapes do not depend on the theme colors, so a new theme only recolors them.
_masks = {}


# ------------------------------------------------------------
# Function: iconSetChoices
# Purpose: (id, label) pairs for the Settings combo.
# ------------------------------------------------------------
def iconSetChoices():
    return ICON_SET_LABELS


# ------------------------------------------------------------
# Function: normalizeIconSet
# Purpose: A known set id, or the default when the saved
#          value is missing or misspelled.
# ------------------------------------------------------------
def normalizeIconSet(value):
    text = str(value or "").strip().lower()
    if text in ICON_SET_FILES:
        return text
    return _DEFAULT_SET


# ------------------------------------------------------------
# Function: setIconSet
# Purpose: Choose which sheet is drawn. Returns True when
#          the choice changed.
# ------------------------------------------------------------
def setIconSet(set_id):
    global _set_id, _cache
    chosen = normalizeIconSet(set_id)
    if chosen == _set_id and _cache:
        return False
    _set_id = chosen
    _cache = {}
    return True


# ------------------------------------------------------------
# Function: setIconColors
# Purpose: Accent fills tiles. Text color tints line icons.
#          Returns True when either color changed.
# ------------------------------------------------------------
def setIconColors(accent, text):
    global _accent, _text_color, _cache
    accent_text = (accent or "").strip() or _DEFAULT_ACCENT
    text_text = (text or "").strip() or _DEFAULT_TEXT
    if (
        accent_text.lower() == _accent.lower()
        and text_text.lower() == _text_color.lower()
        and _cache
    ):
        return False
    _accent = accent_text
    _text_color = text_text
    _cache = {}
    return True


# ------------------------------------------------------------
# Function: applyThemeIconColors
# Purpose: Read accent and text from the theme on screen.
# ------------------------------------------------------------
def applyThemeIconColors():
    return setIconColors(
        themeColor("blue", _DEFAULT_ACCENT),
        themeColor("text", _DEFAULT_TEXT),
    )


# ------------------------------------------------------------
# Function: iconForAction
# Purpose: QIcon for one action. mirrored flips a right arrow
#          so Copy and Move point at the other panel.
# ------------------------------------------------------------
def iconForAction(action_id, mirrored=False):
    image = _coloredImage(action_id, bool(mirrored))
    if image is None or image.isNull():
        return QIcon()
    return QIcon(QPixmap.fromImage(image))


# ------------------------------------------------------------
# Function: _coloredImage
# Purpose: The cached 64 px picture for one action.
# ------------------------------------------------------------
def _coloredImage(action_id, mirrored):
    if action_id not in ACTION_IDS:
        return None
    _ensureColors()
    key = (_set_id, _accent.lower(), _text_color.lower(), action_id, mirrored)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    shape = _shapeFor(action_id)
    if shape is None:
        _cache[key] = QImage()
        return _cache[key]
    if shape[0] == "tile":
        image = _recolorTile(shape[1], shape[2], QColor(_accent))
    else:
        image = _recolorMask(shape[1], QColor(_text_color))
    if mirrored:
        image = image.mirrored(True, False)
    scaled = image.scaled(
        _ICON_PX,
        _ICON_PX,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    _cache[key] = scaled
    return scaled


# ------------------------------------------------------------
# Function: _shapeFor
# Purpose: The color-free parts of one action. A later theme
#          recolors these instead of reading the sheet again.
# ------------------------------------------------------------
def _shapeFor(action_id):
    key = (_set_id, action_id)
    if key in _masks:
        return _masks[key]
    source = _sourceCell(action_id)
    if source is None:
        _masks[key] = None
        return None
    style = _cellStyle(ACTION_IDS.index(action_id))
    if style == "tile":
        shape = _tileShape(source)
    else:
        shape = _lineShape(source, action_id)
    _masks[key] = shape
    return shape


def _ensureColors():
    if not _accent or not _text_color:
        applyThemeIconColors()


def _cellStyle(index):
    if _set_id == "line":
        return "line"
    if _set_id == "mixed" and index >= _GRID_COLUMNS:
        return "line"
    return "tile"


def _sourceCell(action_id):
    return _sourceCellFrom(_set_id, action_id)


def _sourceCellFrom(set_id, action_id):
    cells = _sources.get(set_id)
    if cells is None:
        cells = _loadCells(set_id)
        _sources[set_id] = cells
    return cells.get(action_id)


def _opaqueFraction(image):
    if image is None or image.isNull():
        return 1.0
    width = image.width()
    height = image.height()
    if width < 1 or height < 1:
        return 1.0
    opaque = 0
    step = 2
    for y in range(0, height, step):
        for x in range(0, width, step):
            if image.pixelColor(x, y).alpha() > 20:
                opaque += 1
    samples = ((width + step - 1) // step) * ((height + step - 1) // step)
    return opaque / max(1, samples)


def _loadCells(set_id):
    path = os.path.join(iconsDir(), ICON_SET_FILES[set_id])
    sheet = QImage(path)
    found = {}
    if sheet.isNull():
        return found
    cell_w = sheet.width() // _GRID_COLUMNS
    cell_h = sheet.height() // _GRID_ROWS
    if cell_w < 8 or cell_h < 8:
        return found
    for index, action_id in enumerate(ACTION_IDS):
        col = index % _GRID_COLUMNS
        row = index // _GRID_COLUMNS
        found[action_id] = sheet.copy(col * cell_w, row * cell_h, cell_w, cell_h)
    return found


# ------------------------------------------------------------
# Function: _tileShape
# Purpose: Split a tile into the area that takes the accent
#          and the glyph that stays white with a dark outline.
#          Both are built once and reused for every color.
# ------------------------------------------------------------
def _tileShape(cell):
    """Accent area, plus the white glyph and its dark outline."""
    cell = _fitCell(cell)
    _image, raw, width, height, stride = _raw(cell)
    kind = _classify(raw, width, height, stride)
    outside = _flood(kind, width, height, wall=0)
    clear = QColor(0, 0, 0, 0)
    white = QColor(255, 255, 255)
    accent_mask = _imageFromMarks(
        width, height, kind, outside, white, clear, clear
    )
    glyph = _imageFromMarks(
        width, height, kind, outside, clear, QColor(_OUTLINE), white
    )
    return ("tile", accent_mask, glyph)


def _lineShape(cell, action_id):
    """White strokes. A crowded mixed cell uses the line sheet."""
    mask = _paintLineMask(cell, QColor(255, 255, 255))
    if action_id and _opaqueFraction(mask) > 0.16 and _set_id != "line":
        other = _sourceCellFrom("line", action_id)
        if other is not None:
            mask = _paintLineMask(other, QColor(255, 255, 255))
    return ("line", mask)


def _recolorTile(accent_mask, glyph, color):
    canvas = _recolorMask(accent_mask, color)
    painter = QPainter(canvas)
    painter.drawImage(0, 0, glyph)
    painter.end()
    return canvas


def _recolorMask(mask, color):
    canvas = QImage(mask.size(), QImage.Format_ARGB32_Premultiplied)
    canvas.fill(QColor(color))
    painter = QPainter(canvas)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return canvas


def _paintLineMask(cell, color):
    cell = _fitCell(cell)
    _image, raw, width, height, stride = _raw(cell)
    bright = []
    for y in range(height):
        row_start = y * stride
        row = []
        for x in range(width):
            row.append(raw[row_start + x * 4 + 2] >= 248)
        bright.append(row)
    keep = _largestBlobs(bright, width, height, minimum=6)
    tint = QColor(color)
    out = bytearray(width * height * 4)
    blue, green, red = tint.blue(), tint.green(), tint.red()
    for y in range(height):
        for x in range(width):
            if not keep[y][x]:
                continue
            index = (y * width + x) * 4
            out[index] = blue
            out[index + 1] = green
            out[index + 2] = red
            out[index + 3] = 255
    return _imageFromBytes(out, width, height)


def _fitCell(cell):
    if cell.width() <= 128 and cell.height() <= 128:
        return cell
    return cell.scaled(128, 128, Qt.IgnoreAspectRatio, Qt.FastTransformation)


def _raw(image):
    converted = image.convertToFormat(QImage.Format_ARGB32)
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    pointer = converted.bits()
    pointer.setsize(height * stride)
    return converted, bytes(pointer), width, height, stride


def _classify(raw, width, height, stride):
    kind = []
    for y in range(height):
        row_start = y * stride
        row = []
        for x in range(width):
            offset = row_start + x * 4
            if raw[offset + 3] < 16:
                row.append(0)
                continue
            lum = raw[offset + 2]
            if lum >= 200:
                row.append(2)
            elif lum <= 60:
                row.append(1)
            else:
                row.append(0)
        kind.append(row)
    return kind


def _imageFromMarks(width, height, kind, outside, accent, outline, white):
    out = bytearray(width * height * 4)
    colors = {
        1: (outline.blue(), outline.green(), outline.red(), outline.alpha()),
        2: (white.blue(), white.green(), white.red(), white.alpha()),
        0: (accent.blue(), accent.green(), accent.red(), accent.alpha()),
    }
    for y in range(height):
        for x in range(width):
            mark = kind[y][x]
            if mark == 0 and outside[y][x]:
                continue
            blue, green, red, alpha = colors[mark]
            index = (y * width + x) * 4
            out[index] = blue
            out[index + 1] = green
            out[index + 2] = red
            out[index + 3] = alpha
    return _imageFromBytes(out, width, height)


def _imageFromBytes(out, width, height):
    image = QImage(out, width, height, width * 4, QImage.Format_ARGB32)
    return image.copy()


def _flood(kind, width, height, wall):
    seen = [[False] * width for _ in range(height)]
    stack = []
    for x in range(width):
        stack.append((x, 0))
        stack.append((x, height - 1))
    for y in range(height):
        stack.append((0, y))
        stack.append((width - 1, y))
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= width or y >= height or seen[y][x]:
            continue
        if kind[y][x] != wall:
            continue
        seen[y][x] = True
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))
    return seen


def _largestBlobs(mask, width, height, minimum):
    seen = [[False] * width for _ in range(height)]
    keep = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if seen[y][x] or not mask[y][x]:
                continue
            blob = []
            stack = [(x, y)]
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                blob.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if seen[ny][nx] or not mask[ny][nx]:
                        continue
                    seen[ny][nx] = True
                    stack.append((nx, ny))
            if len(blob) >= minimum:
                for bx, by in blob:
                    keep[by][bx] = True
    return keep


# ------------------------------------------------------------
# Function: _resetForTests
# Purpose: Drop caches so a test can point at a temp sheet.
# ------------------------------------------------------------
def _resetForTests():
    global _set_id, _accent, _text_color, _cache, _sources, _masks
    _set_id = _DEFAULT_SET
    _accent = ""
    _text_color = ""
    _cache = {}
    _sources = {}
    _masks = {}
