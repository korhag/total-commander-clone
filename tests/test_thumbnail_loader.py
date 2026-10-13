"""
Image thumbnails: which files qualify, background loading, cache keys,
and the file model requesting a preview only when thumbnails are on.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QImage
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication

from file_panel import FileSystemModel
from theme import getUiMetrics
from thumbnail_loader import (
    THUMBNAIL_MAX_FILE_BYTES,
    ThumbnailLoader,
    isThumbnailCandidate,
    supportedImageExtensions,
)


_APP = QApplication.instance() or QApplication([])


def _writePng(path):
    image = QImage(8, 4, QImage.Format_RGB32)
    image.fill(Qt.red)
    if not image.save(path, "PNG"):
        raise RuntimeError(f"Could not write {path}")


def _waitForThumbnail(loader):
    spy = QSignalSpy(loader.thumbnailReady)
    if len(spy) == 0 and not spy.wait(5000):
        raise AssertionError("thumbnail was not decoded")
    return spy


# ------------------------------------------------------------
# Class: TestThumbnailCandidates
# Purpose: Only image files under the size limit are previews.
# ------------------------------------------------------------
class TestThumbnailCandidates(unittest.TestCase):

    def test_png_is_a_candidate_and_text_or_huge_files_are_not(self):
        self.assertIn("png", supportedImageExtensions())
        self.assertTrue(isThumbnailCandidate("photo.PNG", 100))
        self.assertTrue(isThumbnailCandidate(os.path.join("album", "photo.jpg"), 100))
        self.assertFalse(isThumbnailCandidate("notes.txt", 100))
        self.assertFalse(isThumbnailCandidate("photo.png", -1))
        self.assertFalse(
            isThumbnailCandidate("photo.png", THUMBNAIL_MAX_FILE_BYTES + 1)
        )
        self.assertFalse(isThumbnailCandidate("", 100))

    def test_thumbnail_row_is_taller_than_the_preview(self):
        metrics = getUiMetrics(10, 100)
        self.assertGreater(metrics["thumbnail_row_height"], metrics["thumbnail_size"])
        self.assertGreaterEqual(metrics["thumbnail_size"], 32)


# ------------------------------------------------------------
# Class: TestThumbnailLoader
# Purpose: A real PNG becomes an icon; a new modified time misses.
# ------------------------------------------------------------
class TestThumbnailLoader(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "pic.png")
        _writePng(self.path)
        self.mtime = os.path.getmtime(self.path)
        self.loader = ThumbnailLoader()

    def tearDown(self):
        self.loader.cancelPending()
        self.loader._pool.waitForDone(5000)
        self._tmp.cleanup()

    def test_png_loads_and_a_new_mtime_is_a_cache_miss(self):
        self.assertIsNone(self.loader.request(self.path, self.mtime, 32))
        _waitForThumbnail(self.loader)

        icon = self.loader.request(self.path, self.mtime, 32)
        self.assertIsInstance(icon, QIcon)
        self.assertFalse(icon.isNull())

        self.assertIsNone(self.loader.request(self.path, self.mtime + 10, 32))


# ------------------------------------------------------------
# Class: TestFileModelThumbnails
# Purpose: The list keeps the normal icon until thumbnails are on.
# ------------------------------------------------------------
class TestFileModelThumbnails(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "pic.png")
        _writePng(self.path)
        notes = os.path.join(self._tmp.name, "notes.txt")
        with open(notes, "w", encoding="utf-8") as handle:
            handle.write("hello")
        self.model = FileSystemModel()
        self.model.loadDirectory(self._tmp.name)

    def tearDown(self):
        self.model._thumbnails.cancelPending()
        self.model._thumbnails._pool.waitForDone(5000)
        self._tmp.cleanup()

    def test_thumbnail_is_requested_only_when_enabled(self):
        image_row = self.model.getEntryByName("pic.png")
        text_row = self.model.getEntryByName("notes.txt")
        self.assertGreaterEqual(image_row, 0)
        self.assertGreaterEqual(text_row, 0)
        image_index = self.model.index(image_row, 0)

        off_icon = self.model.data(image_index, Qt.DecorationRole)
        self.assertIsInstance(off_icon, QIcon)
        spy = QSignalSpy(self.model._thumbnails.thumbnailReady)
        self.model.data(image_index, Qt.DecorationRole)
        self.model.data(self.model.index(text_row, 0), Qt.DecorationRole)
        self.assertFalse(spy.wait(300))

        self.model.setThumbnailSize(32)
        self.model.setShowThumbnails(True)
        on_icon = self.model.data(image_index, Qt.DecorationRole)
        self.assertIsInstance(on_icon, QIcon)
        self.assertTrue(spy.wait(5000) or len(spy) > 0)

        ready_icon = self.model.data(image_index, Qt.DecorationRole)
        self.assertIsInstance(ready_icon, QIcon)
        self.assertFalse(ready_icon.isNull())


if __name__ == "__main__":
    unittest.main()
