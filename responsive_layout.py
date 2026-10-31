"""
Total Commander Clone - Width tiers for a narrow window.

Cut-offs are in pixels at layout scale 1. Callers multiply by the
scale from theme.getUiMetrics so font size and density stay in step.
"""

# ------------------------------------------------------------
# Tiers
# ------------------------------------------------------------
TIER_WIDE = "wide"
TIER_COMPACT = "compact"
TIER_NARROW = "narrow"

# ------------------------------------------------------------
# Window
# ------------------------------------------------------------
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 460

# A file panel narrower than this drops the text on Settings,
# Thumbnails, and Clear. Below the narrow cut-off, extra controls
# move into the "..." menu.
PANEL_COMPACT_WIDTH = 620
PANEL_NARROW_WIDTH = 460
# The panel must be allowed to shrink to this, or the narrow tier
# can never start: the full row's minimum would hold it open.
PANEL_MIN_WIDTH = 240

FILTER_MIN_WIDTH_WIDE = 120
FILTER_MIN_WIDTH_COMPACT = 80

# ------------------------------------------------------------
# Tabs, sidebar, center strip
# ------------------------------------------------------------
PANEL_TAB_MIN_WIDTH = 72
PANEL_TAB_MAX_WIDTH = 168

# The bookmarks sidebar folds into a thin rail below this window width.
SIDEBAR_AUTO_COLLAPSE_WIDTH = 1100
SIDEBAR_RAIL_WIDTH = 36

# Center COPY / MOVE / SPECIAL labels hide below this window width.
CENTER_LABELS_HIDE_WIDTH = 1000

# Column keys hidden for width. The user's own choice is kept and
# restored when the panel is wide again. Name and size are never here.
COLUMNS_HIDDEN_BY_TIER = {
    TIER_WIDE: (),
    TIER_COMPACT: ("type",),
    TIER_NARROW: ("type", "date_modified"),
}


# ------------------------------------------------------------
# Function: scaled
# Purpose: Apply the current UI scale to a base pixel size.
# Input: base (int), layout_scale (float)
# Output: int
# ------------------------------------------------------------
def scaled(base, layout_scale=1.0):
    scale = layout_scale if layout_scale and layout_scale > 0 else 1.0
    return max(1, int(round(base * scale)))


# ------------------------------------------------------------
# Function: layoutTier
# Purpose: Pick wide, compact, or narrow from a widget width.
# Input: width (int), layout_scale (float), compact_at (int), narrow_at (int)
# Output: str - TIER_WIDE, TIER_COMPACT, or TIER_NARROW.
# ------------------------------------------------------------
def layoutTier(width, layout_scale=1.0, compact_at=PANEL_COMPACT_WIDTH, narrow_at=PANEL_NARROW_WIDTH):
    if width is None:
        return TIER_WIDE
    scale = layout_scale if layout_scale and layout_scale > 0 else 1.0
    narrow_px = scaled(narrow_at, scale)
    compact_px = scaled(compact_at, scale)
    if compact_px <= narrow_px:
        compact_px = narrow_px + 1
    if width < narrow_px:
        return TIER_NARROW
    if width < compact_px:
        return TIER_COMPACT
    return TIER_WIDE
