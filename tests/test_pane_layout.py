"""Single-pane workspace behavior, persistence, and lazy sidebar discovery."""

import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from PyQt5.QtCore import QPoint, Qt, QThread
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from file_manager_app import FileManagerApp
from library_manager import LibraryManager
from settings_manager import SettingsManager


_APP = QApplication.instance() or QApplication([])


def _wait_until(predicate):
    for _ in range(150):
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Waypane did not finish updating")


class TestPaneLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.left = self.root / "left"
        self.right = self.root / "right"
        self.left.mkdir()
        self.right.mkdir()
        self.settings = self._readState()
        self.settings.setSetting("check_for_updates_on_startup", False)
        self.settings.setSetting("cache_recursive_scans", False)
        self.settings.setSetting("default_left_path", str(self.left))
        self.settings.setSetting("default_right_path", str(self.right))
        self.settings.saveAll()

    def _readState(self):
        return SettingsManager(self.tmp.name, enable_backup=False)

    def _window(self, settings=None, size=None):
        window = FileManagerApp(settings or self.settings)
        if size:
            window.resize(*size)
        self.addCleanup(self._dispose, window)
        window.show()
        window.activateWindow()
        _wait_until(lambda: window._state_restore_done)
        return window

    @staticmethod
    def _dispose(window):
        if not window._closing:
            window.close()
        window.deleteLater()
        QTest.qWait(0)

    def test_tab_menu_and_view_keep_one_pane_and_restore_keyboard_focus(self):
        window = self._window(size=(1280, 620))
        view = next(action.menu() for action in window.menuBar().actions() if action.text() == "&View")
        controls = view.actions()[:3]
        self.assertEqual([action.text() for action in controls],
                         ["Show left pane", "Show right pane", "Show Bookmarks and Libraries"])
        self.assertTrue(all(action.isCheckable() for action in controls))
        left, right = window._left_panel, window._right_panel
        window._setActivePanel(left)
        left.tableView().setFocus()
        window._onToggleQuickView()
        self.assertIs(window._right_stack.currentWidget(), window._right_quick_view)

        menu = window._left_tabs.tabContextMenu(-1)
        self.assertEqual(menu.actions()[0].text(), "Hide this pane")
        menu.actions()[0].trigger()
        menu.deleteLater()
        self.assertIs(window._right_stack.currentWidget(), right)
        self.assertTrue(window._pane_hosts["left"].isHidden())
        self.assertTrue(window._center_buttons.isHidden())
        self.assertIs(window._active_panel, right)
        self.assertTrue(right.tableView().hasFocus())
        self.assertEqual(self._readState().getPaneLayout(), "right")
        self.assertTrue(window._pane_actions["right"].isChecked())
        self.assertFalse(window._pane_actions["right"].isEnabled())
        self.assertFalse(window._pane_actions["left"].isChecked())
        self.assertFalse(window._action_quick_view.isEnabled())
        self.assertFalse(window._action_mirror.isEnabled())
        self.assertFalse(window._action_swap_panes.isEnabled())
        self.assertFalse(window._libraries_panel._other_pane_available)
        self.assertTrue(all(not action.isEnabled() for action in window._two_pane_shortcuts))
        command = next(item for item in window._commands if item["id"] == "compare")
        self.assertIn("Show both", window._commandUnavailable(command))

        button = window._pane_restore_buttons["right"]
        button.setFocus()
        QTest.keyClick(button, Qt.Key_Tab)
        self.assertIsNot(_APP.focusWidget(), button)
        self.assertIs(window._active_panel, right)
        for width in (480, 640, 1100):
            window.resize(width, 620)
            QTest.qWait(30)
            self.assertEqual(window.width(), width)
            self.assertTrue(window._pane_hosts["left"].isHidden())
            self.assertTrue(button.isVisible())
            for control, *_ in window._bottom_button_specs:
                self.assertTrue(control.isVisible())
                self.assertLessEqual(control.mapTo(window, QPoint()).x() + control.width(), width)

        window.resize(480, 620)
        button.click()
        self.assertTrue(window._pane_hosts["left"].isVisible())
        self.assertTrue(window._center_buttons.isVisible())
        self.assertGreaterEqual(window.width(), 640)
        self.assertTrue(window._pane_actions["left"].isChecked())
        window._pane_actions["right"].trigger()
        self.assertEqual(self._readState().getPaneLayout(), "left")
        self.assertIs(window._active_panel, left)

    def test_hidden_tabs_wait_for_first_reveal_and_survive_close(self):
        tab_state = {
            "tabs": [{"current_path": str(self.right), "filter_text": "work"},
                     {"current_path": str(self.left)}],
            "active": 0,
        }
        self.settings.setPanelState("right", tab_state)
        self.settings.setPaneLayout("left")
        self.settings.setSetting("window_geometry", {"x": 80, "y": 80, "width": 480, "height": 620})
        self.settings.saveAll()
        window = self._window()
        self.assertEqual(window.width(), 480)
        self.assertEqual(window._right_panel.currentPath(), "")
        self.assertEqual(window._right_panel.sourceModel()._scan_generation, 0)
        window.close()

        reloaded = self._readState()
        self.assertEqual(reloaded.getPaneLayout(), "left")
        self.assertEqual(reloaded.getPanelState("right")["tabs"], tab_state["tabs"])
        window = self._window(reloaded)
        self.assertEqual(window._right_panel.currentPath(), "")
        window._pane_actions["right"].trigger()
        self.assertEqual(window._right_tabs.count(), 2)
        self.assertEqual(window._right_panel.currentPath(), str(self.right))
        self.assertEqual(window._right_panel.filterEdit().text(), "work")

    def test_revealing_a_running_pane_applies_one_refresh_and_keeps_selection(self):
        for index in range(60):
            (self.right / f"item-{index}.txt").touch()
        window = self._window()
        panel = window._right_panel
        _wait_until(lambda: not panel.sourceModel().isLoading())
        panel.tableView().selectRow(36)
        selected = panel.selectedPaths()
        self.assertEqual(len(selected), 1)
        bar = panel.tableView().verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        scroll_position = bar.value()
        self.assertGreater(scroll_position, 0)
        window._pane_actions["right"].trigger()

        with mock.patch.object(panel.sourceModel(), "loadDirectory", wraps=panel.sourceModel().loadDirectory) as load:
            panel._onWatchedDirectoryChanged(str(self.right))
            panel.refresh(force_rescan=False)
            panel.refresh(force_rescan=True)
            load.assert_not_called()
            window._pane_actions["right"].trigger()
            load.assert_called_once_with(str(self.right), force_rescan=True)
        _wait_until(lambda: not panel.sourceModel().isLoading())
        self.assertEqual(panel.selectedPaths(), selected)
        self.assertEqual(bar.value(), scroll_position)

    def test_function_keys_choose_a_destination_in_single_pane_mode(self):
        (self.left / "notes.txt").touch()
        self.settings.setPaneLayout("left")
        window = self._window(size=(480, 620))
        pane = window._left_panel
        _wait_until(lambda: pane.proxyModel().rowCount() > 0)
        table = pane.tableView()
        table.selectRow(0)
        table.setFocus()
        with mock.patch.object(window, "_chooseTransferFolder", return_value="") as choose:
            QTest.keyClick(table, Qt.Key_F6)
            QTest.keyClick(table, Qt.Key_F7)
            self.assertEqual(choose.call_args_list, [mock.call("Copy", str(self.left)),
                                                    mock.call("Move", str(self.left))])

    def test_profile_round_trip_replaces_hidden_pane_state(self):
        window = self._window()
        incoming = SettingsManager(str(self.root / "incoming"), enable_backup=False)
        imported = self.root / "from-profile"
        imported.mkdir()
        incoming.setPaneLayout("right")
        incoming.setPanelState("left", {"current_path": str(imported)})
        profile = incoming.exportProfile(str(self.root / "profile.json"))

        window._settings.importProfile(profile)
        window._onSettingsProfileImported()
        self.assertIs(window._active_panel, window._right_panel)
        self.assertTrue(window._pane_hosts["left"].isHidden())
        window._pane_actions["left"].trigger()
        self.assertEqual(window._left_panel.currentPath(), str(imported))

    def test_sidebar_persists_rail_and_width_and_preserves_an_offline_bookmark(self):
        path = str(self.root / "offline" / "schedule.txt")
        self.settings.addBookmark("Schedule", path, kind="file")
        window = self._window(size=(1400, 650))
        self.assertFalse(window._sidebar_collapsed)
        window._main_splitter.moveSplitter(320, 1)
        window._sidebar_tabs.cornerWidget().click()
        self.assertTrue(window._sidebar_rail.isVisible())
        self.assertTrue(self._readState().getSidebarState()["hidden"])
        self.assertEqual(self._readState().getState("bookmarks_panel_width"), 320)
        window._sidebar_rail._bookmarks.click()
        self.assertFalse(self._readState().getSidebarState()["hidden"])
        self.assertEqual(window._main_splitter.sizes()[0], 320)
        with mock.patch("bookmarks_panel.os.path.isfile", side_effect=AssertionError("Probed an offline bookmark")):
            window._bookmarks_panel.refreshIcons()
            self.assertEqual(window._bookmarks_panel.getStructure()[0]["kind"], "file")

    def test_library_scan_waits_for_opening_and_does_not_overwrite_a_relocated_root(self):
        manager = LibraryManager(self.settings)
        library = manager.createLibrary("Work")
        root = manager.addRoot(library["id"], str(self.left))["root"]
        started = threading.Event()
        finish = threading.Event()
        worker_thread = []

        def discover(_manager, _snapshot, _cancel):
            worker_thread.append(QThread.currentThread())
            started.set()
            finish.wait(2)
            return {(library["id"], root["id"]): str(self.left)}

        with mock.patch.object(LibraryManager, "discoverLibraryRoots", autospec=True, side_effect=discover):
            window = self._window(size=(1000, 620))
            self.assertFalse(started.is_set())
            try:
                window._sidebar_rail._libraries.click()
                _wait_until(started.is_set)
                self.assertIsNot(worker_thread[0], _APP.thread())
                self.assertTrue(manager.locateRoot(library["id"], root["id"], str(self.right)))
                finish.set()
                _wait_until(lambda: window._library_worker is None)
                current = manager.getLibraries()[0]["roots"][0]["path"]
                self.assertEqual(os.path.normcase(current), os.path.normcase(str(self.right)))
            finally:
                finish.set()
