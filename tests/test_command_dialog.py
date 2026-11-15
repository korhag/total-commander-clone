import unittest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog
from command_dialog import CommandDialog

_APP = QApplication.instance() or QApplication([])


class CommandDialogTests(unittest.TestCase):
    def setUp(self):
        self.commands = [
            dict(id='copy', name=lambda: 'Copy to other pane', scope='Selection → other pane',
                 aliases=[], keys=[QKeySequence('F6')]),
            dict(id='paths', name=lambda: 'Copy full paths', scope='Selection',
                 aliases=['copy absolute path'], keys=[]),
            dict(id='swap', name=lambda: 'Swap pane paths', scope='Both panes',
                 aliases=['swap panels'], keys=[QKeySequence('Ctrl+Shift+S')]),
        ]
        self.dialog = CommandDialog(self.commands, lambda command: 'Select an item' if command['id'] == 'paths' else '')
        self.dialog.show()

    def tearDown(self):
        self.dialog.close()

    def test_search_and_unavailable_execution(self):
        self.dialog.search.setText('copy absolute path')
        self.assertEqual(self.dialog.results.topLevelItemCount(), 1)
        self.assertEqual(self.dialog.selectedCommand()['id'], 'paths')
        self.dialog.runSelected()
        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.dialog.reason.text(), 'Select an item')
        self.dialog.search.setText('Ctrl+Shift+S')
        self.assertEqual(self.dialog.selectedCommand()['id'], 'swap')
        self.dialog.runSelected()
        self.assertEqual(self.dialog.chosen['id'], 'swap')

    def test_empty_search_and_arrow_navigation(self):
        self.assertIsNone(self.dialog.selectedCommand())
        QTest.keyClick(self.dialog.search, Qt.Key_Down)
        self.assertIsNotNone(self.dialog.selectedCommand())
        self.dialog.search.setText('does not exist')
        self.assertEqual(self.dialog.reason.text(), 'No commands match')
