import tempfile
import unittest
from pathlib import Path
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from file_panel import FilePanel

_APP = QApplication.instance() or QApplication([])

class ListingUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.panel = FilePanel('left')
        self.panel.resize(700, 450)
        self.panel.show()
        self.panel.navigateTo(self.tmp.name)
        QTest.qWait(180)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)
        self.tmp.cleanup()

    def test_empty_filter_and_clear(self):
        self.assertEqual(self.panel._empty_label.text(), 'This folder is empty')
        Path(self.tmp.name, 'example.txt').touch()
        self.panel.refresh()
        QTest.qWait(180)
        self.panel._filter_edit.setText('missing')
        QTest.qWait(100)
        self.assertEqual(self.panel._empty_label.text(), 'No items match')
        self.assertEqual(self.panel._empty_action.text(), 'Clear filter')
        self.assertFalse(self.panel._filter_banner_btn.isVisible())
        self.panel._empty_action.click()
        QTest.qWait(100)
        self.assertFalse(self.panel._hasActiveFilter())
        self.assertFalse(self.panel._empty_widget.isVisible())

    def test_error_and_retry_state(self):
        self.panel._source_model._load_error = 'Access denied'
        self.panel._updateFilterUi()
        self.assertEqual(self.panel._empty_label.text(), 'Can’t read this folder')
        self.assertEqual(self.panel._empty_action.text(), 'Retry')
        self.panel._empty_action.click()
        QTest.qWait(180)
        self.assertEqual(self.panel._empty_label.text(), 'This folder is empty')
