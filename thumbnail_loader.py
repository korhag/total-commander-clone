"""
Total Commander Clone - Image thumbnail loader

Loads small previews for image files Qt can read. Decoding runs on a
background pool so a folder of photos does not freeze the file list.
QImage is produced off the UI thread; QPixmap and QIcon are built on
the UI thread.
"""

import logging
import os
import threading
from collections import OrderedDict

from PyQt5.QtCore import QObject, QRunnable, QSize, QThreadPool, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QImage, QImageReader, QPixmap


logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Limits. Kept here so tests and the file panel share one policy.
# ------------------------------------------------------------
THUMBNAIL_MAX_CACHE_ENTRIES = 400
THUMBNAIL_MAX_FILE_BYTES = 64 * 1024 * 1024
THUMBNAIL_THREAD_COUNT = 2

_supported_extensions = None


# ------------------------------------------------------------
# Function: supportedImageExtensions
# Purpose: Extensions QImageReader can decode, without the dot.
#          Read once, after a QApplication exists.
# ------------------------------------------------------------
def supportedImageExtensions():
    global _supported_extensions
    if _supported_extensions is None:
        found = set()
        for fmt in QImageReader.supportedImageFormats():
            text = bytes(fmt).decode("ascii", "ignore").strip().lower()
            if text:
                found.add(text)
        _supported_extensions = frozenset(found)
    return _supported_extensions


# ------------------------------------------------------------
# Function: isImageFileName
# Purpose: True when Qt can decode this file name as an image.
#          Does not look at the file size.
# ------------------------------------------------------------
def isImageFileName(name):
    if not isinstance(name, str) or not name:
        return False
    extension = os.path.splitext(name)[1].lstrip(".").lower()
    if not extension:
        return False
    extensions = supportedImageExtensions()
    if extension in extensions:
        return True
    # Some Qt builds list only one of these two names.
    if extension == "jpg":
        return "jpeg" in extensions
    if extension == "jpeg":
        return "jpg" in extensions
    return False


# ------------------------------------------------------------
# Function: isThumbnailCandidate
# Purpose: True when this file is an image small enough to preview.
# Input: name (str) - file name or relative path.
#        size (int) - size in bytes; folders use a negative size.
# ------------------------------------------------------------
def isThumbnailCandidate(name, size):
    if not isinstance(size, int) or isinstance(size, bool):
        return False
    if size < 0 or size > THUMBNAIL_MAX_FILE_BYTES:
        return False
    return isImageFileName(name)


def _cacheKey(full_path, mod_time, size):
    return (
        os.path.normcase(os.path.normpath(full_path)),
        float(mod_time),
        int(size),
    )


# ------------------------------------------------------------
# Function: _readScaledImage
# Purpose: Decode an image already scaled down. JPEG uses a cheap
#          scaled decode. EXIF orientation is applied so phone
#          photos are the right way up.
# ------------------------------------------------------------
def _readScaledImage(path, size):
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        dimensions = reader.size()
        if (
            dimensions.isValid()
            and dimensions.width() > 0
            and dimensions.height() > 0
        ):
            scale = min(
                float(size) / float(dimensions.width()),
                float(size) / float(dimensions.height()),
                1.0,
            )
            if scale < 1.0:
                reader.setScaledSize(
                    QSize(
                        max(1, int(round(dimensions.width() * scale))),
                        max(1, int(round(dimensions.height() * scale))),
                    )
                )
        image = reader.read()
        if image.isNull():
            logger.debug(
                "Thumbnail not decoded for %s: %s", path, reader.errorString()
            )
            return None
        if image.width() > size or image.height() > size:
            image = image.scaled(
                size,
                size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        return image
    except Exception:
        logger.exception("Thumbnail decode failed for %s", path)
        return None


# ------------------------------------------------------------
# Class: _ThumbnailTask
# Purpose: One background decode. The result is handed back to the
#          loader, which turns it into an icon on the UI thread.
# ------------------------------------------------------------
class _ThumbnailTask(QRunnable):

    def __init__(self, loader, path, key, generation):
        super().__init__()
        self._loader = loader
        self._path = path
        self._key = key
        self._generation = generation

    def run(self):
        image = _readScaledImage(self._path, self._key[2])
        try:
            self._loader._publishFromWorker(self._key, self._generation, image)
        except RuntimeError:
            # The loader was already destroyed while this decode finished.
            return


# ------------------------------------------------------------
# Class: ThumbnailLoader
# Purpose: Cache of preview icons and a small thread pool that
#          fills it. request() is called from the file model while
#          a row is painted.
# ------------------------------------------------------------
class ThumbnailLoader(QObject):

    thumbnailReady = pyqtSignal(str)
    _resultReady = pyqtSignal()

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = OrderedDict()
        self._failed = OrderedDict()
        self._inflight = set()
        self._pending = {}
        self._generation = 0
        self._pending_lock = threading.Lock()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(THUMBNAIL_THREAD_COUNT)
        self._resultReady.connect(self._applyPendingResults)

    # --------------------------------------------------------
    # Method: request
    # Purpose: Return a cached icon, or queue a decode and return
    #          None. The cache key includes the modified time, so
    #          an edited image is loaded again.
    # --------------------------------------------------------
    def request(self, full_path, mod_time, size):
        if not full_path or int(size) <= 0:
            return None
        key = _cacheKey(full_path, mod_time, size)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        if key in self._failed:
            return None
        with self._pending_lock:
            if key in self._inflight:
                return None
            generation = self._generation
            self._inflight.add(key)
        task = _ThumbnailTask(self, full_path, key, generation)
        self._pool.start(task)
        return None

    # --------------------------------------------------------
    # Method: cancelPending
    # Purpose: Drop queued decodes when the folder changes.
    #          Icons already cached are kept.
    # --------------------------------------------------------
    def cancelPending(self):
        with self._pending_lock:
            self._generation += 1
            self._pending.clear()
            self._inflight.clear()
        self._pool.clear()

    # --------------------------------------------------------
    # Method: _publishFromWorker
    # Purpose: Store a decoded image from a pool thread. A stale
    #          result (folder already changed) is ignored.
    # --------------------------------------------------------
    def _publishFromWorker(self, key, generation, image):
        with self._pending_lock:
            if generation != self._generation:
                return
            self._pending[key] = (generation, image)
        self._resultReady.emit()

    # --------------------------------------------------------
    # Method: _applyPendingResults
    # Purpose: Build icons on the UI thread and tell the model
    #          which path can be repainted.
    # --------------------------------------------------------
    def _applyPendingResults(self):
        with self._pending_lock:
            current = self._generation
            items = list(self._pending.items())
            self._pending.clear()
        for key, (generation, image) in items:
            self._inflight.discard(key)
            if generation != current:
                continue
            icon = self._iconFromImage(image)
            if icon is None:
                self._rememberFailure(key)
                continue
            self._rememberIcon(key, icon)
            self.thumbnailReady.emit(key[0])

    def _iconFromImage(self, image):
        if image is None or image.isNull():
            return None
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return None
        return QIcon(pixmap)

    def _rememberIcon(self, key, icon):
        self._failed.pop(key, None)
        self._cache[key] = icon
        self._cache.move_to_end(key)
        while len(self._cache) > THUMBNAIL_MAX_CACHE_ENTRIES:
            self._cache.popitem(last=False)

    def _rememberFailure(self, key):
        self._failed[key] = True
        self._failed.move_to_end(key)
        while len(self._failed) > THUMBNAIL_MAX_CACHE_ENTRIES:
            self._failed.popitem(last=False)
