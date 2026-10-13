"""
Settings durability: corrupt settings.json is quarantined, hand-edited
values are coerced to the default types, save failures are reported,
and library edits are written immediately.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from library_manager import LibraryManager
from settings_manager import SettingsManager


# ------------------------------------------------------------
# Class: TestSettingsManager
# Purpose: Prove settings survive bad files and bad values, and
#          that a failed write is visible to the caller.
# ------------------------------------------------------------
class TestSettingsManager(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.settings_path = os.path.join(self.base, "settings.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _manager(self):
        return SettingsManager(self.base, enable_backup=False)

    def _write_settings(self, text):
        with open(self.settings_path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_corrupt_settings_file_is_quarantined(self):
        self._write_settings("{ not json")

        manager = self._manager()

        self.assertEqual(manager.getSetting("font_size"), 10)
        quarantined = os.path.join(self.base, "settings.json.corrupt")
        self.assertTrue(os.path.isfile(quarantined))
        with open(quarantined, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{ not json")

    def test_hand_edited_values_are_coerced_to_default_types(self):
        self._write_settings(json.dumps({
            "font_size": "12",
            "ui_scale": "huge",
            "confirm_delete": "false",
            "show_hidden_files": "yes",
            "theme_mode": 5,
            "window_geometry": "broken",
        }))

        manager = self._manager()

        self.assertEqual(manager.getSetting("font_size"), 12)
        self.assertEqual(manager.getSetting("ui_scale"), 100)
        self.assertIs(manager.getSetting("confirm_delete"), False)
        self.assertIs(manager.getSetting("show_hidden_files"), True)
        self.assertEqual(manager.getSetting("theme_mode"), "dark")
        self.assertEqual(manager.getSetting("window_geometry")["width"], 1400)

    def test_save_reports_write_failure(self):
        manager = self._manager()
        with mock.patch("settings_manager.os.replace", side_effect=PermissionError("denied")):
            self.assertFalse(manager.saveSettings())
        self.assertTrue(manager.saveSettings())

    def test_import_profile_normalizes_bookmarks(self):
        profile_path = os.path.join(self.base, "profile.json")
        with open(profile_path, "w", encoding="utf-8") as handle:
            json.dump({
                "settings": {},
                "state": {"bookmarks": [{"name": "Docs", "path": "C:/Docs"}, "junk"]},
            }, handle)
        manager = self._manager()

        manager.importProfile(profile_path)

        bookmarks = manager.getBookmarksStructure()
        self.assertEqual(len(bookmarks), 1)
        self.assertEqual(bookmarks[0]["type"], "bookmark")
        self.assertEqual(bookmarks[0]["path"], "C:/Docs")

    def test_library_edits_are_written_immediately(self):
        manager = self._manager()
        root = os.path.join(self.base, "library_root")
        os.makedirs(root)

        LibraryManager(manager).registerLibraryRoot("Docs", root)

        with open(os.path.join(self.base, "state.json"), encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual([lib["name"] for lib in saved["libraries"]], ["Docs"])


if __name__ == "__main__":
    unittest.main()
