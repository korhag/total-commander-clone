"""
Batch rename applies the new name to the file basename, including
entries whose display name is a relative path from subfolders mode.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

from batch_rename_dialog import BatchRenameDialog


_APP = QApplication.instance() or QApplication([])


# ------------------------------------------------------------
# Class: TestBatchRenamePaths
# Purpose: A prefix must rename the file, not the relative folder path.
# ------------------------------------------------------------
class TestBatchRenamePaths(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_prefix_applies_to_basename_in_subfolder(self):
        sub = os.path.join(self.root, "sub")
        source = os.path.join(sub, "file.txt")
        os.makedirs(sub)
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("data")

        entry = {
            "name": os.path.join("sub", "file.txt"),
            "full_path": source,
            "is_dir": False,
        }
        dialog = BatchRenameDialog([entry], self.root)
        dialog._prefix_edit.setText("pre_")

        self.assertEqual(dialog._preview_table.item(0, 0).text(), "file.txt")
        self.assertEqual(dialog._preview_table.item(0, 1).text(), "pre_file.txt")

        with mock.patch("batch_rename_dialog.QMessageBox.information"):
            dialog._onApply()

        renamed = os.path.join(sub, "pre_file.txt")
        self.assertTrue(os.path.isfile(renamed))
        self.assertFalse(os.path.exists(source))
        self.assertFalse(os.path.exists(os.path.join(self.root, "pre_sub")))
        self.assertEqual(open(renamed, encoding="utf-8").read(), "data")

    def test_invalid_regex_disables_apply(self):
        entry = {
            "name": "file.txt",
            "full_path": os.path.join(self.root, "file.txt"),
            "is_dir": False,
        }
        dialog = BatchRenameDialog([entry], self.root)
        dialog._chk_regex.setChecked(True)
        dialog._find_edit.setText("(")
        self.assertIn("Invalid regex", dialog._summary_label.text())
        self.assertFalse(dialog._btn_apply.isEnabled())


if __name__ == "__main__":
    unittest.main()
