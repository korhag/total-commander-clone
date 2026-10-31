"""
The three action-icon sheets, recolored from the theme.
"""

import tempfile
import unittest

from PyQt5.QtWidgets import QApplication

from action_icons import (
    _coloredImage,
    _resetForTests,
    iconForAction,
    normalizeIconSet,
    setIconColors,
    setIconSet,
)
from settings_dialog import SettingsDialog
from settings_manager import SettingsManager


_APP = QApplication.instance() or QApplication([])


def _opaque_fraction(image):
    width = image.width()
    height = image.height()
    opaque = 0
    samples = 0
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            samples += 1
            if image.pixelColor(x, y).alpha() > 20:
                opaque += 1
    return opaque / max(1, samples)


# ------------------------------------------------------------
# Class: TestActionIcons
# Purpose: Unknown set ids fall back to tiles, each sheet
#          produces a readable icon, and Settings remembers
#          the choice.
# ------------------------------------------------------------
class TestActionIcons(unittest.TestCase):

    def tearDown(self):
        _resetForTests()

    def test_unknown_set_is_tiles(self):
        self.assertEqual(normalizeIconSet("nope"), "tile")
        self.assertEqual(normalizeIconSet("LINE"), "line")
        self.assertEqual(normalizeIconSet(""), "tile")

    def test_tile_copy_is_transparent_outside_the_shape(self):
        setIconSet("tile")
        setIconColors("#3366cc", "#eeeeee")
        image = _coloredImage("copy", False)
        self.assertFalse(image.isNull())
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        self.assertGreater(center.alpha(), 200)
        self.assertFalse(iconForAction("copy").isNull())

    def test_accent_recolors_a_tile(self):
        setIconSet("tile")
        setIconColors("#ff0000", "#eeeeee")
        red = _coloredImage("copy", False)
        setIconColors("#00aa00", "#eeeeee")
        green = _coloredImage("copy", False)
        changed = False
        for y in range(0, red.height(), 3):
            for x in range(0, red.width(), 3):
                left = red.pixelColor(x, y)
                right = green.pixelColor(x, y)
                if left.alpha() > 200 and right.alpha() > 200 and left.red() != right.red():
                    changed = True
                    break
            if changed:
                break
        self.assertTrue(changed)

    def test_line_icon_is_mostly_clear(self):
        setIconSet("line")
        setIconColors("#3366cc", "#f4f4f4")
        image = _coloredImage("back", False)
        self.assertFalse(image.isNull())
        self.assertLess(_opaque_fraction(image), 0.35)

    def test_mixed_lower_rows_stay_line_icons(self):
        setIconSet("mixed")
        setIconColors("#3366cc", "#f4f4f4")
        image = _coloredImage("settings", False)
        self.assertFalse(image.isNull())
        self.assertLess(_opaque_fraction(image), 0.35)

    def test_settings_dialog_saves_the_icon_set(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = SettingsManager(folder, enable_backup=False)
            self.assertEqual(manager.getSetting("action_icon_set"), "tile")
            dialog = SettingsDialog(manager)
            line_index = dialog._icon_set.findData("line")
            self.assertGreaterEqual(line_index, 0)
            dialog._icon_set.setCurrentIndex(line_index)
            self.assertEqual(dialog.values()["action_icon_set"], "line")
            self.assertGreaterEqual(dialog.minimumWidth(), 680)
            self.assertTrue(dialog._font_hint.wordWrap())
            self.assertTrue(dialog._density_hint.wordWrap())
            self.assertTrue(dialog._profile_hint.wordWrap())
            dialog.close()
            dialog.deleteLater()
