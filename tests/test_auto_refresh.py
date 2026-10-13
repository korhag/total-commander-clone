"""
Panels reload when the open folder changes outside the app.
The selection stays, a rename in progress is not interrupted, and
Subfolders mode drops the scan cache instead of walking the tree.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

import scan_cache
from file_panel import FilePanel


_APP = QApplication.instance() or QApplication([])


def _touch(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


def _names(panel):
    found = []
    model = panel._source_model
    for row in range(model.rowCount()):
        entry = model.entryAt(row)
        if entry:
            found.append(entry["name"])
    return found


def _select_name(panel, name):
    source = panel._source_model
    proxy = panel._proxy_model
    for row in range(source.rowCount()):
        entry = source.entryAt(row)
        if not entry or entry["name"] != name:
            continue
        proxy_index = proxy.mapFromSource(source.index(row, 0))
        panel.tableView().selectRow(proxy_index.row())
        return
    raise AssertionError(f"{name} is not in the list")


class _Settings:
    def __init__(self, values):
        self._values = values

    def getSetting(self, key, default=None):
        return self._values.get(key, default)


# ------------------------------------------------------------
# Class: TestAutoRefresh
# Purpose: A file created on disk shows up without F5, and the
#          row that was selected stays selected.
# ------------------------------------------------------------
class TestAutoRefresh(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _touch(os.path.join(self.root, "keep.txt"))
        scan_cache.configureScanCache(None, enabled=True)
        scan_cache.invalidateScanCache()
        self.panel = FilePanel("left")

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)
        scan_cache.invalidateScanCache()
        self._tmp.cleanup()

    def test_new_file_appears_and_selection_survives(self):
        self.assertTrue(self.panel.navigateTo(self.root))
        QTest.qWait(0)
        watched = [
            os.path.normcase(os.path.normpath(path))
            for path in self.panel._dir_watcher.directories()
        ]
        self.assertIn(os.path.normcase(os.path.normpath(self.root)), watched)

        _select_name(self.panel, "keep.txt")
        _touch(os.path.join(self.root, "arrived.txt"))

        appeared = False
        for _ in range(30):
            QTest.qWait(100)
            if "arrived.txt" in _names(self.panel):
                appeared = True
                break
        self.assertTrue(appeared, "the new file did not show up on its own")
        selected = [entry["name"] for entry in self.panel.selectedEntries()]
        self.assertIn("keep.txt", selected)

    def test_refresh_is_deferred_while_renaming(self):
        self.assertTrue(self.panel.navigateTo(self.root))
        QTest.qWait(0)
        _select_name(self.panel, "keep.txt")
        self.panel.startRename()
        self.assertIsNotNone(self.panel._rename_edit)

        _touch(os.path.join(self.root, "during.txt"))
        self.panel._applyPendingAutoRefresh()
        self.assertNotIn("during.txt", _names(self.panel))
        self.assertTrue(self.panel._auto_refresh_deferred)

        self.panel._cancelRename()
        self.assertIsNone(self.panel._rename_edit)
        self.panel._applyPendingAutoRefresh()
        self.assertIn("during.txt", _names(self.panel))

    def test_subfolders_mode_drops_the_cache_without_rescanning(self):
        self.assertTrue(self.panel.navigateTo(self.root))
        scan_cache.putScanCache(self.root, False, [])
        self.assertIsNotNone(scan_cache.getScanCache(self.root, False))
        self.panel._source_model._recursive = True
        before = self.panel._source_model.rowCount()
        _touch(os.path.join(self.root, "later.txt"))

        self.panel._applyPendingAutoRefresh()

        self.assertIsNone(scan_cache.getScanCache(self.root, False))
        self.assertEqual(self.panel._source_model.rowCount(), before)
        self.assertNotIn("later.txt", _names(self.panel))

    def test_setting_off_does_not_watch_the_folder(self):
        panel = FilePanel("left", settings_manager=_Settings({"auto_refresh_panels": False}))
        try:
            self.assertTrue(panel.navigateTo(self.root))
            self.assertEqual(panel._dir_watcher.directories(), [])
            _touch(os.path.join(self.root, "ignored.txt"))
            panel._applyPendingAutoRefresh()
            self.assertNotIn("ignored.txt", _names(panel))
        finally:
            panel.close()
            panel.deleteLater()
            QTest.qWait(0)

    def test_scroll_position_is_kept(self):
        for index in range(40):
            _touch(os.path.join(self.root, f"row{index:02d}.txt"))
        self.panel.resize(480, 160)
        self.panel.show()
        self.assertTrue(self.panel.navigateTo(self.root))
        QTest.qWait(50)
        bar = self.panel.tableView().verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        saved = bar.value()
        self.assertGreater(saved, 0)

        _touch(os.path.join(self.root, "scrolled.txt"))
        self.panel._applyPendingAutoRefresh()
        QTest.qWait(0)
        self.assertEqual(bar.value(), saved)
        self.assertIn("scrolled.txt", _names(self.panel))
