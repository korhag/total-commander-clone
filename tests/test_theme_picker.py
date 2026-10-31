"""
The theme list previews on click and can be compared, kept, or dropped.
"""

import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

from theme_picker import ThemePreviewDialog


_APP = QApplication.instance() or QApplication([])

_CHOICES = [(f"t{index}", f"Theme {index}") for index in range(8)]


def _click_row(dialog, row):
    item = dialog._list.item(row)
    dialog._list.scrollToItem(item)
    QTest.qWait(0)
    rect = dialog._list.visualItemRect(item)
    QTest.mouseClick(
        dialog._list.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        rect.center(),
    )


# ------------------------------------------------------------
# Class: TestThemePreviewDialog
# Purpose: Five rows, a click previews that theme, holding the
#          original name shows it, and Accept or Cancel decides.
# ------------------------------------------------------------
class TestThemePreviewDialog(unittest.TestCase):

    def _dialog(self, seen):
        dialog = ThemePreviewDialog(_CHOICES, "t2", seen.append)
        dialog.show()
        QTest.qWait(0)
        return dialog

    def test_list_shows_five_rows(self):
        seen = []
        dialog = self._dialog(seen)
        row = dialog._list.sizeHintForRow(0)
        frame = dialog._list.frameWidth() * 2
        self.assertEqual(dialog.visibleRowCount(), 5)
        self.assertGreater(row, 0)
        self.assertEqual(dialog._list.height(), row * 5 + frame)
        self.assertEqual(dialog._compare.text(), "Theme 2")
        dialog.close()
        dialog.deleteLater()

    def test_click_previews_hold_compares_and_accept_keeps_it(self):
        seen = []
        dialog = self._dialog(seen)
        _click_row(dialog, 4)
        self.assertEqual(seen[-1], "t4")
        QTest.mousePress(dialog._compare, Qt.LeftButton)
        self.assertEqual(seen[-1], "t2")
        QTest.mouseRelease(dialog._compare, Qt.LeftButton)
        self.assertEqual(seen[-1], "t4")
        QTest.mouseClick(dialog._accept, Qt.LeftButton)
        self.assertEqual(dialog.chosenTheme(), "t4")
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(seen[-1], "t4")
        dialog.close()
        dialog.deleteLater()

    def test_cancel_restores_the_original_theme(self):
        seen = []
        dialog = self._dialog(seen)
        _click_row(dialog, 4)
        QTest.mouseClick(dialog._cancel, Qt.LeftButton)
        self.assertIsNone(dialog.chosenTheme())
        self.assertEqual(seen[-1], "t2")
        dialog.close()
        dialog.deleteLater()
