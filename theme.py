"""
Total Commander Clone - Theme stylesheets
Flat dark palettes (Catppuccin, Matte Black, Osaka Jade, and others)
plus Light and system styles. Sizes follow font size and interface density.
"""

import os

from PyQt5.QtGui import QFont

# Drive dropdown width: drive letters on Windows are short; Linux shows
# mounted folder names (for example "Kromeka-Shared"), so it needs more room.
_DRIVE_COMBO_BASE_WIDTH = (54, 48) if os.name == "nt" else (110, 96)

# ------------------------------------------------------------
# UI scale (Settings → Interface density)
# ------------------------------------------------------------
DEFAULT_UI_SCALE_PERCENT = 100
DEFAULT_FONT_SIZE_PT = 10  # baseline = 100% layout scale
UI_SCALE_PRESETS = (70, 75, 85, 100, 115)

_UI_SCALE_LABELS = {
    70: "Extra compact (70%)",
    75: "Very compact (75%)",
    85: "Compact (85%)",
    100: "Normal (100%)",
    115: "Comfortable (115%)",
}


def normalize_ui_scale(value):
    """
    Map settings value to a density preset percent (70/75/85/100/115).
    Accepts int/float, legacy strings compact/normal/comfortable.
    """
    if isinstance(value, str):
        key = value.strip().lower().replace(" ", "_")
        if key in ("extra_compact", "extracompact", "70"):
            return 70
        if key in ("very_compact", "verycompact", "75"):
            return 75
        if key in ("compact", "85"):
            return 85
        if key in ("comfortable", "115", "large"):
            return 115
        if key in ("normal", "100"):
            return 100
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_UI_SCALE_PERCENT
    if n in UI_SCALE_PRESETS:
        return n
    if n <= 72:
        return 70
    if n <= 80:
        return 75
    if n <= 92:
        return 85
    if n >= 108:
        return 115
    return 100


def ui_scale_label(percent):
    return _UI_SCALE_LABELS.get(normalize_ui_scale(percent), "Normal (100%)")


def step_ui_scale(current, direction):
    """
    Move to the next or previous Interface density preset.
    direction: positive = larger (Comfortable), negative = smaller (Extra compact).
    Returns the new percent, or the current value if already at the limit.
    """
    presets = UI_SCALE_PRESETS
    current = normalize_ui_scale(current)
    try:
        idx = presets.index(current)
    except ValueError:
        idx = presets.index(DEFAULT_UI_SCALE_PERCENT)
    new_idx = idx + (1 if direction > 0 else -1)
    if 0 <= new_idx < len(presets):
        return presets[new_idx]
    return current


def getUiMetrics(font_size_pt, ui_scale_percent=DEFAULT_UI_SCALE_PERCENT):
    """
    Pixel metrics for layout widgets and QSS (padding, min-heights).

    Layout scales with both:
      - font_size_pt relative to DEFAULT_FONT_SIZE_PT (10 = 100%)
      - ui_scale_percent density preset (100 = Normal)

    So raising Font size grows row heights, icons, and controls with the text —
    not only the glyphs — keeping the file list readable.
    Floors keep path bar, rows, and sidebar tabs usable at small sizes.
    """
    density = normalize_ui_scale(ui_scale_percent) / 100.0
    b = max(8, min(24, int(font_size_pt)))
    font_factor = b / float(DEFAULT_FONT_SIZE_PT)
    scale = density * font_factor

    def px(base, minimum=1):
        return max(minimum, int(round(base * scale)))

    return {
        "ui_scale_percent": normalize_ui_scale(ui_scale_percent),
        "font_size_pt": b,
        "font_scale_percent": int(round(font_factor * 100)),
        "layout_scale": scale,
        "nav_bar_height": px(24, 18),
        "nav_icon_size": px(16, 11),
        "nav_button_width": px(28, 22),
        "table_row_height": px(20, 16),
        "table_icon_size": px(16, 12),
        "thumbnail_size": px(48, 32),
        "thumbnail_row_height": px(54, 36),
        "toolbar_icon": px(16, 14),
        "bottom_bar_height": px(26, 22),
        "center_panel_width": px(40, 36),
        "center_button_min_height": px(24, 18),
        "btn_min_height": px(16, 14),
        "table_cell_pad_v": px(1, 1),
        "table_cell_pad_h": px(5, 4),
        "header_pad_v": px(3, 2),
        "header_pad_h": px(6, 4),
        "header_min_height": px(18, 16),
        "tree_item_pad_v": px(1, 1),
        "tree_item_pad_h": px(4, 3),
        "toolbtn_pad_v": px(2, 1),
        "toolbtn_pad_h": px(6, 4),
        "bottom_btn_pad_v": px(2, 1),
        "bottom_btn_pad_h": px(8, 6),
        "bottom_btn_max_width": px(120, 90),
        "menu_item_pad_v": px(4, 2),
        "menu_item_pad_h": px(14, 10),
        "menu_item_icon_pad": px(16, 12),
        "menubar_pad": px(1, 1),
        "menubar_item_pad_h": px(8, 6),
        "menu_pad": px(3, 2),
        "toolbar_pad_v": px(2, 1),
        "toolbar_pad_h": px(4, 3),
        "input_pad_v": px(4, 2),
        "input_pad_h": px(8, 6),
        "combo_pad_v": px(3, 2),
        "combo_pad_h": px(8, 6),
        "combo_drop_width": px(18, 14),
        "btn_pad_v": px(3, 2),
        "btn_pad_h": px(10, 6),
        "nav_btn_pad": px(2, 1),
        "tab_pad_v": px(4, 2),
        "tab_pad_h": px(10, 8),
        "tab_pad_h_sidebar": px(8, 6),
        "checkbox_size": px(14, 12),
        "checkbox_spacing": px(6, 4),
        "status_pad_v": px(1, 1),
        "status_pad_h": px(6, 4),
        "tooltip_pad_v": px(3, 2),
        "tooltip_pad_h": px(6, 4),
        "group_title_pad_h": px(4, 3),
        "hint_pad_top": px(2, 1),
        "hint_pad_h": px(4, 2),
        "hint_pad_bottom": px(3, 2),
        "inline_pad_h": px(2, 1),
        "chip_pad_h": px(6, 4),
        "chip_pad_h_wide": px(8, 6),
        "drive_edit_pad_h": px(3, 2),
        "batch_cell_pad_v": px(2, 1),
        "batch_cell_pad_h": px(5, 3),
        "center_btn_pad_v": px(1, 1),
        "center_btn_pad_h": px(1, 1),
        "transfers_bar_h": px(12, 10),
        "progress_height": px(16, 12),
        "radius": px(4, 2),
        "radius_lg": px(6, 3),
        "drive_combo_height": px(24, 18),
        "drive_combo_width": px(*_DRIVE_COMBO_BASE_WIDTH),
        "nav_line_pad_v": max(1, px(1, 1)),
        "nav_line_pad_h": max(3, px(4, 3)),
        "nav_filter_pad_right": px(20, 16),
        "bookmark_btn_min_height": px(18, 16),
        "path_edit_height": px(24, 20),
        "path_edit_pad_v": px(2, 1),
        "path_edit_pad_h": px(8, 6),
        "sidebar_tab_min_width": px(84, 68),
        "scrollbar_thickness": px(8, 6),
        "scrollbar_handle_min": px(24, 18),
    }


# ------------------------------------------------------------
# Font sizes for QSS (must track Settings "Font size" so the
# app does not ignore QApplication font until Settings is opened).
# ------------------------------------------------------------
def _fontSizesPt(base_pt, scale_factor=1.0):
    """Scale theme text sizes from the user’s base font size (pt)."""
    b = max(8, min(24, int(base_pt)))
    sf = max(0.75, min(1.25, float(scale_factor)))

    def scaled(delta):
        return max(6, int(round((b + delta) * sf)))

    return {
        "base": max(8, int(round(b * sf))),
        "toolbar": scaled(0),
        "small": scaled(1),
        "tiny": max(7, scaled(0)),
        "micro": max(6, scaled(-1)),
        "center_glyph": scaled(3),
    }


# ------------------------------------------------------------
# Color palettes
# Every theme defines the same keys. "dark" stays Catppuccin
# Mocha so existing settings.json values keep their look.
# ------------------------------------------------------------
PALETTE_KEYS = (
    "base",
    "mantle",
    "crust",
    "surface0",
    "surface1",
    "surface2",
    "overlay0",
    "overlay1",
    "text",
    "subtext0",
    "subtext1",
    "blue",
    "lavender",
    "sapphire",
    "green",
    "red",
    "peach",
    "yellow",
    "mauve",
    "rosewater",
    "panel_bg",
    "active_border",
    "panel_focus_ring",
    "hover",
    "selection",
    "border",
    "button",
    "button_hover",
    "button_press",
    "input_bg",
    "scrollbar_bg",
    "scrollbar_handle",
    "scrollbar_hover",
)

THEMES = {
    "dark": {
        "label": "Dark",
        "colors": {
            "base":        "#1e1e2e",
            "mantle":      "#181825",
            "crust":       "#11111b",
            "surface0":    "#313244",
            "surface1":    "#45475a",
            "surface2":    "#585b70",
            "overlay0":    "#6c7086",
            "overlay1":    "#7f849c",
            "text":        "#cdd6f4",
            "subtext0":    "#a6adc8",
            "subtext1":    "#bac2de",
            "blue":        "#89b4fa",
            "lavender":    "#b4befe",
            "sapphire":    "#74c7ec",
            "green":       "#a6e3a1",
            "red":         "#f38ba8",
            "peach":       "#fab387",
            "yellow":      "#f9e2af",
            "mauve":       "#cba6f7",
            "rosewater":   "#f5e0dc",
            "panel_bg":    "#24243a",
            "active_border": "#7aa2f7",
            "panel_focus_ring": "#ff9f43",
            "hover":       "#2d2d44",
            "selection":   "#394060",
            "border":      "#45475a",
            "button":      "#363654",
            "button_hover": "#45457a",
            "button_press": "#52528a",
            "input_bg":    "#2a2a42",
            "scrollbar_bg": "#1e1e2e",
            "scrollbar_handle": "#45475a",
            "scrollbar_hover":  "#585b70",
        },
    },
    "matte_black": {
        "label": "Matte Black",
        "colors": {
            "base":        "#121212",
            "mantle":      "#0d0d0d",
            "crust":       "#080808",
            "surface0":    "#1c1c1c",
            "surface1":    "#2a2a2a",
            "surface2":    "#3d3d3d",
            "overlay0":    "#6b6b6b",
            "overlay1":    "#8f8f8f",
            "text":        "#bebebe",
            "subtext0":    "#8e8e8e",
            "subtext1":    "#a8a8a8",
            "blue":        "#f0b429",
            "lavender":    "#e6c27a",
            "sapphire":    "#d4a017",
            "green":       "#8fbf7f",
            "red":         "#e06c75",
            "peach":       "#e6a15c",
            "yellow":      "#e6c15c",
            "mauve":       "#c4a4d4",
            "rosewater":   "#e8d5c4",
            "panel_bg":    "#161616",
            "active_border": "#e68e0d",
            "panel_focus_ring": "#f0a020",
            "hover":       "#242424",
            "selection":   "#3a2e1a",
            "border":      "#2e2e2e",
            "button":      "#1f1f1f",
            "button_hover": "#2c2c2c",
            "button_press": "#383838",
            "input_bg":    "#1a1a1a",
            "scrollbar_bg": "#121212",
            "scrollbar_handle": "#3a3a3a",
            "scrollbar_hover":  "#4a4a4a",
        },
    },
    "osaka_jade": {
        "label": "Osaka Jade",
        "colors": {
            "base":        "#111c18",
            "mantle":      "#0c1613",
            "crust":       "#091210",
            "surface0":    "#1a2b24",
            "surface1":    "#243830",
            "surface2":    "#345044",
            "overlay0":    "#6d7f72",
            "overlay1":    "#8a9a86",
            "text":        "#c1c497",
            "subtext0":    "#8f9a78",
            "subtext1":    "#a8b48a",
            "blue":        "#2dd5b7",
            "lavender":    "#8fbfa8",
            "sapphire":    "#5ec8b0",
            "green":       "#549e6a",
            "red":         "#e07a7a",
            "peach":       "#d4a574",
            "yellow":      "#d4c46a",
            "mauve":       "#a8c4a0",
            "rosewater":   "#d4c8a8",
            "panel_bg":    "#14211c",
            "active_border": "#549e6a",
            "panel_focus_ring": "#2dd5b7",
            "hover":       "#1c3028",
            "selection":   "#1e3d32",
            "border":      "#2a4036",
            "button":      "#1a2e26",
            "button_hover": "#244038",
            "button_press": "#2e4e44",
            "input_bg":    "#162822",
            "scrollbar_bg": "#111c18",
            "scrollbar_handle": "#345044",
            "scrollbar_hover":  "#456858",
        },
    },
    "tokyo_night": {
        "label": "Tokyo Night",
        "colors": {
            "base":        "#1a1b26",
            "mantle":      "#16161e",
            "crust":       "#13131a",
            "surface0":    "#24283b",
            "surface1":    "#292e42",
            "surface2":    "#3b4261",
            "overlay0":    "#565f89",
            "overlay1":    "#737aa2",
            "text":        "#c0caf5",
            "subtext0":    "#9aa5ce",
            "subtext1":    "#a9b1d6",
            "blue":        "#7aa2f7",
            "lavender":    "#bb9af7",
            "sapphire":    "#7dcfff",
            "green":       "#9ece6a",
            "red":         "#f7768e",
            "peach":       "#ff9e64",
            "yellow":      "#e0af68",
            "mauve":       "#bb9af7",
            "rosewater":   "#d5d6db",
            "panel_bg":    "#1f2335",
            "active_border": "#7aa2f7",
            "panel_focus_ring": "#ff9e64",
            "hover":       "#292e42",
            "selection":   "#283457",
            "border":      "#3b4261",
            "button":      "#24283b",
            "button_hover": "#2f3549",
            "button_press": "#3b4261",
            "input_bg":    "#1f2335",
            "scrollbar_bg": "#1a1b26",
            "scrollbar_handle": "#3b4261",
            "scrollbar_hover":  "#565f89",
        },
    },
    "gruvbox": {
        "label": "Gruvbox Dark",
        "colors": {
            "base":        "#282828",
            "mantle":      "#1d2021",
            "crust":       "#1d2021",
            "surface0":    "#3c3836",
            "surface1":    "#504945",
            "surface2":    "#665c54",
            "overlay0":    "#7c6f64",
            "overlay1":    "#928374",
            "text":        "#ebdbb2",
            "subtext0":    "#a89984",
            "subtext1":    "#bdae93",
            "blue":        "#83a598",
            "lavender":    "#d3869b",
            "sapphire":    "#8ec07c",
            "green":       "#b8bb26",
            "red":         "#fb4934",
            "peach":       "#fe8019",
            "yellow":      "#fabd2f",
            "mauve":       "#d3869b",
            "rosewater":   "#ebdbb2",
            "panel_bg":    "#32302f",
            "active_border": "#fabd2f",
            "panel_focus_ring": "#fe8019",
            "hover":       "#3c3836",
            "selection":   "#504945",
            "border":      "#504945",
            "button":      "#3c3836",
            "button_hover": "#504945",
            "button_press": "#665c54",
            "input_bg":    "#32302f",
            "scrollbar_bg": "#282828",
            "scrollbar_handle": "#665c54",
            "scrollbar_hover":  "#7c6f64",
        },
    },
    "nord": {
        "label": "Nord",
        "colors": {
            "base":        "#2e3440",
            "mantle":      "#272c36",
            "crust":       "#242933",
            "surface0":    "#3b4252",
            "surface1":    "#434c5e",
            "surface2":    "#4c566a",
            "overlay0":    "#616e88",
            "overlay1":    "#8b97ad",
            "text":        "#d8dee9",
            "subtext0":    "#9aa6b8",
            "subtext1":    "#c5cedb",
            "blue":        "#81a1c1",
            "lavender":    "#b48ead",
            "sapphire":    "#88c0d0",
            "green":       "#a3be8c",
            "red":         "#bf616a",
            "peach":       "#d08770",
            "yellow":      "#ebcb8b",
            "mauve":       "#b48ead",
            "rosewater":   "#e5e9f0",
            "panel_bg":    "#323845",
            "active_border": "#88c0d0",
            "panel_focus_ring": "#ebcb8b",
            "hover":       "#3b4252",
            "selection":   "#434c5e",
            "border":      "#4c566a",
            "button":      "#3b4252",
            "button_hover": "#434c5e",
            "button_press": "#4c566a",
            "input_bg":    "#353b49",
            "scrollbar_bg": "#2e3440",
            "scrollbar_handle": "#4c566a",
            "scrollbar_hover":  "#616e88",
        },
    },
    "everforest": {
        "label": "Everforest",
        "colors": {
            "base":        "#2d353b",
            "mantle":      "#232a2e",
            "crust":       "#1e2528",
            "surface0":    "#343f44",
            "surface1":    "#3d484d",
            "surface2":    "#475258",
            "overlay0":    "#7a8478",
            "overlay1":    "#859289",
            "text":        "#d3c6aa",
            "subtext0":    "#859289",
            "subtext1":    "#9da9a0",
            "blue":        "#7fbbb3",
            "lavender":    "#d699b6",
            "sapphire":    "#83c092",
            "green":       "#a7c080",
            "red":         "#e67e80",
            "peach":       "#e69875",
            "yellow":      "#dbbc7f",
            "mauve":       "#d699b6",
            "rosewater":   "#d3c6aa",
            "panel_bg":    "#323c41",
            "active_border": "#a7c080",
            "panel_focus_ring": "#dbbc7f",
            "hover":       "#3d484d",
            "selection":   "#475258",
            "border":      "#475258",
            "button":      "#3d484d",
            "button_hover": "#475258",
            "button_press": "#56635f",
            "input_bg":    "#343f44",
            "scrollbar_bg": "#2d353b",
            "scrollbar_handle": "#475258",
            "scrollbar_hover":  "#56635f",
        },
    },
}

# Light and system are not QSS palettes; they use Qt styles.
_STYLE_THEMES = (
    ("light", "Light"),
    ("system", "Same as system"),
)


# ------------------------------------------------------------
# Function: getThemeChoices
# Purpose: (id, label) pairs for Settings → Theme.
#          Dark palettes first, then Light and Same as system.
# ------------------------------------------------------------
def getThemeChoices():
    choices = [(theme_id, spec["label"]) for theme_id, spec in THEMES.items()]
    choices.extend(_STYLE_THEMES)
    return choices


# ------------------------------------------------------------
# Function: getPalette
# Purpose: Color dict for a theme id. Unknown ids use Dark.
# ------------------------------------------------------------
def getPalette(theme_mode):
    key = (theme_mode or "dark").strip().lower()
    spec = THEMES.get(key)
    if spec is None:
        spec = THEMES["dark"]
    return spec["colors"]


# ------------------------------------------------------------
# Function: themeColor
# Purpose: One hex color from the palette last applied to the
#          running app. Light and system themes have no palette,
#          so callers pass a fallback.
# ------------------------------------------------------------
def themeColor(key, fallback):
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
    except Exception:
        return fallback
    colors = getattr(app, "_theme_colors", None) if app is not None else None
    if isinstance(colors, dict) and colors.get(key):
        return colors[key]
    return fallback


# ------------------------------------------------------------
# Function: _rgba
# Purpose: CSS rgba() from a #rrggbb color and a 0–1 alpha,
#          so tints follow the active palette.
# ------------------------------------------------------------
def _rgba(hex_color, alpha):
    h = str(hex_color).lstrip("#")
    red = int(h[0:2], 16)
    green = int(h[2:4], 16)
    blue = int(h[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


# ------------------------------------------------------------
# Function: getThemeStylesheet
# Purpose: Returns the complete QSS stylesheet for one dark
#          palette, scaled by the current font size and density.
# ------------------------------------------------------------
def getThemeStylesheet(palette, font_size_pt=10, metrics=None):
    c = palette
    if metrics is None:
        metrics = getUiMetrics(font_size_pt, DEFAULT_UI_SCALE_PERCENT)
    sf = metrics["ui_scale_percent"] / 100.0
    fs = _fontSizesPt(font_size_pt, sf)
    m = metrics
    red_12 = _rgba(c["red"], 0.12)
    red_14 = _rgba(c["red"], 0.14)
    red_28 = _rgba(c["red"], 0.28)
    red_40 = _rgba(c["red"], 0.40)
    accent_14 = _rgba(c["active_border"], 0.14)
    accent_18 = _rgba(c["active_border"], 0.18)
    accent_28 = _rgba(c["active_border"], 0.28)
    accent_40 = _rgba(c["active_border"], 0.40)
    return f"""

    /* ====================================================== */
    /* Global Widget Defaults                                  */
    /* ====================================================== */
    QWidget {{
        background-color: {c['base']};
        color: {c['text']};
        font-family: "Segoe UI", "Roboto", sans-serif;
        font-size: {fs['base']}pt;
        font-weight: normal;
        border: none;
    }}

    /* ====================================================== */
    /* Main Window                                             */
    /* ====================================================== */
    QMainWindow {{
        background-color: {c['crust']};
    }}

    /* ====================================================== */
    /* Menu Bar                                                */
    /* ====================================================== */
    QMenuBar {{
        background-color: {c['mantle']};
        color: {c['text']};
        border-bottom: 1px solid {c['border']};
        padding: {m['menubar_pad']}px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: {m['menu_item_pad_v']}px {m['menubar_item_pad_h']}px;
        border-radius: {m['radius']}px;
    }}
    QMenuBar::item:selected {{
        background-color: {c['surface0']};
    }}

    /* ====================================================== */
    /* Menus (dropdowns)                                       */
    /* ====================================================== */
    QMenu {{
        background-color: {c['mantle']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        padding: {m['menu_pad']}px;
    }}
    QMenu::item {{
        padding: {m['menu_item_pad_v']}px {m['menu_item_pad_h']}px {m['menu_item_pad_v']}px {m['menu_item_icon_pad']}px;
        border-radius: {m['radius']}px;
    }}
    QMenu::item:selected {{
        background-color: {c['selection']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: {m['menu_pad']}px {m['menubar_item_pad_h']}px;
    }}
    QMenu::icon {{
        padding-left: {m['chip_pad_h']}px;
    }}

    /* ====================================================== */
    /* Toolbar                                                 */
    /* ====================================================== */
    QToolBar {{
        background-color: {c['mantle']};
        border-bottom: 1px solid {c['border']};
        padding: {m['toolbar_pad_v']}px {m['toolbar_pad_h']}px;
        spacing: {m['toolbar_pad_h']}px;
    }}
    QToolBar::separator {{
        width: 1px;
        background: {c['border']};
        margin: {m['menu_pad']}px {m['toolbar_pad_h']}px;
    }}
    QToolButton {{
        background-color: transparent;
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: {m['radius']}px;
        padding: {m['toolbtn_pad_v']}px {m['toolbtn_pad_h']}px;
        font-size: {fs['toolbar']}pt;
    }}
    QToolButton:hover {{
        background-color: {c['hover']};
        border: 1px solid {c['border']};
    }}
    QToolButton:pressed {{
        background-color: {c['surface0']};
    }}
    QToolButton:checked {{
        background-color: {c['selection']};
        border: 1px solid {c['active_border']};
    }}

    /* ====================================================== */
    /* Push Buttons                                            */
    /* ====================================================== */
    QPushButton {{
        background-color: {c['button']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        padding: {m['btn_pad_v']}px {m['btn_pad_h']}px;
        min-height: {m['btn_min_height']}px;
    }}
    QPushButton:hover {{
        background-color: {c['button_hover']};
        border: 1px solid {c['active_border']};
    }}
    QPushButton:pressed {{
        background-color: {c['button_press']};
    }}
    QPushButton:disabled {{
        background-color: {c['surface0']};
        color: {c['overlay0']};
        border: 1px solid {c['surface0']};
    }}
    QPushButton#accentButton {{
        background-color: {c['active_border']};
        color: {c['crust']};
        font-weight: bold;
    }}
    QPushButton#accentButton:hover {{
        background-color: {c['blue']};
    }}
    QPushButton#navButton {{
        padding: {m['nav_btn_pad']}px;
        min-width: {m['nav_button_width']}px;
    }}
    QPushButton#navButton:focus {{
        border: 1px solid {c['border']};
        background-color: {c['button']};
    }}
    QPushButton#navButton:default {{
        border: 1px solid {c['border']};
        background-color: {c['button']};
    }}

    /* ====================================================== */
    /* Line Edits / Inputs                                     */
    /* ====================================================== */
    QLineEdit {{
        background-color: {c['input_bg']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        padding: {m['input_pad_v']}px {m['input_pad_h']}px;
        selection-background-color: {c['selection']};
    }}
    QLineEdit:focus {{
        border: 1px solid {c['active_border']};
    }}
    QLineEdit:read-only {{
        background-color: {c['surface0']};
    }}
    QLineEdit#panelPathEdit {{
        min-height: {m['path_edit_height']}px;
        padding: {m['path_edit_pad_v']}px {m['path_edit_pad_h']}px;
    }}
    QLineEdit#panelFilterEdit {{
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
    }}
    QLineEdit#panelFilterEdit[filterActive="true"] {{
        border: 2px solid {c['red']};
        background-color: {red_14};
        color: {c['text']};
    }}
    QPushButton#filterClearButton {{
        color: {c['red']};
        background-color: {red_12};
        border: 2px solid {c['red']};
        border-radius: {m['radius']}px;
        font-weight: bold;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
    }}
    QPushButton#filterClearButton:hover {{
        background-color: {red_28};
        border-color: {c['red']};
    }}
    QPushButton#filterClearButton:pressed {{
        background-color: {red_40};
    }}
    QPushButton#filterSettingsButton {{
        color: {c['text']};
        background-color: {c['button']};
        border: 2px solid {c['border']};
        border-radius: {m['radius']}px;
        font-weight: bold;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
        min-width: 0;
    }}
    QPushButton#filterSettingsButton:hover {{
        background-color: {c['button_hover']};
        border-color: {c['active_border']};
    }}
    QPushButton#filterSettingsButton:pressed {{
        background-color: {c['button_press']};
        border-color: {c['active_border']};
    }}
    QPushButton#filterSettingsButton[filterActive="true"] {{
        border-color: {c['active_border']};
        background-color: {accent_18};
    }}
    QPushButton#thumbnailButton {{
        color: {c['text']};
        background-color: {c['button']};
        border: 2px solid {c['border']};
        border-radius: {m['radius']}px;
        font-weight: bold;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
        min-width: 0;
    }}
    QPushButton#thumbnailButton:hover {{
        background-color: {c['button_hover']};
        border-color: {c['active_border']};
    }}
    QPushButton#thumbnailButton:checked {{
        background-color: {c['selection']};
        border: 2px solid {c['active_border']};
    }}
    QPushButton#filterRefreshButton {{
        color: {c['text']};
        background-color: {accent_14};
        border: 2px solid {c['active_border']};
        border-radius: {m['radius']}px;
        font-weight: bold;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
    }}
    QPushButton#filterRefreshButton:hover {{
        background-color: {accent_28};
        border-color: {c['blue']};
    }}
    QPushButton#filterRefreshButton:pressed {{
        background-color: {accent_40};
    }}
    QWidget#panelFilterBanner {{
        background-color: {red_12};
        border: 2px solid {c['red']};
        border-radius: {m['radius']}px;
    }}
    QLabel#panelFilterBannerText {{
        color: {c['red']};
        font-weight: bold;
        font-size: {fs['small']}pt;
        background: transparent;
    }}
    QLineEdit#panelRenameEdit {{
        background-color: {c['selection']};
        color: {c['text']};
        border: 1px solid {c['active_border']};
        border-radius: {m['radius']}px;
        padding: {m['table_cell_pad_v']}px {m['inline_pad_h']}px;
        margin: 0;
        min-height: 0;
    }}

    /* ====================================================== */
    /* Table View (File Listing)                               */
    /* ====================================================== */
    QTableView {{
        background-color: {c['panel_bg']};
        alternate-background-color: {c['base']};
        color: {c['text']};
        gridline-color: {c['surface0']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        selection-background-color: {c['selection']};
        selection-color: {c['text']};
        outline: none;
    }}
    QTableView::item {{
        padding: {m['table_cell_pad_v']}px {m['table_cell_pad_h']}px;
        border: none;
    }}
    QTableView::item:hover {{
        background-color: {c['hover']};
    }}
    QTableView::item:selected {{
        background-color: {c['selection']};
        color: {c['text']};
    }}
    QTableView::item:focus {{
        outline: none;
        border: none;
    }}

    /* ====================================================== */
    /* Header View (Table Column Headers)                      */
    /* ====================================================== */
    QHeaderView {{
        background-color: {c['mantle']};
        border: none;
    }}
    QHeaderView::section {{
        background-color: {c['mantle']};
        color: {c['subtext1']};
        border: none;
        border-right: 1px solid {c['surface0']};
        border-bottom: 1px solid {c['border']};
        padding: {m['header_pad_v']}px {m['header_pad_h']}px;
        font-weight: 600;
        font-size: {fs['small']}pt;
        min-height: {m['header_min_height']}px;
    }}
    QHeaderView::section:hover {{
        background-color: {c['surface0']};
        color: {c['text']};
    }}
    QHeaderView::section:pressed {{
        background-color: {c['surface1']};
    }}

    /* ====================================================== */
    /* Scroll Bars                                             */
    /* ====================================================== */
    QScrollBar:vertical {{
        background: {c['scrollbar_bg']};
        width: {m['scrollbar_thickness']}px;
        margin: 0;
        border-radius: {m['radius']}px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['scrollbar_handle']};
        min-height: {m['scrollbar_handle_min']}px;
        border-radius: {m['radius']}px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c['scrollbar_hover']};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: {c['scrollbar_bg']};
        height: {m['scrollbar_thickness']}px;
        margin: 0;
        border-radius: {m['radius']}px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['scrollbar_handle']};
        min-width: {m['scrollbar_handle_min']}px;
        border-radius: {m['radius']}px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {c['scrollbar_hover']};
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* ====================================================== */
    /* Splitter                                                */
    /* ====================================================== */
    QSplitter::handle {{
        background-color: {c['border']};
        width: {m['menu_pad']}px;
    }}
    QSplitter::handle:hover {{
        background-color: {c['active_border']};
        width: {m['menu_pad']}px;
    }}

    /* ====================================================== */
    /* Status Bar                                              */
    /* ====================================================== */
    QStatusBar {{
        background-color: {c['mantle']};
        color: {c['subtext0']};
        border-top: 1px solid {c['border']};
        padding: {m['status_pad_v']}px {m['status_pad_h']}px;
    }}
    QStatusBar::item {{
        border: none;
    }}

    /* ====================================================== */
    /* Tooltips                                                */
    /* ====================================================== */
    QToolTip {{
        background-color: {c['surface0']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius']}px;
        padding: {m['tooltip_pad_v']}px {m['tooltip_pad_h']}px;
    }}

    /* ====================================================== */
    /* Progress Bar                                            */
    /* ====================================================== */
    QProgressBar {{
        background-color: {c['surface0']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        text-align: center;
        color: {c['text']};
        height: {m['progress_height']}px;
    }}
    QProgressBar::chunk {{
        background-color: {c['active_border']};
        border-radius: {m['radius']}px;
    }}

    /* ====================================================== */
    /* Dialog                                                  */
    /* ====================================================== */
    QDialog {{
        background-color: {c['base']};
    }}

    /* ====================================================== */
    /* Message Box                                             */
    /* ====================================================== */
    QMessageBox {{
        background-color: {c['base']};
    }}
    QMessageBox QLabel {{
        color: {c['text']};
    }}

    /* ====================================================== */
    /* Input Dialog                                            */
    /* ====================================================== */
    QInputDialog {{
        background-color: {c['base']};
    }}

    /* ====================================================== */
    /* Labels                                                  */
    /* ====================================================== */
    QLabel {{
        color: {c['text']};
        background: transparent;
    }}
    QPlainTextEdit#viewerText {{
        background-color: {c['base']};
        color: {c['text']};
        selection-background-color: {c['active_border']};
        selection-color: {c['crust']};
        font-family: Consolas, "Cascadia Mono", monospace;
    }}
    QLabel#panelLabel {{
        color: {c['subtext0']};
        font-size: {fs['small']}pt;
    }}
    QLabel#panelLabel[filterWarning="true"] {{
        color: {c['peach']};
        font-weight: bold;
    }}
    QLabel#statusLabel {{
        color: {c['subtext0']};
    }}

    /* ====================================================== */
    /* Group Box                                               */
    /* ====================================================== */
    QGroupBox {{
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        margin-top: {m['menubar_item_pad_h']}px;
        padding-top: {m['btn_min_height']}px;
        color: {c['text']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 {m['group_title_pad_h']}px;
        color: {c['subtext1']};
    }}

    /* ====================================================== */
    /* Combo Box                                               */
    /* ====================================================== */
    QComboBox {{
        background-color: {c['input_bg']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        padding: {m['combo_pad_v']}px {m['combo_pad_h']}px;
    }}
    QComboBox:hover {{
        border: 1px solid {c['active_border']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: {m['combo_drop_width']}px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['mantle']};
        color: {c['text']};
        border: 1px solid {c['border']};
        selection-background-color: {c['selection']};
        border-radius: {m['radius']}px;
    }}

    /* ====================================================== */
    /* Check Box                                               */
    /* ====================================================== */
    QCheckBox {{
        color: {c['text']};
        spacing: {m['checkbox_spacing']}px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: {m['checkbox_size']}px;
        height: {m['checkbox_size']}px;
        border: 2px solid {c['border']};
        border-radius: {m['radius']}px;
        background-color: {c['input_bg']};
    }}
    QCheckBox::indicator:hover {{
        border-color: {c['active_border']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c['active_border']};
        border-color: {c['active_border']};
    }}

    /* ====================================================== */
    /* Tab Widget (for possible future use)                    */
    /* ====================================================== */
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        background-color: {c['base']};
    }}
    QTabBar::tab {{
        background-color: {c['mantle']};
        color: {c['subtext0']};
        border: 1px solid {c['border']};
        border-bottom: none;
        padding: {m['tab_pad_v']}px {m['tab_pad_h']}px;
        min-width: {m['sidebar_tab_min_width']}px;
        border-top-left-radius: {m['radius_lg']}px;
        border-top-right-radius: {m['radius_lg']}px;
        font-size: {fs['small']}pt;
    }}
    QTabWidget#sidebarTabs::pane {{
        border: 1px solid {c['border']};
        border-radius: 0 0 {m['radius_lg']}px {m['radius_lg']}px;
        top: -1px;
    }}
    QTabWidget#sidebarTabs QTabBar::tab {{
        min-width: {m['sidebar_tab_min_width']}px;
        padding: {m['tab_pad_v']}px {m['tab_pad_h_sidebar']}px;
    }}
    QTabBar::tab:selected {{
        background-color: {c['base']};
        color: {c['text']};
        border-bottom: 2px solid {c['active_border']};
    }}
    QTabBar::tab:hover {{
        background-color: {c['surface0']};
        color: {c['text']};
    }}
    QWidget#panelTabRow {{
        background-color: {c['mantle']};
    }}
    QToolButton#panelTabAddButton {{
        background-color: {c['mantle']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-bottom: none;
        border-top-left-radius: {m['radius_lg']}px;
        border-top-right-radius: {m['radius_lg']}px;
        padding: {m['tab_pad_v']}px {m['tab_pad_h']}px;
        font-size: {fs['small']}pt;
        font-weight: bold;
        min-width: 0px;
    }}
    QToolButton#panelTabAddButton:hover {{
        background-color: {c['surface0']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-bottom: none;
    }}
    QToolButton#panelTabAddButton:pressed {{
        background-color: {c['base']};
        color: {c['text']};
    }}
    QTabBar#panelTabBar QToolButton#panelTabCloseButton {{
        background-color: transparent;
        color: {c['subtext0']};
        border: none;
        border-radius: {m['radius']}px;
        padding: 0px;
        margin: 0px;
        font-size: {fs['small']}pt;
        font-weight: bold;
        min-width: 16px;
        max-width: 16px;
        min-height: 16px;
        max-height: 16px;
    }}
    QTabBar#panelTabBar QToolButton#panelTabCloseButton:hover {{
        background-color: {c['hover']};
        color: {c['text']};
        border: none;
    }}

    /* ====================================================== */
    /* Custom Panel Frame (applied via objectName)             */
    /* ====================================================== */
    QWidget#filePanel {{
        background-color: {c['panel_bg']};
        border: 1px solid {c['overlay0']};
        border-radius: {m['radius_lg']}px;
    }}
    QWidget#filePanelActive {{
        background-color: {c['panel_bg']};
        border: 1px solid {c['overlay0']};
        border-radius: {m['radius_lg']}px;
    }}

    /* Active panel: orange ring on address bar + file table (path + panelFileTable) */
    QWidget#filePanel QLineEdit#panelPathEdit {{
        border: 1px solid {c['border']};
    }}
    QWidget#filePanel QLineEdit#panelPathEdit:focus {{
        border: 1px solid {c['active_border']};
    }}
    QWidget#filePanelActive QLineEdit#panelPathEdit {{
        border: 1px solid {c['panel_focus_ring']};
    }}
    QWidget#filePanelActive QLineEdit#panelPathEdit:focus {{
        border: 1px solid {c['panel_focus_ring']};
    }}

    QWidget#filePanel QTableView#panelFileTable {{
        border: none;
        border-radius: {m['radius_lg']}px;
    }}
    QWidget#filePanelActive QTableView#panelFileTable {{
        border: 1px solid {c['panel_focus_ring']};
        border-radius: {m['radius_lg']}px;
    }}

    /* ====================================================== */
    /* Bottom Button Bar                                       */
    /* ====================================================== */
    QFrame#transfersBar {{
        background-color: {c['surface0']};
        border-top: 1px solid {c['border']};
    }}
    QFrame#transfersBar QLabel#transfersSummary {{
        color: {c['text']};
        font-size: {fs['small']}pt;
    }}
    QFrame#transfersBar QProgressBar#transfersProgress {{
        max-height: {m['transfers_bar_h']}px;
        min-height: {m['transfers_bar_h']}px;
    }}
    QFrame#transfersBar QPushButton#transfersCancel {{
        background-color: transparent;
        border: 1px solid {c['border']};
        border-radius: {m['radius']}px;
        padding: {m['status_pad_v']}px {m['btn_pad_h']}px;
        font-size: {fs['small']}pt;
        color: {c['subtext1']};
    }}
    QFrame#transfersBar QPushButton#transfersCancel:hover {{
        background-color: {c['button_hover']};
        color: {c['text']};
    }}

    QFrame#bottomBar {{
        background-color: {c['mantle']};
        border-top: 1px solid {c['border']};
    }}
    QFrame#bottomBar QPushButton {{
        background-color: transparent;
        border: 1px solid {c['border']};
        border-radius: {m['radius']}px;
        padding: {m['bottom_btn_pad_v']}px {m['bottom_btn_pad_h']}px;
        font-weight: bold;
        font-size: {fs['small']}pt;
        color: {c['subtext1']};
        min-width: 0;
        max-width: {m['bottom_btn_max_width']}px;
    }}
    QFrame#bottomBar QPushButton:hover {{
        background-color: {c['button_hover']};
        color: {c['text']};
        border-color: {c['active_border']};
    }}

    /* ====================================================== */
    /* Center Panel (directional copy/move buttons)            */
    /* ====================================================== */
    QFrame#centerPanel {{
        background-color: {c['mantle']};
        border: none;
        min-width: {m['center_panel_width']}px;
        max-width: {m['center_panel_width']}px;
    }}
    QFrame#centerPanel QPushButton {{
        background-color: {c['button']};
        color: {c['subtext1']};
        border: 1px solid {c['border']};
        border-radius: {m['radius']}px;
        padding: {m['center_btn_pad_v']}px {m['center_btn_pad_h']}px;
        font-size: {fs['center_glyph']}pt;
        font-weight: bold;
        min-height: {m['center_button_min_height']}px;
    }}
    QFrame#centerPanel QPushButton:hover {{
        background-color: {c['button_hover']};
        color: {c['text']};
        border-color: {c['active_border']};
    }}
    QFrame#centerPanel QPushButton:pressed {{
        background-color: {c['button_press']};
    }}
    QFrame#centerPanel QToolButton#centerSpecialButton {{
        background-color: {c['button']};
        color: {c['subtext1']};
        border: 1px solid {c['border']};
        border-radius: {m['radius']}px;
        padding: {m['center_btn_pad_v']}px {m['center_btn_pad_h']}px;
        font-size: {fs['center_glyph']}pt;
        font-weight: bold;
        min-height: {m['center_button_min_height']}px;
    }}
    QFrame#centerPanel QToolButton#centerSpecialButton:hover {{
        background-color: {c['button_hover']};
        color: {c['text']};
        border-color: {c['active_border']};
    }}
    QFrame#centerPanel QToolButton#centerSpecialButton:pressed {{
        background-color: {c['button_press']};
    }}
    QFrame#centerPanel QToolButton#centerSpecialButton::menu-indicator {{
        image: none;
        width: 0;
    }}
    QFrame#centerPanel QLabel {{
        color: {c['overlay0']};
        font-size: {fs['tiny']}pt;
    }}

    /* ====================================================== */
    /* Bookmarks panel tree                                     */
    /* ====================================================== */
    QTreeWidget {{
        background-color: {c['panel_bg']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        outline: none;
    }}
    QTreeWidget::item {{
        padding: {m['tree_item_pad_v']}px {m['tree_item_pad_h']}px;
    }}
    QTreeWidget::item:hover {{
        background-color: {c['hover']};
    }}
    QTreeWidget::item:selected {{
        background-color: {c['selection']};
        color: {c['text']};
    }}
    /* Do not style ::branch so the default expand/collapse arrows remain visible. */

    QPushButton#bookmarksToolButton {{
        padding: {m['status_pad_v']}px {m['chip_pad_h']}px;
        font-size: {fs['small']}pt;
        min-height: {m['bookmark_btn_min_height']}px;
        min-width: 0;
    }}

    QLabel#bookmarksDropHint {{
        color: {c['blue']};
        font-size: {fs['small']}pt;
        padding: {m['hint_pad_top']}px {m['hint_pad_h']}px {m['hint_pad_bottom']}px {m['hint_pad_h']}px;
    }}

    /* ====================================================== */
    /* Drive selector combo (file panel nav bar)                */
    /* ====================================================== */
    QComboBox#driveCombo {{
        min-width: {m['drive_combo_width']}px;
        max-width: {m['drive_combo_width']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
        padding: 0;
        font-weight: bold;
        font-size: {fs['small']}pt;
        border-top-right-radius: 0;
        border-bottom-right-radius: 0;
    }}
    QComboBox#driveCombo::drop-down {{
        width: 0;
        border: none;
    }}
    QComboBox#driveCombo QAbstractItemView {{
        text-align: center;
    }}
    QComboBox#driveCombo QLineEdit {{
        background: transparent;
        border: none;
        margin: 0;
        padding: 0 {m['drive_edit_pad_h']}px;
        min-height: 0;
        max-height: {m['nav_bar_height']}px;
        text-align: center;
    }}
    QComboBox#driveCombo QLineEdit:focus {{
        border: none;
        outline: none;
    }}
    QLabel#driveArrow {{
        color: {c['text']};
        font-size: {fs['micro']}pt;
        padding: 0;
        margin: 0;
        background-color: {c['surface0']};
        border: 1px solid {c['border']};
        border-left: none;
        border-top-right-radius: {m['radius']}px;
        border-bottom-right-radius: {m['radius']}px;
        qproperty-alignment: AlignCenter;
    }}

    /* ====================================================== */
    /* Batch Rename Preview Table                              */
    /* ====================================================== */
    QTableWidget#batchPreview {{
        background-color: {c['panel_bg']};
        alternate-background-color: {c['base']};
        color: {c['text']};
        gridline-color: {c['surface0']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        selection-background-color: {c['selection']};
    }}
    QTableWidget#batchPreview::item {{
        padding: {m['batch_cell_pad_v']}px {m['batch_cell_pad_h']}px;
    }}
    QLabel#batchChanged {{
        color: {c['green']};
    }}
    QLabel#batchUnchanged {{
        color: {c['overlay0']};
    }}

    /* ====================================================== */
    /* Library Browser Panel                                    */
    /* ====================================================== */
    QPushButton#libraryToolButton {{
        padding: {m['status_pad_v']}px {m['chip_pad_h_wide']}px;
        font-size: {fs['small']}pt;
        min-height: {m['bookmark_btn_min_height']}px;
    }}

    QListWidget {{
        background-color: {c['panel_bg']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {m['radius_lg']}px;
        outline: none;
    }}
    QListWidget::item {{
        padding: {m['tree_item_pad_v']}px {m['tree_item_pad_h']}px;
    }}
    QListWidget::item:hover {{
        background-color: {c['hover']};
    }}
    QListWidget::item:selected {{
        background-color: {c['selection']};
        color: {c['text']};
    }}
    """


def applyTheme(app, theme_mode, font_size_pt=None, ui_scale_percent=None):
    """
    Apply a dark palette (custom QSS), light (Fusion), or the system style.
    Any theme id other than "light" and "system" uses that palette, or Dark
    when the id is unknown. The active palette is stored on app._theme_colors.
    Expects app._system_style_name and app._system_palette set at startup (see main.py).

    font_size_pt: optional base font size from Settings. When None, uses app.font()
    point size (falls back to 10). Always updates QApplication font so light/system
    themes match Settings on startup.

    ui_scale_percent: density preset percent — spacing and control sizes (see getUiMetrics).
    Layout metrics also scale with font_size_pt (10 pt = 100%).
    """
    from PyQt5.QtWidgets import QStyleFactory

    if font_size_pt is None:
        sz = app.font().pointSize()
        font_size_pt = sz if sz > 0 else 10
    else:
        font_size_pt = int(font_size_pt)

    if ui_scale_percent is None:
        ui_scale_percent = getattr(app, "_ui_scale_percent", DEFAULT_UI_SCALE_PERCENT)
    ui_scale_percent = normalize_ui_scale(ui_scale_percent)
    app._ui_scale_percent = ui_scale_percent
    metrics = getUiMetrics(font_size_pt, ui_scale_percent)
    app._ui_metrics = metrics

    app_font = QFont("Segoe UI", font_size_pt)
    app_font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(app_font)

    mode = (theme_mode or "dark").strip().lower()

    if mode not in ("light", "system"):
        palette = getPalette(mode)
        app._theme_colors = palette
        app.setStyleSheet(
            getThemeStylesheet(palette, font_size_pt=font_size_pt, metrics=metrics)
        )
        return

    app._theme_colors = None
    app.setStyleSheet("")

    if mode == "light":
        fusion_style = QStyleFactory.create("Fusion")
        if fusion_style is not None:
            app.setStyle(fusion_style)
            app.setPalette(fusion_style.standardPalette())
        return

    system_style_name = getattr(app, "_system_style_name", "")
    if system_style_name:
        system_style = QStyleFactory.create(system_style_name)
        if system_style is not None:
            app.setStyle(system_style)
    system_palette = getattr(app, "_system_palette", None)
    if system_palette is not None:
        app.setPalette(system_palette)
