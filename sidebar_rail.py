"""
Total Commander Clone - Thin stand-in for the bookmarks sidebar.

Shown when the window is narrow, or when the user hides the sidebar.
A click opens the sidebar on that tab.
"""

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon
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
        icon = QIcon()
        for name in icon_names:
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                break
        if icon.isNull():
            button.setText(label[:1])
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        else:
            button.setIcon(icon)
        button.clicked.connect(
            lambda checked, tab_index=index: self.tabRequested.emit(tab_index)
        )
        return button

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
