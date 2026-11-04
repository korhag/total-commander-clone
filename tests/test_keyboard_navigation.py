"""
Arrow, Home, and End keys in a file panel.
"""

import os
import shutil
import tempfile
import unittest

from PyQt5.QtCore import Qt, QModelIndex
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from file_panel import FilePanel


_APP = QApplication.instance() or QApplication([])


def _waitUntilLoaded(panel):
    for _ in range(50):
        QApplication.processEvents()
        QTest.qWait(20)
        if not panel._source_model.isLoading():
            return
    raise AssertionError("folder listing did not finish")


# ------------------------------------------------------------
# Class: TestKeyboardNavigation
# Purpose: The cursor starts on the first row, Home and End
#          reach the ends of the list, Up returns to the
#          folder that was left, and Down from an empty
#          cursor lands on row 0.
# ------------------------------------------------------------
class TestKeyboardNavigation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.child = os.path.join(self._tmp, "child")
        os.makedirs(self.child)
        with open(os.path.join(self._tmp, "a.txt"), "w", encoding="utf-8") as handle:
            handle.write("a")
        with open(os.path.join(self.child, "inside.txt"), "w", encoding="utf-8") as handle:
            handle.write("b")
        self.panel = FilePanel("left")
        self.panel.resize(700, 400)
        self.panel.show()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _open(self, path):
        self.assertTrue(self.panel.navigateTo(path))
        _waitUntilLoaded(self.panel)

    def test_first_row_is_current_after_open(self):
        self._open(self._tmp)
        self.assertEqual(self.panel._table.currentIndex().row(), 0)
        self.assertGreaterEqual(self.panel._table.model().rowCount(), 2)

    def test_down_moves_to_the_next_row(self):
        self._open(self._tmp)
        QTest.keyClick(self.panel._table, Qt.Key_Down)
        QApplication.processEvents()
        self.assertEqual(self.panel._table.currentIndex().row(), 1)

    def test_home_and_end_reach_the_ends(self):
        self._open(self._tmp)
        table = self.panel._table
        last = table.model().rowCount() - 1
        QTest.keyClick(table, Qt.Key_End)
        QApplication.processEvents()
        self.assertEqual(table.currentIndex().row(), last)
        QTest.keyClick(table, Qt.Key_Home)
        QApplication.processEvents()
        self.assertEqual(table.currentIndex().row(), 0)

    def test_go_up_highlights_the_folder_just_left(self):
        self._open(self.child)
        self.panel.goUp()
        _waitUntilLoaded(self.panel)
        row = self.panel._table.currentIndex().row()
        source = self.panel._proxy_model.mapToSource(
            self.panel._proxy_model.index(row, 0)
        )
        entry = self.panel._source_model.entryAt(source.row())
        self.assertEqual(
            os.path.normcase(os.path.normpath(entry["full_path"])),
            os.path.normcase(os.path.normpath(self.child)),
        )

    def test_down_from_path_box_starts_at_first_row(self):
        self._open(self._tmp)
        self.panel._table.setCurrentIndex(QModelIndex())
        self.panel._table.clearSelection()
        QTest.keyClick(self.panel._path_edit, Qt.Key_Down)
        QApplication.processEvents()
        self.assertEqual(self.panel._table.currentIndex().row(), 0)

    def test_enter_in_path_box_opens_that_folder(self):
        self._open(self._tmp)
        self.panel._path_edit.setText(self.child)
        self.panel._path_edit.setFocus()
        QTest.keyClick(self.panel._path_edit, Qt.Key_Return)
        _waitUntilLoaded(self.panel)
        self.assertEqual(
            os.path.normcase(os.path.normpath(self.panel.currentPath())),
            os.path.normcase(os.path.normpath(self.child)),
        )

    def test_enter_on_file_path_selects_that_file(self):
        file_path = os.path.join(self._tmp, "a.txt")
        self._open(self.child)
        self.panel._path_edit.setText(file_path)
        self.panel._path_edit.setFocus()
        QTest.keyClick(self.panel._path_edit, Qt.Key_Return)
        _waitUntilLoaded(self.panel)
        self.assertEqual(
            os.path.normcase(os.path.normpath(self.panel.currentPath())),
            os.path.normcase(os.path.normpath(self._tmp)),
        )
        row = self.panel._table.currentIndex().row()
        source = self.panel._proxy_model.mapToSource(
            self.panel._proxy_model.index(row, 0)
        )
        entry = self.panel._source_model.entryAt(source.row())
        self.assertIsNotNone(entry)
        self.assertEqual(
            os.path.normcase(os.path.normpath(entry["full_path"])),
            os.path.normcase(os.path.normpath(file_path)),
        )

    def test_enter_on_missing_path_keeps_the_open_folder(self):
        self._open(self._tmp)
        missing = os.path.join(self._tmp, "no-such-folder")
        self.panel._path_edit.setText(missing)
        self.panel._path_edit.setFocus()
        QTest.keyClick(self.panel._path_edit, Qt.Key_Return)
        QApplication.processEvents()
        self.assertEqual(
            os.path.normcase(os.path.normpath(self.panel.currentPath())),
            os.path.normcase(os.path.normpath(self._tmp)),
        )
        self.assertIn("Folder not found", self.panel._status_label.text())
        self.assertEqual(
            os.path.normcase(os.path.normpath(self.panel._path_edit.text())),
            os.path.normcase(os.path.normpath(self._tmp)),
        )


if __name__ == "__main__":
    unittest.main()
