"""
Total Commander Clone - Built-in file viewer

F3 opens a window that is not modal. Images are scaled, text is shown
read-only, and anything else is a hex dump of the start of the file.
N and P step through the files in the panel. The same widget is used
for the Ctrl+Q quick-view pane.
"""

import os
import subprocess
import sys

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QImageReader, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QShortcut,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from thumbnail_loader import isImageFileName


# ------------------------------------------------------------
# Limits. A viewer must not read a whole multi-gigabyte file.
# ------------------------------------------------------------
TEXT_PREVIEW_LIMIT = 256 * 1024
HEX_PREVIEW_LIMIT = 4096
IMAGE_PREVIEW_LIMIT = 64 * 1024 * 1024
IMAGE_PREVIEW_EDGE = 1600


# ------------------------------------------------------------
# Function: looksLikeText
# Purpose: True when a byte sample is plain text rather than
#          a binary file. NUL bytes and a run of control
#          characters mean hex view instead.
# ------------------------------------------------------------
def looksLikeText(data):
    if not data:
        return True
    if b"\x00" in data:
        return False
    sample = data[:4096]
    controls = 0
    for byte in sample:
        if byte < 9 or (13 < byte < 32):
            controls += 1
    return (controls / len(sample)) < 0.10


# ------------------------------------------------------------
# Function: decodeText
# Purpose: Decode text as UTF-8, then Windows-1252.
#          Returns None when the bytes are not text.
# ------------------------------------------------------------
def decodeText(data):
    if not looksLikeText(data):
        return None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return None


# ------------------------------------------------------------
# Function: formatHexDump
# Purpose: Classic hex + ASCII lines, 16 bytes each.
# ------------------------------------------------------------
def formatHexDump(data):
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        ascii_part = "".join(
            chr(byte) if 32 <= byte < 127 else "." for byte in chunk
        )
        lines.append(f"{offset:08X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


# ------------------------------------------------------------
# Function: buildPreview
# Purpose: Decide how to show a path, without building widgets.
# Output: dict with kind missing, folder, image, text, hex, or error.
# ------------------------------------------------------------
def buildPreview(path):
    if not path or not os.path.lexists(path):
        return {"kind": "missing", "path": path or "", "message": "File not found."}
    if os.path.isdir(path):
        return {
            "kind": "folder",
            "path": path,
            "message": "Select a file to view.",
        }
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return {
            "kind": "error",
            "path": path,
            "message": exc.strerror or str(exc),
        }

    name = os.path.basename(path)
    if isImageFileName(name):
        if size > IMAGE_PREVIEW_LIMIT:
            return {
                "kind": "error",
                "path": path,
                "message": "This image is too large to preview.",
            }
        return {"kind": "image", "path": path, "name": name, "size": size}

    try:
        with open(path, "rb") as handle:
            raw = handle.read(TEXT_PREVIEW_LIMIT + 1)
    except OSError as exc:
        return {
            "kind": "error",
            "path": path,
            "message": exc.strerror or str(exc),
        }

    truncated = len(raw) > TEXT_PREVIEW_LIMIT
    sample = raw[:TEXT_PREVIEW_LIMIT]
    text = decodeText(sample)
    if text is not None:
        return {
            "kind": "text",
            "path": path,
            "name": name,
            "text": text,
            "truncated": truncated,
            "size": size,
        }

    hex_data = sample[:HEX_PREVIEW_LIMIT]
    return {
        "kind": "hex",
        "path": path,
        "name": name,
        "text": formatHexDump(hex_data),
        "truncated": size > len(hex_data),
        "size": size,
    }


# ------------------------------------------------------------
# Function: loadPreviewImage
# Purpose: Decode an image scaled down so a large photo does
#          not freeze the window. EXIF orientation is applied.
# ------------------------------------------------------------
def loadPreviewImage(path, max_edge=IMAGE_PREVIEW_EDGE):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    dimensions = reader.size()
    if (
        dimensions.isValid()
        and dimensions.width() > 0
        and dimensions.height() > 0
        and max(dimensions.width(), dimensions.height()) > max_edge
    ):
        scale = float(max_edge) / float(max(dimensions.width(), dimensions.height()))
        reader.setScaledSize(
            QSize(
                max(1, int(round(dimensions.width() * scale))),
                max(1, int(round(dimensions.height() * scale))),
            )
        )
    image = reader.read()
    if image.isNull():
        return None
    return image


# ------------------------------------------------------------
# Function: openInSystemEditor
# Purpose: F4. Notepad on Windows, TextEdit on macOS, and
#          $VISUAL / $EDITOR (or the default app) elsewhere.
# Output: (ok, message). message is empty on success.
# ------------------------------------------------------------
def openInSystemEditor(path):
    if not path or not os.path.isfile(path):
        return False, "Select a file to edit."
    try:
        if os.name == "nt":
            subprocess.Popen(["notepad.exe", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-e", path])
        else:
            editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
            if editor:
                subprocess.Popen([editor, path])
            else:
                subprocess.Popen(["xdg-open", path])
    except OSError as exc:
        return False, exc.strerror or str(exc)
    return True, ""


# ------------------------------------------------------------
# Class: FileViewerWidget
# Purpose: Image, text, or hex preview. Used in the viewer
#          window and in the quick-view pane.
# ------------------------------------------------------------
class FileViewerWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._source_image = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = QLabel("No file selected")
        self._title.setObjectName("viewerTitle")
        self._title.setWordWrap(True)
        self._title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._title)

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(32, 32)

        self._text = QPlainTextEdit()
        self._text.setObjectName("viewerText")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._text.setFont(QFont("Consolas", 10))

        self._message = QLabel("No file selected")
        self._message.setAlignment(Qt.AlignCenter)
        self._message.setWordWrap(True)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._message)
        self._stack.addWidget(self._image)
        self._stack.addWidget(self._text)
        layout.addWidget(self._stack, 1)

    # --------------------------------------------------------
    # Method: showPath
    # Purpose: Load and display one file.
    # --------------------------------------------------------
    def showPath(self, path):
        self._path = path or ""
        self._source_image = None
        preview = buildPreview(self._path)
        kind = preview.get("kind")
        name = preview.get("name") or os.path.basename(self._path)

        if kind == "image":
            image = loadPreviewImage(self._path)
            if image is None:
                self._showMessage(name, "Could not read this image.")
                return
            self._source_image = image
            self._title.setText(name)
            self._stack.setCurrentWidget(self._image)
            self._rescaleImage()
            return

        if kind in ("text", "hex"):
            title = name
            if preview.get("truncated"):
                if kind == "text":
                    title += "  (first 256 KB)"
                else:
                    title += "  (first 4 KB)"
            self._title.setText(title)
            self._text.setPlainText(preview.get("text") or "")
            self._stack.setCurrentWidget(self._text)
            return

        self._showMessage(name or "Viewer", preview.get("message") or "Nothing to show.")

    # --------------------------------------------------------
    # Method: clear
    # Purpose: Empty state, used when no file is selected.
    # --------------------------------------------------------
    def clear(self, message="No file selected"):
        self._path = ""
        self._source_image = None
        self._showMessage("Viewer", message)

    def currentPath(self):
        return self._path

    def _showMessage(self, title, message):
        self._title.setText(title)
        self._message.setText(message)
        self._stack.setCurrentWidget(self._message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescaleImage()

    # --------------------------------------------------------
    # Method: _rescaleImage
    # Purpose: Fit the decoded image inside the pane, keeping
    #          the aspect ratio. The source image is kept.
    # --------------------------------------------------------
    def _rescaleImage(self):
        if self._source_image is None or self._source_image.isNull():
            return
        if self._stack.currentWidget() is not self._image:
            return
        target = self._image.size()
        if target.width() < 2 or target.height() < 2:
            target = self._stack.size()
        pixmap = QPixmap.fromImage(self._source_image)
        scaled = pixmap.scaled(
            target,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image.setPixmap(scaled)


# ------------------------------------------------------------
# Class: FileViewerWindow
# Purpose: Non-modal F3 window. Esc closes it. N and P move
#          to the next and previous file in the panel.
# ------------------------------------------------------------
class FileViewerWindow(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle("Viewer")
        self.resize(760, 560)
        self._panel = None
        self._viewer = FileViewerWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._viewer)

        shortcut_context = Qt.WidgetWithChildrenShortcut
        QShortcut(
            QKeySequence(Qt.Key_Escape), self, self.close, context=shortcut_context
        )
        QShortcut(
            QKeySequence(Qt.Key_N), self, lambda: self._step(1), context=shortcut_context
        )
        QShortcut(
            QKeySequence(Qt.Key_P), self, lambda: self._step(-1), context=shortcut_context
        )

    # --------------------------------------------------------
    # Method: viewPanelFile
    # Purpose: Show the panel's selected file and remember the
    #          panel so N and P can move through its list.
    # --------------------------------------------------------
    def viewPanelFile(self, panel):
        self._panel = panel
        entry = panel.primaryFileEntry() if panel is not None else None
        if entry is None:
            self.setWindowTitle("Viewer")
            self._viewer.clear("Select a file to view.")
        else:
            self._showEntry(entry)
        self.show()
        self.raise_()
        self.activateWindow()

    def viewerWidget(self):
        return self._viewer

    def _showEntry(self, entry):
        path = entry.get("full_path") or ""
        name = os.path.basename(path) or "Viewer"
        self.setWindowTitle(f"Viewer — {name}")
        self._viewer.showPath(path)

    def _step(self, step):
        panel = self._panel
        if panel is None:
            return
        entry = panel.selectAdjacentFile(step)
        if entry is not None:
            self._showEntry(entry)
