"""Date display preferences and chronological file-list sorting."""

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QMenu, QMessageBox

from file_manager_app import FileManagerApp
from file_panel import (
    DATE_MODIFIED_FORMATS,
    DEFAULT_DATE_MODIFIED_FORMAT,
    FilePanel,
    format_date_modified,
)
from settings_dialog import SettingsDialog
from settings_manager import SettingsManager


_APP = QApplication.instance() or QApplication([])


def _visible_names(panel):
    model = panel._proxy_model
    return [model.data(model.index(row, 0)) for row in range(model.rowCount())]


class TestDateModifiedSorting(unittest.TestCase):
    def setUp(self):
        self.panel = FilePanel("left")
        model = self.panel._source_model
        model.beginResetModel()
        model._entries = [
            self._entry("folder_jan", True, datetime(2026, 1, 31, 23, 59, 50)),
            self._entry("folder_feb", True, datetime(2026, 2, 1, 0, 0, 10)),
            self._entry("file_jan", False, datetime(2026, 1, 31, 23, 59, 50)),
            self._entry("file_early", False, datetime(2026, 2, 1, 0, 0, 10)),
            self._entry("file_late", False, datetime(2026, 2, 1, 0, 0, 50)),
        ]
        model.endResetModel()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)

    @staticmethod
    def _entry(name, is_dir, modified):
        return {
            "name": name,
            "is_dir": is_dir,
            "size": -1 if is_dir else 1,
            "type": "Folder" if is_dir else "File",
            "mod_time": modified.timestamp(),
            "full_path": name,
        }

    def test_formats_render_expected_local_dates(self):
        timestamp = datetime(2026, 2, 1, 14, 5, 6).timestamp()
        expected = {
            "yyyy_mm_dd": "2026/02/01",
            "yy_mm_dd": "26/02/01",
            "yyyy_mm_dd_hm": "2026/02/01 14:05",
            "yy_mm_dd_hm": "26/02/01 14:05",
            "dd_mm_yyyy": "01/02/2026",
            "dd_mm_yy": "01/02/26",
            "dd_mm_yyyy_hm": "01/02/2026 14:05",
            "dd_mm_yy_hm": "01/02/26 14:05",
            "mm_dd_yyyy": "02/01/2026",
            "mm_dd_yyyy_hm": "02/01/2026 14:05",
            "yyyy_mm_dd_dash": "2026-02-01",
            "yyyy_mm_dd_dash_hm": "2026-02-01 14:05",
            "yyyy_mm_dd_dash_hms": "2026-02-01 14:05:06",
        }
        self.assertTrue(set(expected).issubset(DATE_MODIFIED_FORMATS))
        for format_key, value in expected.items():
            with self.subTest(format_key=format_key):
                self.assertEqual(format_date_modified(timestamp, format_key), value)
        self.assertEqual(format_date_modified(timestamp, "unknown"), "2026/02/01 14:05")

    def test_date_sorts_by_timestamp_and_keeps_selection_when_format_changes(self):
        orders = (
            (
                Qt.AscendingOrder,
                ["folder_jan", "folder_feb", "file_jan", "file_early", "file_late"],
            ),
            (
                Qt.DescendingOrder,
                ["folder_feb", "folder_jan", "file_late", "file_early", "file_jan"],
            ),
        )
        for direction, expected in orders:
            with self.subTest(direction=direction):
                self.panel._table.sortByColumn(3, direction)
                self.panel._reselectPaths(["file_early"])
                self.assertEqual(_visible_names(self.panel), expected)
                for format_key in DATE_MODIFIED_FORMATS:
                    self.panel.applyDateModifiedFormat(format_key)
                    self.assertEqual(_visible_names(self.panel), expected)
                    self.assertEqual(self.panel.selectedPaths(), ["file_early"])

    def test_format_refits_automatic_width_and_preserves_locked_width(self):
        self.panel.resize(1400, 420)
        self.panel.show()
        QTest.qWait(100)

        self.panel.applyDateModifiedFormat("yyyy_mm_dd_dash_hms")
        self.assertEqual(
            self.panel._table.columnWidth(3), self.panel._preferredWidthForColumn(3)
        )

        self.panel._table.setColumnWidth(3, 220)
        self.panel._setColumnWidthLock(3, True)
        locked_width = self.panel._table.columnWidth(3)
        self.panel.applyDateModifiedFormat("dd_mm_yy")
        self.assertEqual(self.panel._table.columnWidth(3), locked_width)


class TestDateModifiedPreference(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.files = os.path.join(self.root, "files")
        os.mkdir(self.files)
        self.file_path = os.path.join(self.files, "item.txt")
        with open(self.file_path, "w", encoding="utf-8") as handle:
            handle.write("test")
        other_path = os.path.join(self.files, "other.txt")
        with open(other_path, "w", encoding="utf-8") as handle:
            handle.write("test")
        os.utime(self.file_path, (1_769_900_000, 1_769_900_000))
        os.utime(other_path, (1_769_900_030, 1_769_900_030))
        self.settings = SettingsManager(self.root, enable_backup=False)
        self.settings.setSetting("check_for_updates_on_startup", False)
        self.settings.setSetting("auto_refresh_panels", False)
        self.settings.setSetting("cache_recursive_scans", False)
        with patch("file_manager_app.os.path.expanduser", return_value=self.files):
            self.window = FileManagerApp(self.settings)
        for panel in self._panels():
            self.assertTrue(panel.navigateTo(self.files))
        for _ in range(100):
            if all(
                not panel._source_model.isLoading() and panel._source_model.rowCount() == 2
                for panel in self._panels()
            ):
                break
            QTest.qWait(20)
        else:
            self.fail("Both panels did not finish loading the test files")

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(0)
        self._tmp.cleanup()

    def _panels(self):
        return (self.window._left_panel, self.window._right_panel)

    def _assert_format(self, format_key):
        for panel in self._panels():
            self.assertEqual(panel.currentDateModifiedFormatKey(), format_key)

    def test_settings_accept_cancel_and_reload(self):
        for panel in self._panels():
            panel._table.sortByColumn(3, Qt.DescendingOrder)
            panel._reselectPaths([self.file_path])
            self.assertEqual(panel.selectedPaths(), [self.file_path])
            self.assertEqual(_visible_names(panel), ["other.txt", "item.txt"])

        def choose_format(dialog, result):
            self.assertEqual(
                dialog._date_modified_format.currentData(), DEFAULT_DATE_MODIFIED_FORMAT
            )
            dialog._date_modified_format.setCurrentIndex(
                dialog._date_modified_format.findData("dd_mm_yy_hm")
            )
            return result

        with patch.object(
            SettingsDialog, "exec_", lambda dialog: choose_format(dialog, QDialog.Rejected)
        ):
            self.window._onOpenSettings()
        self._assert_format(DEFAULT_DATE_MODIFIED_FORMAT)
        self.assertEqual(
            self.settings.getSetting("date_modified_format"), DEFAULT_DATE_MODIFIED_FORMAT
        )
        for panel in self._panels():
            self.assertEqual(_visible_names(panel), ["other.txt", "item.txt"])
            self.assertEqual(panel.selectedPaths(), [self.file_path])

        with patch.object(
            SettingsDialog, "exec_", lambda dialog: choose_format(dialog, QDialog.Accepted)
        ):
            self.window._onOpenSettings()
        self._assert_format("dd_mm_yy_hm")
        for panel in self._panels():
            self.assertEqual(_visible_names(panel), ["other.txt", "item.txt"])
            self.assertEqual(panel.selectedPaths(), [self.file_path])
            date = panel._proxy_model.data(panel._proxy_model.index(1, 3))
            self.assertEqual(
                date, format_date_modified(os.path.getmtime(self.file_path), "dd_mm_yy_hm")
            )

        reloaded = SettingsManager(self.root, enable_backup=False)
        self.assertEqual(reloaded.getSetting("date_modified_format"), "dd_mm_yy_hm")
        new_panel = FilePanel("left", settings_manager=reloaded)
        self.assertEqual(new_panel.currentDateModifiedFormatKey(), "dd_mm_yy_hm")
        new_panel.close()
        new_panel.deleteLater()

    def test_header_menu_updates_both_panes_and_settings(self):
        panel = self.window._left_panel
        header = panel._table.horizontalHeader()
        date_position = QPoint(header.sectionViewportPosition(3) + 1, 1)
        self.assertEqual(header.logicalIndexAt(date_position.x()), 3)

        def choose_from_menu(menu, _position):
            format_menu = next(
                action.menu() for action in menu.actions() if action.text() == "Date format"
            )
            actions = format_menu.actions()
            self.assertEqual(
                [action.text() for action in actions],
                [label for _, label in DATE_MODIFIED_FORMATS.values()],
            )
            self.assertEqual(
                [action.text() for action in actions if action.isChecked()],
                ["YYYY/MM/DD hh:mm"],
            )
            next(action for action in actions if action.text() == "YYYY-MM-DD hh:mm:ss").trigger()

        with patch.object(QMenu, "exec_", choose_from_menu):
            panel._onTableHeaderContextMenu(date_position)

        self._assert_format("yyyy_mm_dd_dash_hms")
        self.assertEqual(self.settings.getSetting("date_modified_format"), "yyyy_mm_dd_dash_hms")

        def check_selected_menu_item(menu, _position):
            format_menu = next(
                action.menu() for action in menu.actions() if action.text() == "Date format"
            )
            self.assertEqual(
                [action.text() for action in format_menu.actions() if action.isChecked()],
                ["YYYY-MM-DD hh:mm:ss"],
            )

        with patch.object(QMenu, "exec_", check_selected_menu_item):
            panel._onTableHeaderContextMenu(date_position)

        reloaded = SettingsManager(self.root, enable_backup=False)
        dialog = SettingsDialog(reloaded)
        self.assertEqual(dialog._date_modified_format.currentData(), "yyyy_mm_dd_dash_hms")
        dialog.close()
        dialog.deleteLater()

    def test_profile_import_applies_format_and_refreshes_dropdown(self):
        profile = os.path.join(self.root, "profile.json")
        self.settings.exportProfile(profile, {"date_modified_format": "mm_dd_yyyy_hm"})
        dialog = SettingsDialog(self.settings, self.window)
        dialog.profileImported.connect(self.window._onSettingsProfileImported)
        with patch("settings_dialog.QFileDialog.getOpenFileName", return_value=(profile, "")), \
             patch("settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("settings_dialog.QMessageBox.information"):
            dialog._onImportProfile()

        self._assert_format("mm_dd_yyyy_hm")
        self.assertEqual(dialog._date_modified_format.currentData(), "mm_dd_yyyy_hm")
        reloaded = SettingsManager(self.root, enable_backup=False)
        self.assertEqual(reloaded.getSetting("date_modified_format"), "mm_dd_yyyy_hm")
        dialog.close()
        dialog.deleteLater()

    def test_unknown_saved_format_uses_default(self):
        self.settings.setSetting("date_modified_format", "unknown")
        dialog = SettingsDialog(self.settings)
        self.assertEqual(dialog._date_modified_format.currentData(), DEFAULT_DATE_MODIFIED_FORMAT)
        for panel in self._panels():
            panel.applyDateModifiedFormat("unknown")
        self._assert_format(DEFAULT_DATE_MODIFIED_FORMAT)
        dialog.close()
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
