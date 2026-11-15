import ntpath
import os
import tempfile
import unittest
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QToolButton
from file_panel import FilePanel, breadcrumbPaths, normalizePathInput

_APP = QApplication.instance() or QApplication([])

class BreadcrumbTests(unittest.TestCase):
    def test_path_components_and_file_url(self):
        self.assertEqual(breadcrumbPaths('/a/b'), [('/', '/'), ('a', '/a'), ('b', '/a/b')])
        self.assertEqual(breadcrumbPaths(r'C:\a\b', ntpath)[0][1], 'C:\\')
        self.assertEqual(breadcrumbPaths(r'\\server\share\folder', ntpath)[0][1], '\\\\server\\share\\')
        self.assertEqual(normalizePathInput('file:///tmp/a%20b'), '/tmp/a b')

    def test_click_navigation_history_and_escape(self):
        with tempfile.TemporaryDirectory() as root:
            child = Path(root, 'a & b', 'child')
            child.mkdir(parents=True)
            panel = FilePanel('left')
            panel.resize(800, 400)
            panel.show()
            panel.navigateTo(str(child))
            QTest.qWait(70)
            parent = str(child.parent)
            panel._navigateBreadcrumb(parent)
            self.assertEqual(panel.currentPath(), parent)
            panel.goBack()
            self.assertEqual(panel.currentPath(), str(child))
            panel.editPath()
            panel.pathEdit().setText('/uncommitted')
            QTest.keyClick(panel.pathEdit(), Qt.Key_Escape)
            self.assertEqual(panel.pathEdit().text(), str(child))
            self.assertIs(panel._address_stack.currentWidget(), panel._breadcrumbs)
            panel.close()
            panel.deleteLater()
            QTest.qWait(0)

    def test_overflow_keeps_current_and_ancestors(self):
        with tempfile.TemporaryDirectory() as root:
            child = Path(root, 'one', 'two', 'three', 'four')
            child.mkdir(parents=True)
            panel = FilePanel('left')
            from PyQt5.QtWidgets import QWidget, QHBoxLayout
            host = QWidget()
            layout = QHBoxLayout(host)
            layout.addWidget(panel)
            host.resize(300, 400)
            host.show()
            panel.navigateTo(str(child))
            QTest.qWait(80)
            self.assertTrue(panel._breadcrumbs._hidden_paths)
            self.assertEqual(panel._breadcrumbs._paths[-1][1], str(child))
            menu = panel._breadcrumbs.ancestorMenu(all_ancestors=True)
            self.assertEqual(len(menu.actions()), len(panel._breadcrumbs._paths) - 1)
            host.close()
            panel.close()
            panel.deleteLater()
            QTest.qWait(0)
