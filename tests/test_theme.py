"""
Theme registry: every palette is complete, stylesheets build,
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


if __name__ == "__main__":
    unittest.main()
