"""
The drive list opens on mouse release, and a slow folder read does
not freeze the window or apply after the user has moved on.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from file_panel import DriveLineEdit, DrivePickerCombo, FilePanel, FileSystemModel


_APP = QApplication.instance() or QApplication([])


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


def _names(model):
    found = []
    for row in range(model.rowCount()):
        entry = model.entryAt(row)
        if entry:
            found.append(entry["name"])
    return found


def _waitUntil(predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(20)
    return predicate()


# ------------------------------------------------------------
# Class: DrivePopupTests
# Purpose: A click must not open the list until the button is
#          released, or the same click closes it again.
# ------------------------------------------------------------
class DrivePopupTests(unittest.TestCase):

    def tearDown(self):
        QTest.qWait(0)

    def test_comboOpensOnReleaseNotPress(self):
        combo = DrivePickerCombo()
        combo.addItem("/", "/")
        combo.resize(120, 28)
        combo.show()
        QTest.qWait(0)
        try:
            self.assertFalse(combo.view().isVisible())
            QTest.mousePress(combo, Qt.LeftButton)
            self.assertFalse(combo.view().isVisible())
            QTest.mouseRelease(combo, Qt.LeftButton)
            self.assertTrue(combo.view().isVisible())
        finally:
            combo.hidePopup()
            combo.close()

    def test_lineEditOpensOnReleaseNotPress(self):
        combo = DrivePickerCombo()
        combo.setEditable(True)
        edit = DriveLineEdit(combo, combo)
        combo.setLineEdit(edit)
        combo.addItem("~", "/home")
        combo.resize(120, 28)
        combo.show()
        QTest.qWait(0)
        try:
            QTest.mousePress(edit, Qt.LeftButton)
            self.assertFalse(combo.view().isVisible())
            QTest.mouseRelease(edit, Qt.LeftButton)
            self.assertTrue(combo.view().isVisible())
        finally:
            combo.hidePopup()
            combo.close()


# ------------------------------------------------------------
# Class: SlowListingTests
# Purpose: A folder read that outlasts the short wait returns
#          at once, then fills the rows. A newer folder wins.
# ------------------------------------------------------------
class SlowListingTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _touch(os.path.join(self.root, "keep.txt"))
        self.model = FileSystemModel()

    def tearDown(self):
        self.model.shutdownListing()
        self.model.deleteLater()
        QTest.qWait(0)
        self._tmp.cleanup()

    def test_slowListingReturnsWhileLoadingThenFillsRows(self):
        release = threading.Event()
        real_listdir = os.listdir

        def slow_listdir(path):
            release.wait(5)
            return real_listdir(path)

        with patch("recursive_scan_worker.os.listdir", side_effect=slow_listdir):
            started = time.monotonic()
            self.model.loadDirectory(self.root)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.4)
            self.assertTrue(self.model.isLoading())
            self.assertEqual(self.model.rowCount(), 0)
            release.set()
            self.assertTrue(_waitUntil(lambda: not self.model.isLoading()))

        self.assertEqual(_names(self.model), ["keep.txt"])
        self.assertFalse(self.model.isLoading())

    def test_staleSlowListingIsDiscarded(self):
        slow_root = os.path.join(self.root, "slow")
        fast_root = os.path.join(self.root, "fast")
        os.makedirs(slow_root)
        os.makedirs(fast_root)
        _touch(os.path.join(slow_root, "slow.txt"))
        _touch(os.path.join(fast_root, "fast.txt"))
        release = threading.Event()
        real_listdir = os.listdir
        slow_key = os.path.normpath(slow_root)

        def slow_listdir(path):
            if os.path.normpath(path) == slow_key:
                release.wait(5)
            return real_listdir(path)

        try:
            with patch("recursive_scan_worker.os.listdir", side_effect=slow_listdir):
                self.model.loadDirectory(slow_root)
                self.assertTrue(self.model.isLoading())
                self.model.loadDirectory(fast_root)
                self.assertFalse(self.model.isLoading())
                self.assertEqual(_names(self.model), ["fast.txt"])
                release.set()
                QTest.qWait(200)
        finally:
            release.set()

        self.assertEqual(_names(self.model), ["fast.txt"])
        self.assertEqual(os.path.normpath(self.model.currentPath()), os.path.normpath(fast_root))


# ------------------------------------------------------------
# Class: CancelScanTests
# Purpose: Leaving a Subfolders scan must not wait for it.
# ------------------------------------------------------------
class CancelScanTests(unittest.TestCase):

    def test_cancelReturnsWithoutWaiting(self):
        tmp = tempfile.TemporaryDirectory()
        dir_a = os.path.join(tmp.name, "a")
        dir_b = os.path.join(tmp.name, "b")
        os.makedirs(dir_a)
        os.makedirs(dir_b)
        _touch(os.path.join(dir_a, "a.txt"))
        panel = FilePanel("left")
        release = threading.Event()
        started = threading.Event()
        calls = {"n": 0}
        real_walk = os.walk

        def slow_walk(path, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                started.set()
                release.wait(5)
            return real_walk(path, *args, **kwargs)

        try:
            self.assertTrue(panel.navigateTo(dir_a))
            with patch("recursive_scan_worker.os.walk", side_effect=slow_walk):
                panel.sourceModel().setRecursive(True)
                self.assertTrue(started.wait(2))
                began = time.monotonic()
                self.assertTrue(panel.navigateTo(dir_b))
                self.assertLess(time.monotonic() - began, 0.5)
        finally:
            release.set()
            panel.close()
            panel.deleteLater()
            QTest.qWait(0)
            tmp.cleanup()
