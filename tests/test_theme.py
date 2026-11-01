"""
Theme registry: every palette is complete, stylesheets build,
and an unknown theme id falls back to Dark.
"""

from __future__ import annotations

import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtGui import QColor, QFont, QTextCharFormat
from PyQt5.QtWidgets import QApplication, QDateTimeEdit, QSpinBox

from filter_options_dialog import configureCalendarWeek
from theme import (
    PALETTE_KEYS,
    THEMES,
    UI_SCALE_PRESETS,
    _rgba,
    applyTheme,
    getPalette,
    getThemeChoices,
    getThemeStylesheet,
    getUiMetrics,
)
from theme_palettes import OMARCHY_SEEDS, _mix, buildPalette

# Hand-tuned palettes. Omarchy seeds must not replace these.
_HAND_TUNED = (
    "dark",
    "matte_black",
    "osaka_jade",
    "tokyo_night",
    "gruvbox",
    "nord",
    "everforest",
)


def _contrast(color_a, color_b):
    """WCAG contrast, independent of theme_palettes.contrastRatio."""
    def luminance(hex_color):
        text = hex_color.lstrip("#")
        channels = [int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

        def linear(value):
            if value <= 0.04045:
                return value / 12.92
            return ((value + 0.055) / 1.055) ** 2.4

        red, green, blue = (linear(channel) for channel in channels)
        return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)

    lighter = luminance(color_a)
    darker = luminance(color_b)
    if lighter < darker:
        lighter, darker = darker, lighter
    return (lighter + 0.05) / (darker + 0.05)


# ------------------------------------------------------------
# Class: TestThemePalettes
# Purpose: Guard the selectable themes and their QSS.
# ------------------------------------------------------------
class TestThemePalettes(unittest.TestCase):

    def test_every_palette_has_required_keys(self):
        required = set(PALETTE_KEYS)
        for theme_id, spec in THEMES.items():
            colors = spec["colors"]
            self.assertEqual(
                set(colors),
                required,
                theme_id,
            )
            for key, value in colors.items():
                self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", f"{theme_id}.{key}")

    def test_choices_list_dark_palettes_then_light_and_system(self):
        choices = getThemeChoices()
        ids = [theme_id for theme_id, _label in choices]
        self.assertEqual(ids[: len(THEMES)], list(THEMES))
        self.assertEqual(ids[-2:], ["light", "system"])

    def test_stylesheet_builds_for_every_theme_and_density(self):
        leftover = re.compile(r"\{[a-zA-Z_]")
        for theme_id in THEMES:
            palette = getPalette(theme_id)
            for density in UI_SCALE_PRESETS:
                metrics = getUiMetrics(10, density)
                sheet = getThemeStylesheet(
                    palette, font_size_pt=10, metrics=metrics
                )
                self.assertTrue(sheet.strip(), f"{theme_id} {density}")
                self.assertIsNone(
                    leftover.search(sheet),
                    f"{theme_id} at {density}% still has a format placeholder",
                )
                self.assertIn(_rgba(palette["red"], 0.14), sheet)
                self.assertIn(_rgba(palette["active_border"], 0.18), sheet)
                if palette["red"].lower() != "#f38ba8":
                    self.assertNotIn("rgba(243, 139, 168", sheet)
                self.assertIn(palette["base"], sheet)

    def test_unknown_theme_falls_back_to_dark(self):
        dark = getPalette("dark")
        self.assertEqual(getPalette("not-a-theme"), dark)
        self.assertEqual(getPalette(""), dark)
        self.assertEqual(getPalette(None), dark)
        self.assertEqual(getPalette("  Matte_Black "), getPalette("matte_black"))

    def test_omarchy_seeds_do_not_replace_hand_tuned_themes(self):
        self.assertTrue(set(OMARCHY_SEEDS).isdisjoint(_HAND_TUNED))
        for theme_id, seed in OMARCHY_SEEDS.items():
            self.assertIn(theme_id, THEMES)
            self.assertEqual(THEMES[theme_id]["label"], seed["label"])
        self.assertEqual(THEMES["dark"]["colors"]["base"], "#1e1e2e")
        self.assertEqual(THEMES["nord"]["colors"]["base"], "#2e3440")
        self.assertEqual(THEMES["gruvbox"]["label"], "Gruvbox Dark")
        self.assertEqual(THEMES["matte_black"]["colors"]["active_border"], "#e68e0d")

    def test_choices_keep_hand_tuned_then_omarchy_labels_then_styles(self):
        choices = getThemeChoices()
        ids = [theme_id for theme_id, _label in choices]
        self.assertEqual(tuple(ids[: len(_HAND_TUNED)]), _HAND_TUNED)
        omarchy_labels = [label for _theme_id, label in choices[len(_HAND_TUNED):-2]]
        self.assertEqual(omarchy_labels, sorted(omarchy_labels, key=str.casefold))
        self.assertEqual(
            [theme_id for theme_id, _label in choices[len(_HAND_TUNED):-2]],
            list(OMARCHY_SEEDS),
        )
        self.assertEqual(ids[-2:], ["light", "system"])

    def test_mix_blends_endpoints_and_midpoint(self):
        self.assertEqual(_mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(_mix("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(_mix("#000000", "#ffffff", 0.5), "#808080")
        self.assertRegex(_mix("#112233", "#abcdef", 0.3), r"^#[0-9a-f]{6}$")

    def test_build_palette_fills_every_key(self):
        colors = buildPalette(OMARCHY_SEEDS["darcula"])
        self.assertEqual(set(colors), set(PALETTE_KEYS))
        for key, value in colors.items():
            self.assertRegex(value, r"^#[0-9a-f]{6}$", key)

    def test_build_palette_replaces_selection_that_matches_the_text(self):
        seed = OMARCHY_SEEDS["castle_on_a_lake"]
        colors = buildPalette(seed)
        self.assertNotEqual(colors["selection"], seed["foreground"])
        self.assertGreaterEqual(_contrast(colors["text"], colors["selection"]), 3)

    def test_text_contrast_on_base_panel_and_selection(self):
        for theme_id, spec in THEMES.items():
            colors = spec["colors"]
            for surface in ("base", "panel_bg", "selection"):
                ratio = _contrast(colors["text"], colors[surface])
                self.assertGreaterEqual(
                    ratio,
                    3,
                    f"{theme_id} text on {surface} contrast {ratio:.2f}",
                )


def _pixel(image, x, y):
    color = image.pixelColor(x, y)
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def _button_column_contrast(widget):
    """Best contrast between the field and the button column on the right."""
    widget.resize(240, 36)
    widget.show()
    QApplication.processEvents()
    image = widget.grab().toImage()
    field = _pixel(image, image.width() // 4, image.height() // 2)
    best = 1.0
    x0 = max(0, image.width() - 20)
    for x in range(x0, max(x0 + 1, image.width() - 1)):
        for y in range(2, image.height() - 2):
            best = max(best, _contrast(field, _pixel(image, x, y)))
    return best


def _up_button_is_a_plus(widget, text_color, surface_color):
    """A plus: the cross is the text color, and a nearby corner stays the surface."""
    del text_color
    widget.resize(240, 36)
    widget.show()
    QApplication.processEvents()
    image = widget.grab().toImage()
    width = image.width()
    height = image.height()
    best = 1.0
    mark_x = width - 9
    mark_y = max(4, height // 4)
    for x in range(width - 18, width - 2):
        for y in range(2, max(3, height // 2 - 1)):
            ratio = _contrast(_pixel(image, x, y), surface_color)
            if ratio > best:
                best = ratio
                mark_x = x
                mark_y = y
    horizontal = _pixel(image, max(0, mark_x - 1), mark_y)
    vertical = _pixel(image, mark_x, max(0, mark_y - 1))
    corner = _pixel(image, max(0, mark_x - 4), max(0, mark_y - 3))
    return (
        best >= 3
        and _contrast(horizontal, surface_color) >= 2
        and _contrast(vertical, surface_color) >= 2
        and _contrast(corner, surface_color) < 1.8
    )


# ------------------------------------------------------------
# Class: TestStepperContrast
# Purpose: Stepper and calendar buttons stay visible on every palette.
# ------------------------------------------------------------
class TestStepperContrast(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        cls._spin = QSpinBox()
        cls._date = QDateTimeEdit(QDateTime.currentDateTime())
        cls._date.setCalendarPopup(True)

    def test_stepper_and_date_buttons_clear_the_field(self):
        for theme_id, spec in THEMES.items():
            colors = spec["colors"]
            sheet = getThemeStylesheet(colors)
            for name, widget in (("spin", self._spin), ("date", self._date)):
                widget.setStyleSheet(sheet)
                ratio = _button_column_contrast(widget)
                self.assertGreaterEqual(
                    ratio,
                    3,
                    f"{theme_id} {name} button contrast {ratio:.2f}",
                )
            self.assertTrue(
                _up_button_is_a_plus(self._spin, colors["text"], colors["surface2"]),
                f"{theme_id} up button is not a plus",
            )

    def test_calendar_week_starts_on_monday(self):
        edit = QDateTimeEdit()
        edit.setCalendarPopup(True)
        calendar = edit.calendarWidget()
        friday = QTextCharFormat()
        friday.setForeground(QColor("#ff0000"))
        calendar.setWeekdayTextFormat(Qt.Friday, friday)
        calendar.setFirstDayOfWeek(Qt.Sunday)
        configureCalendarWeek(edit)
        self.assertEqual(calendar.firstDayOfWeek(), Qt.Monday)
        monday = calendar.weekdayTextFormat(Qt.Monday).foreground().color().name()
        self.assertEqual(
            calendar.weekdayTextFormat(Qt.Friday).foreground().color().name(),
            monday,
        )
        saturday = calendar.weekdayTextFormat(Qt.Saturday).foreground().color().name()
        self.assertEqual(
            calendar.weekdayTextFormat(Qt.Sunday).foreground().color().name(),
            saturday,
        )
        self.assertNotEqual(saturday, monday)


class _ThemeApp:
    """The slice of QApplication that applyTheme talks to."""

    def __init__(self):
        self.sheets = 0
        self._system_style_name = ""
        self._system_palette = None
        self._style = None

    def font(self):
        return QFont("Segoe UI", 10)

    def setFont(self, font):
        return None

    def style(self):
        return self._style

    def setStyle(self, style):
        self._style = style

    def setStyleSheet(self, sheet):
        self.sheets += 1


class TestApplyTheme(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_same_theme_is_applied_once(self):
        app = _ThemeApp()
        applyTheme(app, "nord", 10, 100)
        applyTheme(app, "nord", 10, 100)
        self.assertEqual(app.sheets, 1)
        applyTheme(app, "nord", 12, 100)
        self.assertEqual(app.sheets, 2)
        applyTheme(app, "nord", 12, 85)
        self.assertEqual(app.sheets, 3)


if __name__ == "__main__":
    unittest.main()
