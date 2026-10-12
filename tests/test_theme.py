"""
Theme registry: every dark palette is complete, stylesheets build,
and an unknown theme id falls back to Dark.
"""

from __future__ import annotations

import re
import unittest

from theme import (
    PALETTE_KEYS,
    THEMES,
    UI_SCALE_PRESETS,
    _rgba,
    getPalette,
    getThemeChoices,
    getThemeStylesheet,
    getUiMetrics,
)


# ------------------------------------------------------------
# Class: TestThemePalettes
# Purpose: Guard the selectable dark themes and their QSS.
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


if __name__ == "__main__":
    unittest.main()
