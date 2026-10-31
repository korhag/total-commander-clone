"""
Toolbar icon size and whether the buttons show text.
"""

import unittest

from file_manager_app import (
    normalizeToolbarButtonStyle,
    normalizeToolbarIconSize,
    toolbarIconPixels,
)


# ------------------------------------------------------------
# Class: TestToolbarAppearance
# Purpose: Unknown saved values fall back to icons-and-text
#          and small icons. Large is twice the theme size.
# ------------------------------------------------------------
class TestToolbarAppearance(unittest.TestCase):

    def test_unknown_style_is_icons_and_text(self):
        self.assertEqual(normalizeToolbarButtonStyle("nope"), "text_beside")
        self.assertEqual(normalizeToolbarButtonStyle(""), "text_beside")
        self.assertEqual(normalizeToolbarButtonStyle("ICON_ONLY"), "icon_only")
        self.assertEqual(normalizeToolbarButtonStyle("text_under"), "text_under")

    def test_unknown_size_is_small_and_large_is_double(self):
        self.assertEqual(normalizeToolbarIconSize("huge"), "small")
        self.assertEqual(normalizeToolbarIconSize(None), "small")
        self.assertEqual(normalizeToolbarIconSize("MEDIUM"), "medium")
        self.assertEqual(toolbarIconPixels(16, "small"), 16)
        self.assertEqual(toolbarIconPixels(16, "medium"), 24)
        self.assertEqual(toolbarIconPixels(16, "large"), 32)
        self.assertEqual(toolbarIconPixels(16, "nope"), 16)
