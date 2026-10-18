"""
Total Commander Clone - Omarchy palette seeds

Bundled copies of the Omarchy themes that are not already hand-tuned in
theme.py. Values come from each theme's colors.toml, or from alacritty.toml
when that is the only palette file. The app does not read ~/.config/omarchy
at runtime, so the same list works on Windows.

buildPalette() expands a seed (about a dozen colors) into the full set of
keys in theme.PALETTE_KEYS.
"""

# ------------------------------------------------------------
# Contrast helpers
# ------------------------------------------------------------
_SHADE = "#000000"
_MIN_CONTRAST = 3.0


def _channels(hex_color):
    """Return (red, green, blue) ints for a #rrggbb color."""
    text = hex_color.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _hex(red, green, blue):
    return f"#{red:02x}{green:02x}{blue:02x}"


def _normalize(color):
    """Lower-case #rrggbb. Raises ValueError when the color is not 6 hex digits."""
    text = str(color).strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6 or any(char not in "0123456789abcdefABCDEF" for char in text):
        raise ValueError(f"Expected #rrggbb, got {color!r}")
    return f"#{text.lower()}"


# ------------------------------------------------------------
# Function: _mix
# Purpose: Blend two #rrggbb colors. ratio 0 returns color_a,
#          ratio 1 returns color_b.
# ------------------------------------------------------------
def _mix(color_a, color_b, ratio):
    ar, ag, ab = _channels(color_a)
    br, bg, bb = _channels(color_b)
    amount = float(ratio)

    def channel(start, end):
        value = int(round(start + (end - start) * amount))
        return max(0, min(255, value))

    return _hex(channel(ar, br), channel(ag, bg), channel(ab, bb))


def _luminance(hex_color):
    """Relative luminance (WCAG) of a #rrggbb color."""
    def linear(channel):
        value = channel / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = _channels(hex_color)
    return (0.2126 * linear(red)) + (0.7152 * linear(green)) + (0.0722 * linear(blue))


# ------------------------------------------------------------
# Function: contrastRatio
# Purpose: WCAG contrast of two #rrggbb colors (1 = identical).
# ------------------------------------------------------------
def contrastRatio(color_a, color_b):
    lighter = _luminance(color_a)
    darker = _luminance(color_b)
    if lighter < darker:
        lighter, darker = darker, lighter
    return (lighter + 0.05) / (darker + 0.05)


def _withContrast(color, against, minimum, toward):
    """
    Move color toward `toward` until contrastRatio(color, against) >= minimum.
    Returns `toward` when that color is the only one that qualifies.
    """
    if contrastRatio(color, against) >= minimum:
        return color
    best = toward
    low = 0.0
    high = 1.0
    for _step in range(16):
        mid = (low + high) / 2.0
        mixed = _mix(color, toward, mid)
        if contrastRatio(mixed, against) >= minimum:
            best = mixed
            high = mid
        else:
            low = mid
    if contrastRatio(best, against) < minimum:
        return toward
    return best


# ------------------------------------------------------------
# Function: buildPalette
# Purpose: Expand one Omarchy seed into the app's palette keys.
#          Surfaces are mixes of the background and foreground.
#          mantle and crust are the background darkened (a small
#          step on light themes). Text colors are nudged until
#          they stay readable on the background, and fills are
#          nudged until the text on them stays readable.
# ------------------------------------------------------------
def buildPalette(seed):
    background = _normalize(seed["background"])
    foreground = _normalize(seed["foreground"])
    accent = _normalize(seed["accent"])
    if "mode" in seed:
        light = seed.get("mode") == "light"
    else:
        light = _luminance(background) >= 0.5

    if light:
        crust = _mix(background, _SHADE, 0.10)
        mantle = _mix(background, _SHADE, 0.05)
        panel_bg = _mix(background, _SHADE, 0.03)
        input_bg = _mix(background, _SHADE, 0.04)
    else:
        crust = _mix(background, _SHADE, 0.40)
        mantle = _mix(background, _SHADE, 0.20)
        panel_bg = _mix(background, foreground, 0.05)
        input_bg = _mix(background, _SHADE, 0.12)

    surface0 = _mix(background, foreground, 0.08)
    surface1 = _mix(background, foreground, 0.15)
    surface2 = _mix(background, foreground, 0.24)
    overlay0 = _mix(background, foreground, 0.50)
    overlay1 = _mix(background, foreground, 0.68)
    subtext0 = _withContrast(
        _mix(background, foreground, 0.72), mantle, _MIN_CONTRAST, foreground
    )
    subtext1 = _withContrast(
        _mix(background, foreground, 0.86), mantle, _MIN_CONTRAST, foreground
    )

    def background_for(color):
        """Pull a fill toward the background until foreground text is readable on it."""
        return _withContrast(color, foreground, _MIN_CONTRAST, background)

    panel_bg = background_for(panel_bg)
    hover = background_for(_mix(background, foreground, 0.12))
    button = background_for(_mix(background, foreground, 0.08))
    button_hover = background_for(_mix(background, accent, 0.20))
    button_press = background_for(_mix(background, accent, 0.32))
    input_bg = background_for(input_bg)

    def readable(color):
        """Nudge a text color until it is readable on the window and the file list."""
        color = _normalize(color)
        color = _withContrast(color, background, _MIN_CONTRAST, foreground)
        return _withContrast(color, panel_bg, _MIN_CONTRAST, foreground)

    red = readable(seed["red"])
    green = readable(seed["green"])
    yellow = readable(seed["yellow"])
    blue = readable(seed["blue"])
    magenta = readable(seed["magenta"])
    cyan = readable(seed["cyan"])
    if seed.get("orange"):
        peach = readable(seed["orange"])
    else:
        peach = yellow
    # Accent-button hover paints `blue` behind crust-colored text.
    blue = _withContrast(blue, crust, _MIN_CONTRAST, foreground)

    selection = seed.get("selection")
    if selection:
        selection = _normalize(selection)
    selection_unusable = (
        not selection
        or selection in (foreground, background)
        or contrastRatio(foreground, selection) < _MIN_CONTRAST
    )
    if selection_unusable:
        selection = _mix(background, accent, 0.16 if light else 0.26)
    selection = background_for(selection)

    active_border = _withContrast(accent, crust, _MIN_CONTRAST, foreground)
    if seed.get("orange"):
        focus_source = _normalize(seed["orange"])
    else:
        focus_source = yellow
    panel_focus_ring = _withContrast(
        focus_source, panel_bg, _MIN_CONTRAST, foreground
    )
    if panel_focus_ring == active_border:
        panel_focus_ring = _withContrast(
            _mix(panel_focus_ring, foreground, 0.45),
            panel_bg,
            _MIN_CONTRAST,
            foreground,
        )
    if panel_focus_ring == active_border:
        panel_focus_ring = _withContrast(red, panel_bg, _MIN_CONTRAST, foreground)

    return {
        "base": background,
        "mantle": mantle,
        "crust": crust,
        "surface0": surface0,
        "surface1": surface1,
        "surface2": surface2,
        "overlay0": overlay0,
        "overlay1": overlay1,
        "text": foreground,
        "subtext0": subtext0,
        "subtext1": subtext1,
        "blue": blue,
        "lavender": magenta,
        "sapphire": cyan,
        "green": green,
        "red": red,
        "peach": peach,
        "yellow": yellow,
        "mauve": magenta,
        "rosewater": _mix(foreground, magenta, 0.35),
        "panel_bg": panel_bg,
        "active_border": active_border,
        "panel_focus_ring": panel_focus_ring,
        "hover": hover,
        "selection": selection,
        "border": surface1,
        "button": button,
        "button_hover": button_hover,
        "button_press": button_press,
        "input_bg": input_bg,
        "scrollbar_bg": background,
        "scrollbar_handle": _mix(background, foreground, 0.32),
        "scrollbar_hover": _mix(background, foreground, 0.48),
    }


# ------------------------------------------------------------
# Omarchy seeds
# Order is the Settings → Theme order (alphabetical by label).
# ANSI-only themes (Gold Rush, Golden Brown) map color1–color6
# to red, green, yellow, blue, magenta, cyan, and the cursor
# color to accent.
# ------------------------------------------------------------
OMARCHY_SEEDS = {
    "blackgold": {
        "label": "Blackgold",
        "mode": "dark",
        "background": "#0d0d0d",
        "foreground": "#ebdbb2",
        "accent": "#6e6a58",
        "red": "#d35f5f",
        "green": "#a3850e",
        "yellow": "#4d574e",
        "blue": "#6e6a58",
        "magenta": "#bfa75d",
        "cyan": "#7a6a2c",
        "orange": "#d86a29",
        "selection": "#241f16",
    },
    "blackturq": {
        "label": "Blackturq",
        "mode": "dark",
        "background": "#0a0a0a",
        "foreground": "#c8dcdc",
        "accent": "#adf0e9",
        "red": "#d35f5f",
        "green": "#8fecd5",
        "yellow": "#a9d1d7",
        "blue": "#adf0e9",
        "magenta": "#485362",
        "cyan": "#5a676b",
        "orange": "#ff8a4d",
        "selection": "#182826",
    },
    "castle_on_a_lake": {
        "label": "Castle on a Lake",
        "mode": "dark",
        "background": "#060606",
        "foreground": "#f0d4e4",
        "accent": "#9b6b9f",
        "red": "#a06048",
        "green": "#80a070",
        "yellow": "#d4b060",
        "blue": "#5870a8",
        "magenta": "#8060a0",
        "cyan": "#6090a0",
        "orange": "#c47838",
        "selection": "#f0d4e4",
    },
    "catppuccin_latte": {
        "label": "Catppuccin Latte",
        "mode": "light",
        "background": "#eff1f5",
        "foreground": "#4c4f69",
        "accent": "#1e66f5",
        "red": "#d20f39",
        "green": "#40a02b",
        "yellow": "#df8e1d",
        "blue": "#1e66f5",
        "magenta": "#ea76cb",
        "cyan": "#179299",
        "orange": "#d84e2b",
        "selection": "#ccd0da",
    },
    "darcula": {
        "label": "Darcula",
        "mode": "dark",
        "background": "#2b2b2b",
        "foreground": "#a9b7c6",
        "accent": "#ffd760",
        "red": "#ff6b68",
        "green": "#629755",
        "yellow": "#cc7832",
        "blue": "#6897bb",
        "magenta": "#9876aa",
        "cyan": "#39b2ac",
        "selection": "#3f4b6e",
    },
    "ethereal": {
        "label": "Ethereal",
        "mode": "dark",
        "background": "#060b1e",
        "foreground": "#ffcead",
        "accent": "#7d82d9",
        "red": "#ed5b5a",
        "green": "#92a593",
        "yellow": "#e9bb4f",
        "blue": "#7d82d9",
        "magenta": "#c89dc1",
        "cyan": "#a3bfd1",
        "orange": "#eb8b54",
        "selection": "#252e56",
    },
    "flexoki_light": {
        "label": "Flexoki Light",
        "mode": "light",
        "background": "#fffcf0",
        "foreground": "#100f0f",
        "accent": "#205ea6",
        "red": "#d14d41",
        "green": "#879a39",
        "yellow": "#d0a215",
        "blue": "#205ea6",
        "magenta": "#ce5d97",
        "cyan": "#3aa99f",
        "orange": "#d0772b",
        "selection": "#cecdc3",
    },
    "gold_rush": {
        "label": "Gold Rush",
        "mode": "dark",
        "background": "#121212",
        "foreground": "#d9d9d9",
        "accent": "#c9a227",
        "red": "#dbb42c",
        "green": "#a47e1b",
        "yellow": "#fad643",
        "blue": "#926c15",
        "magenta": "#b69121",
        "cyan": "#805b10",
        "selection": "#926c15",
    },
    "golden_brown": {
        "label": "Golden Brown",
        "mode": "dark",
        "background": "#0f0b05",
        "foreground": "#c3a983",
        "accent": "#c3a983",
        "red": "#a88c62",
        "green": "#dec8a7",
        "yellow": "#dec8a7",
        "blue": "#c3a983",
        "magenta": "#a88c62",
        "cyan": "#dec8a7",
    },
    "hackerman": {
        "label": "Hackerman",
        "mode": "dark",
        "background": "#0b0c16",
        "foreground": "#ddf7ff",
        "accent": "#82fb9c",
        "red": "#50f872",
        "green": "#4fe88f",
        "yellow": "#50f7d4",
        "blue": "#829dd4",
        "magenta": "#86a7df",
        "cyan": "#7cf8f7",
        "orange": "#50f7a3",
        "selection": "#1f253a",
    },
    "kanagawa": {
        "label": "Kanagawa",
        "mode": "dark",
        "background": "#1f1f28",
        "foreground": "#dcd7ba",
        "accent": "#dcd7ba",
        "red": "#c34043",
        "green": "#76946a",
        "yellow": "#c0a36e",
        "blue": "#7e9cd8",
        "magenta": "#957fb8",
        "cyan": "#6a9589",
        "orange": "#c17158",
        "selection": "#363646",
    },
    "last_horizon": {
        "label": "Last Horizon",
        "mode": "dark",
        "background": "#0c0b0c",
        "foreground": "#fafcfb",
        "accent": "#b59790",
        "red": "#c38b7b",
        "green": "#87a9b0",
        "yellow": "#6b5e73",
        "blue": "#b59790",
        "magenta": "#c4d8e2",
        "cyan": "#a5a0b6",
        "selection": "#584e51",
    },
    "lumon": {
        "label": "Lumon",
        "mode": "dark",
        "background": "#16242d",
        "foreground": "#d6e2ee",
        "accent": "#8bc9eb",
        "red": "#4d86b0",
        "green": "#5e95bc",
        "yellow": "#6fa4c9",
        "blue": "#6fb8e3",
        "magenta": "#8bc9eb",
        "cyan": "#b4e4f6",
        "orange": "#8bc9eb",
        "selection": "#243d56",
    },
    "lupine": {
        "label": "Lupine",
        "mode": "light",
        "background": "#fafafa",
        "foreground": "#212121",
        "accent": "#3264eb",
        "red": "#c900c4",
        "green": "#4a2fd0",
        "yellow": "#026fde",
        "blue": "#3264eb",
        "magenta": "#8a4ad7",
        "cyan": "#0c67de",
        "orange": "#026fde",
        "selection": "#d0d0d0",
    },
    "miasma": {
        "label": "Miasma",
        "mode": "dark",
        "background": "#222222",
        "foreground": "#c2c2b0",
        "accent": "#78824b",
        "red": "#685742",
        "green": "#5f875f",
        "yellow": "#b36d43",
        "blue": "#78824b",
        "magenta": "#bb7744",
        "cyan": "#c9a554",
        "orange": "#8d6242",
        "selection": "#383838",
    },
    "neovoid": {
        "label": "Neovoid",
        "mode": "dark",
        "background": "#000000",
        "foreground": "#e0e0e0",
        "accent": "#00bfff",
        "red": "#ff0040",
        "green": "#00bfff",
        "yellow": "#1e90ff",
        "blue": "#00bfff",
        "magenta": "#1e90ff",
        "cyan": "#00bfff",
        "selection": "#333333",
    },
    "omacarchy": {
        "label": "Omacarchy",
        "mode": "dark",
        "background": "#1c1c1e",
        "foreground": "#ffffff",
        "accent": "#ffffff",
        "red": "#4a4a4a",
        "green": "#5a5a5a",
        "yellow": "#6a6a6a",
        "blue": "#7a7a7a",
        "magenta": "#8a8a8a",
        "cyan": "#9a9a9a",
        "selection": "#808080",
    },
    "omaled": {
        "label": "Omaled",
        "mode": "dark",
        "background": "#000000",
        "foreground": "#e66063",
        "accent": "#860111",
        "red": "#dd2c2f",
        "green": "#bd1f21",
        "yellow": "#e66063",
        "blue": "#ac1c1e",
        "magenta": "#f1a7a9",
        "cyan": "#ec8385",
        "orange": "#e35053",
        "selection": "#860111",
    },
    "retro_82": {
        "label": "Retro 82",
        "mode": "dark",
        "background": "#05182e",
        "foreground": "#f6dcac",
        "accent": "#faa968",
        "red": "#f85525",
        "green": "#028391",
        "yellow": "#e97b3c",
        "blue": "#3f8f8a",
        "magenta": "#3f8f8a",
        "cyan": "#8cbfb8",
        "orange": "#faa968",
        "selection": "#134e5a",
    },
    "ristretto": {
        "label": "Ristretto",
        "mode": "dark",
        "background": "#2c2525",
        "foreground": "#e6d9db",
        "accent": "#f38d70",
        "red": "#fd6883",
        "green": "#adda78",
        "yellow": "#f9cc6c",
        "blue": "#f38d70",
        "magenta": "#a8a9eb",
        "cyan": "#85dacc",
        "orange": "#fb9a77",
        "selection": "#403e41",
    },
    "rose_pine": {
        "label": "Rose Pine",
        "mode": "light",
        "background": "#faf4ed",
        "foreground": "#575279",
        "accent": "#56949f",
        "red": "#b4637a",
        "green": "#286983",
        "yellow": "#ea9d34",
        "blue": "#56949f",
        "magenta": "#907aa9",
        "cyan": "#d7827e",
        "orange": "#cf8057",
        "selection": "#dfdad9",
    },
    "solitude": {
        "label": "Solitude",
        "mode": "dark",
        "background": "#101315",
        "foreground": "#cacccc",
        "accent": "#798186",
        "red": "#565d60",
        "green": "#9fa5a9",
        "yellow": "#d9dbdc",
        "blue": "#798186",
        "magenta": "#aeaeae",
        "cyan": "#707070",
        "selection": "#343d41",
    },
    "vantablack": {
        "label": "Vantablack",
        "mode": "dark",
        "background": "#000000",
        "foreground": "#ffffff",
        "accent": "#8d8d8d",
        "red": "#a4a4a4",
        "green": "#b6b6b6",
        "yellow": "#cecece",
        "blue": "#8d8d8d",
        "magenta": "#9b9b9b",
        "cyan": "#b0b0b0",
        "orange": "#b9b9b9",
        "selection": "#1a1a1a",
    },
    "white": {
        "label": "White",
        "mode": "light",
        "background": "#ffffff",
        "foreground": "#000000",
        "accent": "#6e6e6e",
        "red": "#2a2a2a",
        "green": "#3a3a3a",
        "yellow": "#4a4a4a",
        "blue": "#1a1a1a",
        "magenta": "#2e2e2e",
        "cyan": "#3e3e3e",
        "selection": "#c0c0c0",
    },
}
