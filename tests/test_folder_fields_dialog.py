"""
The field editor can reuse a field or create one, and suggestions
match Turkish spelling.
"""

import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from library_dialogs import FoldingCompleter, FolderFieldsDialog, LibraryRootDialog


_APP = QApplication.instance() or QApplication([])


def _click_row(widget, row):
    item = widget.item(row)
    widget.scrollToItem(item)
    QTest.qWait(0)
    rect = widget.visualItemRect(item)
    QTest.mouseClick(widget.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())


# ------------------------------------------------------------
# Class: TestFolderFieldsDialog
# Purpose: Clicking a known field adds it. A new name creates one.
# ------------------------------------------------------------
class TestFolderFieldsDialog(unittest.TestCase):

    def test_completer_matches_turkish_spelling(self):
        completer = FoldingCompleter()
        completer.setOptions(["İstanbul", "Ankara"])
        completer.setPrefix("ist")
        self.assertEqual(completer.model().stringList(), ["İstanbul"])

    def test_root_dialog_picks_an_existing_library(self):
        dialog = LibraryRootDialog(
            [{"id": "a", "name": "One"}, {"id": "b", "name": "Two"}],
            initial_root_path="/tmp/PARA",
            initial_library_id="b",
        )
        self.assertEqual(dialog.values()["library_id"], "b")
        self.assertEqual(dialog.values()["root_path"], "/tmp/PARA")
        self.assertFalse(dialog._library.isEditable())
        dialog.close()
        dialog.deleteLater()

    def test_click_adds_a_field_and_create_keeps_a_spaced_value(self):
        dialog = FolderFieldsDialog(
            "/tmp/Workshop",
            [{"id": "c", "name": "Customer"}, {"id": "s", "name": "Status"}],
            {},
            {"c": ["İstanbul"]},
        )
        dialog.show()
        QTest.qWait(0)
        self.assertEqual(dialog._field_list.count(), 2)

        _click_row(dialog._field_list, 0)
        QTest.qWait(0)
        self.assertIn("c", dialog.values()["fields"])

        dialog._search.setText("Bölge")
        QTest.qWait(0)
        self.assertIn("Bölge", dialog._create_btn.text())
        QTest.mouseClick(dialog._create_btn, Qt.LeftButton)
        QTest.qWait(0)
        created = dialog.values()["created"]
        self.assertEqual([item["name"] for item in created], ["Bölge"])

        edit = dialog.valueEditFor("Bölge")
        self.assertIsNotNone(edit)
        edit.setFocus()
        edit.setText("Ahmet Yılmaz")
        edit.returnPressed.emit()
        QTest.qWait(0)
        self.assertEqual(
            dialog.values()["fields"][created[0]["temp_id"]],
            ["Ahmet Yılmaz"],
        )
        dialog.close()
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
