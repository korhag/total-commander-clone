"""
Total Commander Clone - Dark Theme Stylesheet
Provides a modern, flat dark theme using Qt Style Sheets (QSS).
Color palette inspired by Catppuccin Mocha.
"""

from PyQt5.QtGui import QFont


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
        "nav_bar_height": px(26, 18),
        "nav_icon_size": px(16, 11),
        "nav_button_width": px(30, 22),
        "table_row_height": px(22, 16),
        "table_icon_size": px(16, 12),
        "toolbar_icon": px(18, 14),
        "bottom_bar_height": px(30, 22),
        "center_panel_width": px(44, 36),
        "center_button_min_height": px(28, 18),
        "btn_min_height": px(18, 14),
        "table_cell_pad_v": px(2, 1),
        "table_cell_pad_h": px(6, 4),
        "header_pad_v": px(4, 2),
        "header_pad_h": px(8, 6),
        "tree_item_pad_v": px(2, 1),
        "tree_item_pad_h": px(4, 3),
        "toolbtn_pad_v": px(3, 2),
        "toolbtn_pad_h": px(8, 6),
        "bottom_btn_pad_v": px(3, 2),
        "bottom_btn_pad_h": px(10, 8),
        "menu_item_pad_v": px(6, 4),
        "menu_item_pad_h": px(24, 18),
        "drive_combo_height": px(26, 18),
        "drive_combo_width": px(58, 50),
        "nav_line_pad_v": max(1, px(2, 1)),
        "nav_line_pad_h": max(4, px(6, 4)),
        "nav_filter_pad_right": px(24, 20),
        "bookmark_btn_min_height": px(20, 16),
        "path_edit_height": px(28, 20),
        "path_edit_pad_v": px(3, 2),
        "path_edit_pad_h": px(10, 6),
        "sidebar_tab_min_width": px(92, 72),
        "scrollbar_thickness": px(10, 8),
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
        "toolbar": scaled(2),
        "small": scaled(1),
        "tiny": max(7, scaled(0)),
        "micro": max(6, scaled(-1)),
        "center_glyph": scaled(6),
    }


# ------------------------------------------------------------
# Color Constants
# ------------------------------------------------------------
COLORS = {
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
}


# ------------------------------------------------------------
# Function: getDarkThemeStylesheet
# Purpose: Returns the complete QSS stylesheet string for the
#          dark theme applied to the entire application.
# ------------------------------------------------------------
def getDarkThemeStylesheet(base_path=None, font_size_pt=10, metrics=None):
    c = COLORS
    if metrics is None:
        metrics = getUiMetrics(font_size_pt, DEFAULT_UI_SCALE_PERCENT)
    sf = metrics["ui_scale_percent"] / 100.0
    fs = _fontSizesPt(font_size_pt, sf)
    m = metrics
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
        padding: 2px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: {m['menu_item_pad_v']}px 12px;
        border-radius: 4px;
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
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: {m['menu_item_pad_v']}px {m['menu_item_pad_h']}px {m['menu_item_pad_v']}px 20px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background-color: {c['selection']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 4px 10px;
    }}
    QMenu::icon {{
        padding-left: 6px;
    }}

    /* ====================================================== */
    /* Toolbar                                                 */
    /* ====================================================== */
    QToolBar {{
        background-color: {c['mantle']};
        border-bottom: 1px solid {c['border']};
        padding: 3px 6px;
        spacing: 4px;
    }}
    QToolBar::separator {{
        width: 1px;
        background: {c['border']};
        margin: 4px 6px;
    }}
    QToolButton {{
        background-color: transparent;
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: 5px;
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
        border-radius: 6px;
        padding: 4px 12px;
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
        padding: 4px;
        min-width: 30px;
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
        border-radius: 6px;
        padding: 6px 10px;
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
        background-color: rgba(243, 139, 168, 0.14);
        color: {c['text']};
    }}
    QPushButton#filterClearButton {{
        color: {c['red']};
        background-color: rgba(243, 139, 168, 0.12);
        border: 2px solid {c['red']};
        border-radius: 4px;
        font-weight: bold;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
    }}
    QPushButton#filterClearButton:hover {{
        background-color: rgba(243, 139, 168, 0.28);
        border-color: {c['red']};
    }}
    QPushButton#filterClearButton:pressed {{
        background-color: rgba(243, 139, 168, 0.4);
    }}
    QPushButton#filterSettingsButton {{
        color: {c['text']};
        background-color: {c['button']};
        border: 2px solid {c['border']};
        border-radius: 4px;
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
        background-color: rgba(137, 180, 250, 0.18);
    }}
    QPushButton#filterRefreshButton {{
        color: {c['text']};
        background-color: rgba(137, 180, 250, 0.14);
        border: 2px solid {c['active_border']};
        border-radius: 4px;
        font-weight: bold;
        padding: {m['nav_line_pad_v']}px {m['nav_line_pad_h']}px;
        min-height: {m['nav_bar_height']}px;
        max-height: {m['nav_bar_height']}px;
    }}
    QPushButton#filterRefreshButton:hover {{
        background-color: rgba(137, 180, 250, 0.28);
        border-color: {c['blue']};
    }}
    QPushButton#filterRefreshButton:pressed {{
        background-color: rgba(137, 180, 250, 0.4);
    }}
    QWidget#panelFilterBanner {{
        background-color: rgba(243, 139, 168, 0.12);
        border: 2px solid {c['red']};
        border-radius: 5px;
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
        border-radius: 3px;
        padding: {m['table_cell_pad_v']}px 2px;
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
        border-radius: 6px;
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
        font-weight: bold;
        font-size: {fs['small']}pt;
        min-height: {max(m['table_row_height'] - 2, 20)}px;
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
        border-radius: {max(4, m['scrollbar_thickness'] // 2)}px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['scrollbar_handle']};
        min-height: 30px;
        border-radius: {max(4, m['scrollbar_thickness'] // 2)}px;
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
        border-radius: {max(4, m['scrollbar_thickness'] // 2)}px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['scrollbar_handle']};
        min-width: 30px;
        border-radius: {max(4, m['scrollbar_thickness'] // 2)}px;
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
        width: 4px;
    }}
    QSplitter::handle:hover {{
        background-color: {c['active_border']};
        width: 4px;
    }}

    /* ====================================================== */
    /* Status Bar                                              */
    /* ====================================================== */
    QStatusBar {{
        background-color: {c['mantle']};
        color: {c['subtext0']};
        border-top: 1px solid {c['border']};
        padding: 2px 8px;
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
        border-radius: 4px;
        padding: 4px 8px;
    }}

    /* ====================================================== */
    /* Progress Bar                                            */
    /* ====================================================== */
    QProgressBar {{
        background-color: {c['surface0']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        text-align: center;
        color: {c['text']};
        height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {c['active_border']};
        border-radius: 5px;
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
        border-radius: 6px;
        margin-top: 8px;
        padding-top: 16px;
        color: {c['text']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        color: {c['subtext1']};
    }}

    /* ====================================================== */
    /* Combo Box                                               */
    /* ====================================================== */
    QComboBox {{
        background-color: {c['input_bg']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 5px 10px;
    }}
    QComboBox:hover {{
        border: 1px solid {c['active_border']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['mantle']};
        color: {c['text']};
        border: 1px solid {c['border']};
        selection-background-color: {c['selection']};
        border-radius: 4px;
    }}

    /* ====================================================== */
    /* Check Box                                               */
    /* ====================================================== */
    QCheckBox {{
        color: {c['text']};
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {c['border']};
        border-radius: 4px;
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
        border-radius: 6px;
        background-color: {c['base']};
    }}
    QTabBar::tab {{
        background-color: {c['mantle']};
        color: {c['subtext0']};
        border: 1px solid {c['border']};
        border-bottom: none;
        padding: 6px 14px;
        min-width: {m['sidebar_tab_min_width']}px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-size: {fs['small']}pt;
    }}
    QTabWidget#sidebarTabs::pane {{
        border: 1px solid {c['border']};
        border-radius: 0 0 6px 6px;
        top: -1px;
    }}
    QTabWidget#sidebarTabs QTabBar::tab {{
        min-width: {m['sidebar_tab_min_width']}px;
        padding: 6px 12px;
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

    /* ====================================================== */
    /* Custom Panel Frame (applied via objectName)             */
    /* ====================================================== */
    QWidget#filePanel {{
        background-color: {c['panel_bg']};
        border: 1px solid {c['overlay0']};
        border-radius: 8px;
    }}
    QWidget#filePanelActive {{
        background-color: {c['panel_bg']};
        border: 1px solid {c['overlay0']};
        border-radius: 8px;
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
        border: 1px solid {c['border']};
        border-radius: 6px;
    }}
    QWidget#filePanelActive QTableView#panelFileTable {{
        border: 1px solid {c['panel_focus_ring']};
        border-radius: 6px;
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
        max-height: 14px;
        min-height: 14px;
    }}
    QFrame#transfersBar QPushButton#transfersCancel {{
        background-color: transparent;
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 2px 10px;
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
        border-radius: 4px;
        padding: {m['bottom_btn_pad_v']}px {m['bottom_btn_pad_h']}px;
        font-weight: bold;
        font-size: {fs['small']}pt;
        color: {c['subtext1']};
        min-width: 0;
        max-width: 140px;
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
        border-radius: 5px;
        padding: 2px 1px;
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
        border-radius: 5px;
        padding: 2px 1px;
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
        border-radius: 6px;
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
        padding: 2px 6px;
        font-size: {fs['small']}pt;
        min-height: {m['bookmark_btn_min_height']}px;
        min-width: 0;
    }}

    QLabel#bookmarksDropHint {{
        color: {c['blue']};
        font-size: {fs['small']}pt;
        padding: 2px 4px 4px 4px;
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
        padding: 0 4px;
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
        border-top-right-radius: 5px;
        border-bottom-right-radius: 5px;
        min-width: 14px;
        max-width: 14px;
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
        border-radius: 6px;
        selection-background-color: {c['selection']};
    }}
    QTableWidget#batchPreview::item {{
        padding: 3px 6px;
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
        padding: 2px 8px;
        font-size: {fs['small']}pt;
        min-height: {m['bookmark_btn_min_height']}px;
    }}

    QListWidget {{
        background-color: {c['panel_bg']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 6px;
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
    Apply dark (custom QSS), light (Fusion), or system default style + palette.
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
    if font_size_pt <= 10:
        app_font.setWeight(QFont.Medium)
    app.setFont(app_font)

    mode = (theme_mode or "dark").lower()

    if mode == "dark":
        app.setStyleSheet(getDarkThemeStylesheet(font_size_pt=font_size_pt, metrics=metrics))
        return

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
