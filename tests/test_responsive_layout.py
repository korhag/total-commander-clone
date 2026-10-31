"""
Narrow-window layout: width tiers, the panel overflow row, and tab limits.
"""

from __future__ import annotations

import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from file_panel import FilePanel
from panel_tabs import PanelTabBar
from responsive_layout import (
    PANEL_COMPACT_WIDTH,
    PANEL_MIN_WIDTH,
    PANEL_NARROW_WIDTH,
    PANEL_TAB_MAX_WIDTH,
    PANEL_TAB_MIN_WIDTH,
    TIER_COMPACT,
    TIER_NARROW,
    TIER_WIDE,
    layoutTier,
    scaled,
)
from sidebar_rail import SidebarRail


_APP = QApplication.instance() or QApplication([])


# ------------------------------------------------------------
# Class: TestLayoutTier
# Purpose: The pure width cut-offs, including UI scale.
# ------------------------------------------------------------
class TestLayoutTier(unittest.TestCase):

    def test_cutoffs_at_normal_scale(self):
        self.assertEqual(layoutTier(PANEL_COMPACT_WIDTH), TIER_WIDE)
        self.assertEqual(layoutTier(PANEL_COMPACT_WIDTH - 1), TIER_COMPACT)
        self.assertEqual(layoutTier(PANEL_NARROW_WIDTH), TIER_COMPACT)
        self.assertEqual(layoutTier(PANEL_NARROW_WIDTH - 1), TIER_NARROW)
        self.assertEqual(layoutTier(None), TIER_WIDE)

    def test_scale_moves_the_cutoffs(self):
        self.assertEqual(layoutTier(900, layout_scale=2.0), TIER_NARROW)
        self.assertEqual(
            layoutTier(scaled(PANEL_COMPACT_WIDTH, 2.0), layout_scale=2.0),
            TIER_WIDE,
        )


# ------------------------------------------------------------
# Class: TestFilePanelResponsive
# Purpose: A narrow panel keeps every action, and does not save
#          the columns it hid only because it was narrow.
# ------------------------------------------------------------
class TestFilePanelResponsive(unittest.TestCase):

    def setUp(self):
        self.panel = FilePanel("left")
        self._setWidth(900)

    def tearDown(self):
        self.panel.deleteLater()
        _APP.processEvents()

    def _setWidth(self, width):
        # resize() updates the size immediately. Qt delivers resizeEvent
        # once the widget is on screen; apply the tier here so the test
        # checks the same method the event calls.
        self.panel.resize(width, 500)
        self.panel._applyResponsiveTier()

    def test_panel_can_shrink_below_the_full_row(self):
        self.assertLessEqual(
            self.panel.minimumSizeHint().width(),
            scaled(PANEL_MIN_WIDTH),
        )

    def test_wide_row_shows_labels_and_hides_overflow(self):
        self.assertFalse(self.panel._btn_home.isHidden())
        self.assertFalse(self.panel._btn_new_folder.isHidden())
        self.assertTrue(self.panel._btn_overflow.isHidden())
        self.assertEqual(self.panel._btn_filter_options.text(), "Filter settings")
        self.assertEqual(self.panel._btn_thumbnails.text(), "Thumbnails")
        self.assertTrue(self.panel._drive_line_edit.alignment() & Qt.AlignLeft)
        self.assertFalse(self.panel._btn_favorite.isHidden())

    def test_compact_row_is_icon_only(self):
        self._setWidth(500)
        self.assertFalse(self.panel._btn_home.isHidden())
        self.assertTrue(self.panel._btn_overflow.isHidden())
        self.assertEqual(self.panel._btn_filter_options.text(), "Filter")
        self.assertNotEqual(self.panel._btn_thumbnails.text(), "Thumbnails")

    def test_narrow_row_moves_controls_into_the_overflow_menu(self):
        chosen = self.panel.getColumnVisibility()
        self._setWidth(260)
        self.assertTrue(self.panel._btn_home.isHidden())
        self.assertTrue(self.panel._btn_new_folder.isHidden())
        self.assertTrue(self.panel._btn_forward.isHidden())
        self.assertTrue(self.panel._drive_container.isHidden())
        self.assertTrue(self.panel._btn_copy_path.isHidden())
        self.assertFalse(self.panel._btn_back.isHidden())
        self.assertFalse(self.panel._btn_up.isHidden())
        self.assertFalse(self.panel._btn_favorite.isHidden())
        self.assertFalse(self.panel._btn_overflow.isHidden())
        labels = [action.text() for action in self.panel._overflow_menu.actions()]
        self.assertIn("Home", labels)
        self.assertIn("Favorite", labels)
        self.assertIn("New folder", labels)
        self.assertIn("Forward", labels)
        self.assertIn("Drives", labels)
        self.assertIn("Copy path", labels)
        self.assertIn("Paste path", labels)
        self.assertIn("Open in file manager", labels)
        self.assertEqual(self.panel.getColumnVisibility(), chosen)
        type_col = self.panel.COLUMN_VISIBILITY_KEYS.index("type")
        date_col = self.panel.COLUMN_VISIBILITY_KEYS.index("date_modified")
        self.assertTrue(self.panel.tableView().isColumnHidden(type_col))
        self.assertTrue(self.panel.tableView().isColumnHidden(date_col))

    def test_widening_restores_the_row_and_columns(self):
        self._setWidth(260)
        self._setWidth(900)
        self.assertFalse(self.panel._btn_home.isHidden())
        self.assertTrue(self.panel._btn_overflow.isHidden())
        type_col = self.panel.COLUMN_VISIBILITY_KEYS.index("type")
        date_col = self.panel.COLUMN_VISIBILITY_KEYS.index("date_modified")
        self.assertFalse(self.panel.tableView().isColumnHidden(type_col))
        self.assertFalse(self.panel.tableView().isColumnHidden(date_col))

    def test_user_hidden_column_stays_hidden_when_wide(self):
        self.panel.applyColumnVisibility({
            "name": True,
            "size": True,
            "type": False,
            "date_modified": True,
        })
        self._setWidth(260)
        self._setWidth(900)
        type_col = self.panel.COLUMN_VISIBILITY_KEYS.index("type")
        self.assertTrue(self.panel.tableView().isColumnHidden(type_col))
        self.assertFalse(self.panel.getColumnVisibility()["type"])
        self.assertTrue(self.panel.getColumnVisibility()["date_modified"])


# ------------------------------------------------------------
# Class: TestPanelTabWidth
# Purpose: Long folder names elide instead of eating the strip.
# ------------------------------------------------------------
class TestPanelTabWidth(unittest.TestCase):

    def test_tab_width_stays_between_the_limits(self):
        panel = FilePanel("left")
        bar = PanelTabBar(panel)
        self.assertEqual(bar.elideMode(), Qt.ElideMiddle)
        bar.setTabText(0, "Kingdom of Saudi Arabia documents and photos")
        long_hint = bar.tabSizeHint(0)
        self.assertEqual(long_hint.width(), scaled(PANEL_TAB_MAX_WIDTH))
        bar.setTabText(0, "A")
        short_hint = bar.tabSizeHint(0)
        self.assertGreaterEqual(short_hint.width(), scaled(PANEL_TAB_MIN_WIDTH))
        self.assertLessEqual(short_hint.width(), scaled(PANEL_TAB_MAX_WIDTH))
        panel.deleteLater()


# ------------------------------------------------------------
# Class: TestSidebarRail
# Purpose: The rail asks for the tab the user clicked.
# ------------------------------------------------------------
class TestSidebarRail(unittest.TestCase):

    def test_buttons_request_their_tabs(self):
        rail = SidebarRail()
        requested = []
        rail.tabRequested.connect(requested.append)
        rail._bookmarks.click()
        rail._libraries.click()
        self.assertEqual(requested, [0, 1])
        rail.deleteLater()


if __name__ == "__main__":
    unittest.main()
