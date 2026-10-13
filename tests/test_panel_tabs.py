"""
Folder tabs keep a separate folder, history, and filter for each
tab, and an old single-panel state file still opens as one tab.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from file_manager_app import FileManagerApp
from file_panel import FilePanel
from panel_tabs import PanelTabBar, activeTabRecord, splitTabState
from settings_manager import SettingsManager


_APP = QApplication.instance() or QApplication([])


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


# ------------------------------------------------------------
# Class: TestPanelTabs
# Purpose: Switching tabs restores the folder and the filter.
# ------------------------------------------------------------
class TestPanelTabs(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.folder_a = os.path.join(self.root, "alpha")
        self.folder_b = os.path.join(self.root, "beta")
        os.makedirs(self.folder_a)
        os.makedirs(self.folder_b)
        _touch(os.path.join(self.folder_a, "a.txt"))
        _touch(os.path.join(self.folder_b, "b.txt"))
        self.panel = FilePanel("left")
        self.tabs = PanelTabBar(self.panel)
        self.assertTrue(self.panel.navigateTo(self.folder_a))
        QTest.qWait(0)

    def tearDown(self):
        self.tabs.deleteLater()
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)
        self._tmp.cleanup()

    def test_switch_restores_folder_and_filter(self):
        self.panel._filter_edit.setText("a.txt")
        self.tabs.newTab()
        self.assertEqual(self.tabs.count(), 2)
        self.assertTrue(self.panel.navigateTo(self.folder_b))
        self.panel._filter_edit.setText("")

        self.tabs.setCurrentIndex(0)
        self.assertEqual(
            os.path.normcase(self.panel.currentPath()),
            os.path.normcase(self.folder_a),
        )
        self.assertEqual(self.panel._filter_edit.text(), "a.txt")

        self.tabs.setCurrentIndex(1)
        self.assertEqual(
            os.path.normcase(self.panel.currentPath()),
            os.path.normcase(self.folder_b),
        )
        self.assertEqual(self.panel._filter_edit.text(), "")

    def test_last_tab_stays_open(self):
        self.assertFalse(self.tabs.closeTab())
        self.assertEqual(self.tabs.count(), 1)

    def test_middle_click_closes_a_tab(self):
        self.tabs.newTab()
        self.assertTrue(self.panel.navigateTo(self.folder_b))
        rect = self.tabs.tabRect(1)
        QTest.mouseClick(self.tabs, Qt.MiddleButton, Qt.NoModifier, rect.center())
        self.assertEqual(self.tabs.count(), 1)
        self.assertEqual(
            os.path.normcase(self.panel.currentPath()),
            os.path.normcase(self.folder_a),
        )

    def test_open_in_new_tab_clears_the_filter(self):
        self.panel._filter_edit.setText("a.txt")
        self.assertTrue(self.tabs.openInNewTab(self.folder_b))
        self.assertEqual(self.tabs.count(), 2)
        self.assertEqual(self.panel._filter_edit.text(), "")
        self.assertEqual(
            os.path.normcase(self.panel.currentPath()),
            os.path.normcase(self.folder_b),
        )
        self.tabs.setCurrentIndex(0)
        self.assertEqual(self.panel._filter_edit.text(), "a.txt")

    def test_legacy_state_is_one_tab(self):
        self.tabs.importState(
            {
                "current_path": self.folder_b,
                "history": [self.folder_b],
                "history_index": 0,
            }
        )
        self.assertEqual(self.tabs.count(), 1)
        self.assertEqual(
            os.path.normcase(self.panel.currentPath()),
            os.path.normcase(self.folder_b),
        )
        saved = self.tabs.exportState()
        self.assertEqual(saved["active"], 0)
        self.assertEqual(len(saved["tabs"]), 1)

    def test_damaged_tab_list_falls_back_to_one_tab(self):
        self.tabs.importState({"tabs": "nope"})
        self.assertEqual(self.tabs.count(), 1)
        self.tabs.importState(
            {
                "tabs": [
                    {"current_path": self.folder_a},
                    {"current_path": self.folder_b},
                ],
                "active": True,
            }
        )
        self.assertEqual(self.tabs.count(), 2)
        self.assertEqual(
            os.path.normcase(self.panel.currentPath()),
            os.path.normcase(self.folder_a),
        )

    def test_saved_active_tab_is_the_one_on_screen(self):
        self.tabs.newTab()
        self.assertTrue(self.panel.navigateTo(self.folder_b))
        saved = self.tabs.exportState()
        self.assertEqual(saved["active"], 1)
        record = activeTabRecord(saved)
        self.assertEqual(
            os.path.normcase(record["current_path"]),
            os.path.normcase(self.folder_b),
        )
        tabs, active = splitTabState({"tabs": None, "current_path": self.folder_a})
        self.assertEqual(active, 0)
        self.assertEqual(tabs[0]["current_path"], self.folder_a)


# ------------------------------------------------------------
# Class: TestPanelTabsInWindow
# Purpose: The main window opens a folder in a new tab and
#          writes the tab list when the window closes.
# ------------------------------------------------------------
class TestPanelTabsInWindow(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.folder = os.path.join(self.root, "work")
        os.makedirs(self.folder)
        _touch(os.path.join(self.folder, "note.txt"))
        self.settings = SettingsManager(self.root, enable_backup=False)
        self.window = FileManagerApp(self.settings)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(0)
        self._tmp.cleanup()

    def test_new_tab_and_close_save_the_tab_list(self):
        left = self.window._left_panel
        self.window._setActivePanel(left)
        self.assertTrue(left.navigateTo(self.folder))
        QTest.qWait(0)
        self.window._onNewTab()
        self.assertEqual(self.window._left_tabs.count(), 2)
        self.window._openInNewTab(left, self.root)
        self.assertEqual(self.window._left_tabs.count(), 3)
        self.assertEqual(
            os.path.normcase(left.currentPath()),
            os.path.normcase(self.root),
        )

        self.window.close()
        QTest.qWait(0)
        saved = self.settings.getPanelState("left")
        self.assertEqual(saved["active"], 2)
        self.assertEqual(len(saved["tabs"]), 3)
