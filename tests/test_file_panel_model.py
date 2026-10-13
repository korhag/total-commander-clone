"""
File panel listing: scan cache invalidation below the root, regex
filters with commas, unreadable folders, and recursive folder rename.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PyQt5.QtWidgets import QApplication

import scan_cache
from file_panel import FileSortFilterProxy, FileSystemModel


_APP = QApplication.instance() or QApplication([])


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


def _dirEntry(full_path, name):
    return {
        "name": name,
        "size": -1,
        "type": "Folder",
        "mod_time": os.path.getmtime(full_path),
        "is_dir": True,
        "full_path": full_path,
    }


# ------------------------------------------------------------
# Class: TestScanCache
# Purpose: A change inside a subfolder must invalidate the cached
#          recursive listing even though the root mtime is unchanged.
# ------------------------------------------------------------
class TestScanCache(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.sub = os.path.join(self.root, "sub")
        os.makedirs(self.sub)
        os.utime(self.sub, (1_000_000_000, 1_000_000_000))
        scan_cache.configureScanCache(None, enabled=True)
        scan_cache.invalidateScanCache()
        self.entries = [_dirEntry(self.sub, "sub")]

    def tearDown(self):
        scan_cache.invalidateScanCache()
        self._tmp.cleanup()

    def test_unchanged_tree_is_served_from_cache(self):
        scan_cache.putScanCache(self.root, False, self.entries)
        self.assertEqual(scan_cache.getScanCache(self.root, False), self.entries)

    def test_change_inside_subfolder_invalidates_cache(self):
        scan_cache.putScanCache(self.root, False, self.entries)
        root_mtime = os.path.getmtime(self.root)

        _touch(os.path.join(self.sub, "new.txt"))

        self.assertEqual(os.path.getmtime(self.root), root_mtime)
        self.assertIsNone(scan_cache.getScanCache(self.root, False))


# ------------------------------------------------------------
# Class: TestFileSystemModel
# Purpose: Model and proxy behaviour without a full FilePanel.
# ------------------------------------------------------------
class TestFileSystemModel(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_regex_filter_is_not_split_on_commas(self):
        for name in ("a.txt", "aaa.txt", "aaaa.txt", "b.txt"):
            _touch(os.path.join(self.root, name))
        model = FileSystemModel()
        model.loadDirectory(self.root)
        proxy = FileSortFilterProxy()
        proxy.setSourceModel(model)

        proxy.setFilterMode("regex")
        proxy.setFilterText(r"^a{1,3}\.txt$")

        names = sorted(
            model.entryAt(proxy.mapToSource(proxy.index(row, 0)).row())["name"]
            for row in range(proxy.rowCount())
        )
        self.assertEqual(names, ["a.txt", "aaa.txt"])

    def test_unreadable_folder_reports_error(self):
        model = FileSystemModel()
        model.loadDirectory(os.path.join(self.root, "missing"))
        self.assertEqual(model.rowCount(), 0)
        self.assertTrue(model.loadError())

        model.loadDirectory(self.root)
        self.assertEqual(model.loadError(), "")

    def test_recursive_folder_rename_updates_children(self):
        old_dir = os.path.join(self.root, "old")
        child = os.path.join(old_dir, "child.txt")
        _touch(child)
        model = FileSystemModel()
        model._current_path = self.root
        model._recursive = True
        model._entries = [
            {"name": "old", "size": -1, "type": "Folder", "mod_time": 0,
             "is_dir": True, "full_path": old_dir},
            {"name": os.path.join("old", "child.txt"), "size": 1, "type": "File",
             "mod_time": 0, "is_dir": False, "full_path": child},
        ]
        new_dir = os.path.join(self.root, "new")
        os.rename(old_dir, new_dir)

        model.renameEntry(0, "new")

        child_entry = model.entryAt(1)
        self.assertEqual(child_entry["full_path"], os.path.join(new_dir, "child.txt"))
        self.assertEqual(child_entry["name"], os.path.join("new", "child.txt"))


if __name__ == "__main__":
    unittest.main()
