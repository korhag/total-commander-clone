"""
Bookmark list durability: atomic writes, last-good restore,
stale-session protection, nested menu entries, and import/export.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import config_backup
from settings_manager import SettingsManager


def _names(manager):
    return [item["name"] for item in manager.getBookmarks()]


# ------------------------------------------------------------
# Class: TestBookmarksPersistence
# Purpose: Prove a saved bookmark list survives empty snapshots,
#          damaged state files, and a second window that did not edit.
# ------------------------------------------------------------
class TestBookmarksPersistence(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _manager(self):
        return SettingsManager(self.base, enable_backup=False)

    def _state_path(self):
        return os.path.join(self.base, "state.json")

    def _bookmarks_path(self):
        return os.path.join(self.base, "bookmarks.json")

    def _read_state(self):
        with open(self._state_path(), encoding="utf-8") as handle:
            return json.load(handle)

    def _read_bookmarks_file(self):
        with open(self._bookmarks_path(), encoding="utf-8") as handle:
            return json.load(handle)

    def _write_bookmark_file(self, bookmarks, explicit_empty=False):
        payload = {
            "format": "total-commander-clone-bookmarks",
            "format_version": 1,
            "explicit_empty": explicit_empty,
            "bookmarks": bookmarks,
        }
        with open(self._bookmarks_path(), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    # --------------------------------------------------------
    # Method: test_write_is_atomic_and_keeps_original_on_failure
    # --------------------------------------------------------
    def test_write_is_atomic_and_keeps_original_on_failure(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        self.assertFalse(os.path.exists(self._bookmarks_path() + ".tmp"))
        before = self._read_bookmarks_file()

        with mock.patch("settings_manager.json.dump", side_effect=OSError("disk full")):
            manager.addBookmark("Work", "C:/Work")

        self.assertEqual(_names_from_list(self._read_bookmarks_file()["bookmarks"]), ["Home"])
        self.assertEqual(before["bookmarks"][0]["name"], "Home")
        self.assertFalse(os.path.exists(self._bookmarks_path() + ".tmp"))

    # --------------------------------------------------------
    # Method: test_corrupt_state_restores_last_good_bookmarks
    # --------------------------------------------------------
    def test_corrupt_state_restores_last_good_bookmarks(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        with open(self._bookmarks_path(), "w", encoding="utf-8") as handle:
            handle.write("{not json")

        restored = self._manager()
        self.assertEqual(_names(restored), ["Home"])
        self.assertTrue(os.path.isfile(self._bookmarks_path() + ".corrupt"))
        self.assertIn("unreadable", restored.consumeBookmarkRecoveryNotice())
        self.assertEqual(_names_from_list(self._read_bookmarks_file()["bookmarks"]), ["Home"])

    # --------------------------------------------------------
    # Method: test_empty_state_restores_last_good_unless_cleared
    # --------------------------------------------------------
    def test_empty_state_restores_last_good_unless_cleared(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        self._write_bookmark_file([])

        restored = self._manager()
        self.assertEqual(_names(restored), ["Home"])
        self.assertIn("empty", restored.consumeBookmarkRecoveryNotice())

        restored.setBookmarksStructure([], user_edit=True)
        cleared = self._manager()
        self.assertEqual(_names(cleared), [])
        self.assertEqual(cleared.consumeBookmarkRecoveryNotice(), "")

    # --------------------------------------------------------
    # Method: test_unchanged_session_keeps_newer_disk_bookmarks
    # --------------------------------------------------------
    def test_unchanged_session_keeps_newer_disk_bookmarks(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        self._write_bookmark_file([
            {"type": "bookmark", "name": "Home", "path": "C:/Home"},
            {"type": "bookmark", "name": "Work", "path": "C:/Work"},
        ])
        manager.setSetting("font_size", 14)
        manager.saveAll()
        self.assertEqual(
            _names_from_list(self._read_bookmarks_file()["bookmarks"]),
            ["Home", "Work"],
        )

    # --------------------------------------------------------
    # Method: test_dirty_empty_memory_does_not_wipe_disk
    # --------------------------------------------------------
    def test_dirty_empty_memory_does_not_wipe_disk(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        manager._state["bookmarks"] = []
        manager._bookmarks_dirty = True
        manager._bookmarks_explicit_clear = False
        manager.saveAll()
        self.assertEqual(_names_from_list(self._read_bookmarks_file()["bookmarks"]), ["Home"])

    # --------------------------------------------------------
    # Method: test_empty_tree_snapshot_does_not_wipe_list
    # --------------------------------------------------------
    def test_empty_tree_snapshot_does_not_wipe_list(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        manager.applyBookmarkTreeSnapshot([])
        self.assertEqual(_names(manager), ["Home"])
        self.assertEqual(_names_from_list(self._read_bookmarks_file()["bookmarks"]), ["Home"])

    # --------------------------------------------------------
    # Method: test_getBookmarks_includes_nested_groups
    # --------------------------------------------------------
    def test_getBookmarks_includes_nested_groups(self):
        manager = self._manager()
        manager.setBookmarksStructure([
            {
                "type": "group",
                "name": "Outer",
                "children": [
                    {
                        "type": "group",
                        "name": "Inner",
                        "children": [
                            {"type": "bookmark", "name": "Deep", "path": "C:/Deep"},
                        ],
                    }
                ],
            }
        ], user_edit=True)
        self.assertEqual(manager.getBookmarks(), [{"name": "Deep", "path": "C:/Deep"}])

    # --------------------------------------------------------
    # Method: test_import_replace_and_merge
    # --------------------------------------------------------
    def test_import_replace_and_merge(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        merge_path = os.path.join(self.base, "merge.json")
        with open(merge_path, "w", encoding="utf-8") as handle:
            json.dump({
                "bookmarks": [
                    {"name": "Home", "path": "C:/Home"},
                    {
                        "type": "group",
                        "name": "Extra",
                        "children": [
                            {"name": "Work", "path": "C:/Work"},
                        ],
                    },
                ],
            }, handle)

        merged = manager.importBookmarks(merge_path, mode="merge")
        self.assertEqual(merged["mode"], "merge")
        self.assertEqual(_names(manager), ["Home", "Work"])

        replace_path = os.path.join(self.base, "replace.json")
        with open(replace_path, "w", encoding="utf-8") as handle:
            json.dump([{"name": "Docs", "path": "C:/Docs"}], handle)
        replaced = manager.importBookmarks(replace_path, mode="replace")
        self.assertEqual(replaced["count"], 1)
        self.assertEqual(manager.getBookmarks(), [{"name": "Docs", "path": "C:/Docs"}])
        self.assertEqual(manager.getBookmarksStructure()[0]["type"], "bookmark")

    # --------------------------------------------------------
    # Method: test_export_round_trip
    # --------------------------------------------------------
    def test_export_round_trip(self):
        manager = self._manager()
        manager.addBookmark("Home", "C:/Home")
        path = os.path.join(self.base, "out.json")
        manager.exportBookmarks(path)
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["format"], "total-commander-clone-bookmarks")
        self.assertEqual(payload["bookmarks"][0]["path"], "C:/Home")

    # --------------------------------------------------------
    # Method: test_backup_keeps_bookmarks_when_incoming_list_is_empty
    # --------------------------------------------------------
    def test_backup_keeps_bookmarks_when_incoming_list_is_empty(self):
        user_data = os.path.join(self.base, "user-data")
        settings = {"theme_mode": "dark"}
        with_home = {"bookmarks": [{"type": "bookmark", "name": "Home", "path": "C:/Home"}]}
        empty = {"bookmarks": []}
        with mock.patch.object(config_backup, "getComputerName", return_value="TEST-HOST"):
            backup_dir = config_backup.writeConfigBackup(settings, with_home, user_data_dir=user_data)
            config_backup.writeConfigBackup(
                settings, empty, user_data_dir=user_data, allow_empty_bookmarks=False,
            )
            kept_path = os.path.join(backup_dir, "bookmarks.json")
            with open(kept_path, encoding="utf-8") as handle:
                kept = json.load(handle)
            self.assertEqual(kept["bookmarks"][0]["name"], "Home")
            with open(os.path.join(backup_dir, "state.json"), encoding="utf-8") as handle:
                backed_state = json.load(handle)
            self.assertEqual(backed_state["bookmarks"][0]["name"], "Home")

            config_backup.writeConfigBackup(
                settings, empty, user_data_dir=user_data, allow_empty_bookmarks=True,
            )
            with open(kept_path, encoding="utf-8") as handle:
                cleared = json.load(handle)
        self.assertEqual(cleared["bookmarks"], [])

    # --------------------------------------------------------
    # Method: test_loaded_list_seeds_last_good_once
    # --------------------------------------------------------
    def test_loaded_list_seeds_last_good_once(self):
        os.makedirs(self.base, exist_ok=True)
        with open(self._state_path(), "w", encoding="utf-8") as handle:
            json.dump({
                "bookmarks": [{"type": "bookmark", "name": "Home", "path": "C:/Home"}],
            }, handle)
        manager = self._manager()
        last_good = os.path.join(self.base, "bookmarks.last-good.json")
        self.assertTrue(os.path.isfile(self._bookmarks_path()))
        self.assertTrue(os.path.isfile(last_good))
        self.assertEqual(_names(manager), ["Home"])
        with open(last_good, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertFalse(payload["explicit_empty"])
        with open(self._bookmarks_path(), encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored["bookmarks"][0]["name"], "Home")


def _names_from_list(bookmarks):
    names = []

    def walk(nodes):
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "group":
                walk(node.get("children", []))
            elif node.get("name"):
                names.append(node["name"])

    walk(bookmarks)
    return names


if __name__ == "__main__":
    unittest.main()
