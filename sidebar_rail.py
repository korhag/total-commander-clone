"""
Waypane - Thin stand-in for the bookmarks sidebar.

Shown when the window is narrow, or when the user hides the sidebar.
A click opens the sidebar on that tab.
"""

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QFrame, QToolButton, QVBoxLayout

from responsive_layout import SIDEBAR_RAIL_WIDTH


# ------------------------------------------------------------
# Class: SidebarRail
# Purpose: Icon buttons for Bookmarks and Libraries.
# ------------------------------------------------------------
class SidebarRail(QFrame):

    # Tab index: 0 bookmarks, 1 libraries.
    tabRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebarRail")
        self.setFixedWidth(SIDEBAR_RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 6)
        layout.setSpacing(4)

        self._bookmarks = self._makeButton(
            "Bookmarks",
            0,
            ("user-bookmarks", "bookmarks", "bookmark-new"),
        )
        self._libraries = self._makeButton(
            "Libraries",
            1,
            ("folder-library", "folder-documents", "folder"),
        )
        layout.addWidget(self._bookmarks)
        layout.addWidget(self._libraries)
        layout.addStretch(1)
        self.refreshIcons()

    # --------------------------------------------------------
    # Method: _makeButton
    # Purpose: One rail button. Uses a theme icon, or the first
    #          letter when the theme has no matching icon.
    # --------------------------------------------------------
    def _makeButton(self, label, index, icon_names):
        button = QToolButton(self)
        button.setObjectName("sidebarRailButton")
        button.setToolTip(
            label + "\n\nShow the sidebar with " + label.lower() + " open."
        )
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAccessibleName(label)
        button.clicked.connect(
            lambda checked, tab_index=index: self.tabRequested.emit(tab_index)
        )
        return button

    def refreshIcons(self):
        from action_icons import iconForAction
        from theme import themeColor

        self._bookmarks.setIcon(iconForAction("bookmark"))
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(themeColor("text", "#cdd6f4")), 2))
        painter.drawRoundedRect(4, 7, 20, 16, 2, 2)
        painter.drawRoundedRect(9, 12, 19, 14, 2, 2)
        painter.end()
        self._libraries.setIcon(QIcon(pixmap))

    # --------------------------------------------------------
    # Method: applyUiMetrics
    # Purpose: Match icon size to the rest of the window.
    # --------------------------------------------------------
    def applyUiMetrics(self, metrics):
        if not metrics:
            return
        icon = metrics.get("toolbar_icon", 16)
        side = max(SIDEBAR_RAIL_WIDTH, icon + 20)
        self.setFixedWidth(side)
        for button in (self._bookmarks, self._libraries):
            button.setIconSize(QSize(icon, icon))
            button.setFixedSize(side - 6, side - 6)
