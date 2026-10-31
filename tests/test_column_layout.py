"""
File-list columns pack to their text and give the rest to Name.
"""

import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from file_panel import FilePanel


_APP = QApplication.instance() or QApplication([])


def _settle(panel):
    for _ in range(30):
        QApplication.processEvents()
        QTest.qWait(10)


# ------------------------------------------------------------
# Class: TestColumnLayout
# Purpose: A saved wide Size column is pulled back to the text,
#          Date stays wide enough for its header, and a locked
#          Size column is left alone.
# ------------------------------------------------------------
class TestColumnLayout(unittest.TestCase):

    def setUp(self):
        self.panel = FilePanel("left")
        self.panel.resize(1100, 420)
        self.panel.show()
        _settle(self.panel)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)

    def _visible_width(self):
        table = self.panel._table
        visible = [
            col
            for col in range(table.model().columnCount())
            if not table.isColumnHidden(col)
        ]
        return visible, sum(table.columnWidth(col) for col in visible)

    def test_size_header_is_right_aligned(self):
        alignment = self.panel._source_model.headerData(
            1, Qt.Horizontal, Qt.TextAlignmentRole
        )
        self.assertTrue(int(alignment) & int(Qt.AlignRight))

    def test_wide_size_column_packs_to_the_text(self):
        table = self.panel._table
        header = table.horizontalHeader()
        header.blockSignals(True)
        table.setColumnWidth(1, 400)
        header.blockSignals(False)
        self.panel._user_sized_columns.discard("size")
        self.panel._reflowColumnsToViewport()

        preferred = self.panel._preferredWidthForColumn(1)
        self.assertIsNotNone(preferred)
        self.assertLessEqual(table.columnWidth(1), preferred + 4)
        self.assertGreaterEqual(
            table.columnWidth(3),
            self.panel._minWidthForColumn(3),
        )
        visible, total = self._visible_width()
        viewport = table.viewport().width()
        self.assertIn(1, visible)
        self.assertIn(3, visible)
        self.assertGreater(viewport, 400)
        self.assertLessEqual(abs(total - viewport), 8)

    def test_locked_size_column_keeps_its_width(self):
        table = self.panel._table
        header = table.horizontalHeader()
        header.blockSignals(True)
        table.setColumnWidth(1, 400)
        header.blockSignals(False)
        self.panel._column_width_locked["size"] = True
        self.panel._locked_column_width_px["size"] = 400
        self.panel._user_sized_columns.discard("size")
        self.panel._reflowColumnsToViewport()
        self.assertGreaterEqual(table.columnWidth(1), 390)

    def test_columns_can_be_reordered_and_restored(self):
        header = self.panel._table.horizontalHeader()
        self.assertTrue(header.sectionsMovable())
        self.assertEqual(
            self.panel.columnOrder(),
            ["name", "size", "type", "date_modified"],
        )
        header.moveSection(3, 1)
        self.assertEqual(
            self.panel.columnOrder(),
            ["name", "date_modified", "size", "type"],
        )
        self.assertIsNone(self.panel._sanitizeColumnOrder(["size", "nope"]))
        self.assertIsNone(self.panel._sanitizeColumnOrder(None))
        self.panel.applyColumnOrder(["name", "size", "type", "date_modified"])
        self.assertEqual(
            self.panel.columnOrder(),
            ["name", "size", "type", "date_modified"],
        )
