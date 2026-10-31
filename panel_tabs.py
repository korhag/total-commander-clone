"""
Total Commander Clone - Folder tabs for one file panel

One file panel stays on each side. Each tab stores the dictionary
from FilePanel.getHistoryData(). Switching tabs saves the panel you
are leaving and restores the other tab.
"""

import copy
import os

from archive_backend import isNavigablePath
from responsive_layout import PANEL_TAB_MAX_WIDTH, PANEL_TAB_MIN_WIDTH, scaled
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QMenu, QTabBar, QToolButton


# ------------------------------------------------------------
# Function: splitTabState
# Purpose: Turn saved state into (list of tab dicts, active index).
#          An older state file is one panel dict, not a tab list.
#          Damaged data becomes a single empty tab.
# ------------------------------------------------------------
def splitTabState(data):
    if isinstance(data, dict):
        tabs = data.get("tabs")
        if isinstance(tabs, list):
            clean = [item for item in tabs if isinstance(item, dict)]
            if clean:
                active = data.get("active", 0)
                if isinstance(active, bool) or not isinstance(active, int):
                    active = 0
                active = max(0, min(active, len(clean) - 1))
                return clean, active
        if any(
            key in data
            for key in ("current_path", "history", "column_widths", "filter_text")
        ):
            return [data], 0
    return [{}], 0


# ------------------------------------------------------------
# Function: activeTabRecord
# Purpose: The tab dict that was on screen, or the legacy
#          panel dict when the file has no tab list.
# ------------------------------------------------------------
def activeTabRecord(data):
    tabs, active = splitTabState(data)
    if not tabs:
        return {}
    record = tabs[active]
    return record if isinstance(record, dict) else {}


def _folderLabel(path):
    if not isinstance(path, str) or not path:
        return "New tab"
    try:
        name = os.path.basename(os.path.normpath(path))
    except (OSError, ValueError):
        name = ""
    return name or path


# ------------------------------------------------------------
# Class: _TabCloseButton
# Purpose: The "x" on a folder tab. Qt's built-in close glyph is
#          a light square, and a stylesheet hover rule on
#          QTabBar::close-button paints over that glyph. A text
#          mark takes its color from the theme instead.
# ------------------------------------------------------------
class _TabCloseButton(QToolButton):

    def __init__(self, tab_bar):
        super().__init__(tab_bar)
        self._tab_bar = tab_bar
        self.setObjectName("panelTabCloseButton")
        self.setText("\u00d7")
        self.setToolTip("Close tab")
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.clicked.connect(self._onClicked)

    def _onClicked(self):
        self._tab_bar._closeFromButton(self)


# ------------------------------------------------------------
# Class: PanelTabBar
# Purpose: The tab strip above one file panel.
# ------------------------------------------------------------
class PanelTabBar(QTabBar):

    # Emitted after a tab switch has loaded that tab's folder.
    tabDisplayed = pyqtSignal()
    # The window opens the tab, so the panel it belongs to becomes active.
    newTabRequested = pyqtSignal()
    # Right-click a tab: open that tab's folder outside the app.
    openInExplorerRequested = pyqtSignal(str)
    openInTerminalRequested = pyqtSignal(str)

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._states = [{}]
        self._current = 0
        self._guard = False

        self.setObjectName("panelTabBar")
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideMiddle)
        self.setDrawBase(True)
        self.setTabsClosable(False)

        self._guard = True
        self.addTab("New tab")
        self._guard = False

        self.currentChanged.connect(self._onCurrentChanged)
        self.tabCloseRequested.connect(self.closeTab)
        panel.pathChanged.connect(self._onPathChanged)

    # --------------------------------------------------------
    # Method: tabSizeHint
    # Purpose: Keep each tab between a minimum and a maximum
    #          so one long folder name cannot push the others
    #          off the strip. The tooltip still has the full path.
    #          The middle of the name is what gets cut.
    # --------------------------------------------------------
    def tabSizeHint(self, index):
        hint = super().tabSizeHint(index)
        scale = 1.0
        panel = getattr(self, "_panel", None)
        if panel is not None:
            scale = float(getattr(panel, "_layout_scale", 1.0) or 1.0)
        min_w = scaled(PANEL_TAB_MIN_WIDTH, scale)
        max_w = scaled(PANEL_TAB_MAX_WIDTH, scale)
        hint.setWidth(max(min_w, min(int(hint.width()), max_w)))
        return hint

    # --------------------------------------------------------
    # Method: newTab
    # Purpose: Open another tab on the folder that is showing.
    # --------------------------------------------------------
    def newTab(self):
        self._rememberCurrent()
        state = copy.deepcopy(self._panel.getHistoryData())
        self._appendAndSwitch(state)

    # --------------------------------------------------------
    # Method: openInNewTab
    # Purpose: Open a folder in a new tab. Filters start clear
    #          so the folder is not hidden by the current search.
    # --------------------------------------------------------
    def openInNewTab(self, path):
        if not isNavigablePath(path):
            return False
        self._rememberCurrent()
        state = copy.deepcopy(self._panel.getHistoryData())
        folder = os.path.normpath(path)
        state["current_path"] = folder
        state["history"] = [folder]
        state["history_index"] = 0
        state["filter_text"] = ""
        state["filter_exclude_text"] = ""
        state["filter_extensions"] = ""
        state["filter_include_subfolders"] = False
        state["filter_kind"] = "all"
        state["filter_mode"] = "contains"
        state["filter_advanced"] = {}
        self._appendAndSwitch(state)
        return True

    # --------------------------------------------------------
    # Method: closeTab
    # Purpose: Close one tab. The last tab stays open.
    # Output: True when a tab was closed.
    # --------------------------------------------------------
    def closeTab(self, index=None):
        count = self.count()
        if count <= 1:
            return False
        if index is None:
            index = self.currentIndex()
        if isinstance(index, bool) or not isinstance(index, int):
            return False
        if not (0 <= index < count):
            return False

        closing_current = index == self._current
        if not closing_current:
            self._rememberCurrent()

        self._guard = True
        try:
            self.removeTab(index)
            del self._states[index]
            if closing_current:
                self._current = self.currentIndex()
            elif self._current > index:
                self._current -= 1
        finally:
            self._guard = False

        self._syncCloseButtons()
        if closing_current:
            self._restoreCurrent()
        return True

    # --------------------------------------------------------
    # Method: closeOtherTabs
    # Purpose: Leave one tab open and drop the rest.
    # Input: index (int) - The tab that stays.
    # Output: True when other tabs were closed.
    # --------------------------------------------------------
    def closeOtherTabs(self, index):
        count = self.count()
        if count <= 1:
            return False
        if isinstance(index, bool) or not isinstance(index, int):
            return False
        if not (0 <= index < count) or index >= len(self._states):
            return False

        if index == self._current:
            self._rememberCurrent()
        kept = copy.deepcopy(self._states[index])
        if not isinstance(kept, dict):
            kept = {}

        self._guard = True
        try:
            for tab_index in range(count - 1, index, -1):
                self.removeTab(tab_index)
            for tab_index in range(index - 1, -1, -1):
                self.removeTab(tab_index)
            self._states = [kept]
            self._current = 0
            path = kept.get("current_path") or ""
            if not isinstance(path, str):
                path = ""
            self.setTabText(0, _folderLabel(path))
            self.setTabToolTip(0, path)
            if self.currentIndex() != 0:
                self.setCurrentIndex(0)
        finally:
            self._guard = False

        self._syncCloseButtons()
        self._restoreCurrent()
        return True

    # --------------------------------------------------------
    # Method: selectRelative
    # Purpose: Move to the next or previous tab, wrapping around.
    # --------------------------------------------------------
    def selectRelative(self, step):
        count = self.count()
        if count <= 1:
            return
        index = (self.currentIndex() + int(step)) % count
        self.setCurrentIndex(index)

    # --------------------------------------------------------
    # Method: exportState
    # Purpose: Tab list and the active index, for state.json.
    # --------------------------------------------------------
    def exportState(self):
        self._rememberCurrent()
        active = self.currentIndex()
        if active < 0:
            active = 0
        return {
            "tabs": copy.deepcopy(self._states),
            "active": active,
        }

    # --------------------------------------------------------
    # Method: importState
    # Purpose: Replace the tabs from saved state. A legacy
    #          single-panel dict becomes one tab.
    # --------------------------------------------------------
    def importState(self, data):
        tabs, active = splitTabState(data)
        self._guard = True
        try:
            while self.count() > 0:
                self.removeTab(0)
            self._states = [copy.deepcopy(item) for item in tabs]
            for state in self._states:
                path = ""
                if isinstance(state, dict):
                    path = state.get("current_path") or ""
                if not isinstance(path, str):
                    path = ""
                index = self.addTab(_folderLabel(path))
                self.setTabToolTip(index, path)
            self._current = active
            self.setCurrentIndex(active)
        finally:
            self._guard = False
        self._syncCloseButtons()
        self._restoreCurrent()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            index = self.tabAt(event.pos())
            if index >= 0:
                self.closeTab(index)
                return
        super().mouseReleaseEvent(event)

    # --------------------------------------------------------
    # Method: mouseDoubleClickEvent
    # Purpose: A double-click on the empty part of the strip
    #          asks the window for another tab.
    # --------------------------------------------------------
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.tabAt(event.pos()) < 0:
            self.newTabRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # --------------------------------------------------------
    # Method: folderForTab
    # Purpose: The real folder that tab is showing. The current
    #          tab uses the panel. Another tab uses the path
    #          saved when you left it.
    # --------------------------------------------------------
    def folderForTab(self, index):
        if isinstance(index, bool) or not isinstance(index, int):
            return ""
        if not (0 <= index < self.count()):
            return ""
        if index == self._current:
            path = self._panel.currentPath() or ""
        else:
            state = self._states[index] if index < len(self._states) else {}
            path = ""
            if isinstance(state, dict):
                path = state.get("current_path") or ""
        if not isinstance(path, str) or not path:
            return ""
        try:
            path = os.path.normpath(path)
        except (OSError, ValueError):
            return ""
        if os.path.isdir(path):
            return path
        return ""

    # --------------------------------------------------------
    # Method: tabContextMenu
    # Purpose: New, close, and — when a tab was clicked —
    #          open that folder in the file manager or a terminal.
    # --------------------------------------------------------
    def tabContextMenu(self, index):
        only_one = self.count() <= 1
        menu = QMenu(self)
        new_action = menu.addAction("New Tab")
        new_action.setData("new")
        close_action = menu.addAction("Close Tab")
        close_action.setData("close")
        others_action = menu.addAction("Close Other Tabs")
        others_action.setData("others")
        close_action.setEnabled(index >= 0 and not only_one)
        others_action.setEnabled(index >= 0 and not only_one)
        if index >= 0:
            menu.addSeparator()
            folder = self.folderForTab(index)
            explorer_action = menu.addAction("Open in Explorer")
            explorer_action.setData("explorer")
            explorer_action.setToolTip(
                "Open in Explorer\n\n"
                "Open this tab's folder in the system file manager."
            )
            explorer_action.setEnabled(bool(folder))
            terminal_action = menu.addAction("Open in Terminal")
            terminal_action.setData("terminal")
            terminal_action.setToolTip(
                "Open in Terminal\n\n"
                "Open the default terminal in this tab's folder."
            )
            terminal_action.setEnabled(bool(folder))
        return menu

    # --------------------------------------------------------
    # Method: contextMenuEvent
    # Purpose: Right-click menu for a new tab, closing this
    #          tab, or opening that tab's folder outside the app.
    # --------------------------------------------------------
    def contextMenuEvent(self, event):
        index = self.tabAt(event.pos())
        menu = self.tabContextMenu(index)
        chosen = menu.exec_(event.globalPos())
        kind = chosen.data() if chosen is not None else None
        if kind == "new":
            self.newTabRequested.emit()
        elif kind == "close":
            self.closeTab(index)
        elif kind == "others":
            self.closeOtherTabs(index)
        elif kind == "explorer":
            folder = self.folderForTab(index)
            if folder:
                self.openInExplorerRequested.emit(folder)
        elif kind == "terminal":
            folder = self.folderForTab(index)
            if folder:
                self.openInTerminalRequested.emit(folder)
        event.accept()

    def _appendAndSwitch(self, state):
        if not isinstance(state, dict):
            state = {}
        self._states.append(state)
        path = state.get("current_path") or ""
        if not isinstance(path, str):
            path = ""
        self._guard = True
        try:
            index = self.addTab(_folderLabel(path))
            self.setTabToolTip(index, path)
        finally:
            self._guard = False
        self._syncCloseButtons()
        if self.currentIndex() != index:
            self.setCurrentIndex(index)
            return
        self._current = index
        self._restoreCurrent()

    def _onCurrentChanged(self, index):
        if self._guard or index < 0 or index == self._current:
            return
        previous = self._current
        if 0 <= previous < len(self._states):
            self._states[previous] = self._panel.getHistoryData()
        self._current = index
        self._restoreCurrent()

    def _onPathChanged(self, _path):
        if self._guard:
            return
        self._rememberCurrent()

    def _rememberCurrent(self):
        if self._guard:
            return
        index = self._current
        if not (0 <= index < len(self._states)):
            return
        self._states[index] = self._panel.getHistoryData()
        self._applyLabel(index, self._panel.currentPath())

    def _restoreCurrent(self):
        index = self._current
        if not (0 <= index < len(self._states)):
            return
        state = self._states[index]
        self._guard = True
        try:
            path = ""
            if isinstance(state, dict):
                path = state.get("current_path") or ""
            if isinstance(path, str) and isNavigablePath(path):
                self._panel.restoreHistoryData(state)
        finally:
            self._guard = False
        shown = self._panel.currentPath() or ""
        self._applyLabel(index, shown)
        self.tabDisplayed.emit()

    def _applyLabel(self, index, path):
        if not (0 <= index < self.count()):
            return
        if not isinstance(path, str):
            path = ""
        self.setTabText(index, _folderLabel(path))
        self.setTabToolTip(index, path)

    def _closeFromButton(self, button):
        for index in range(self.count()):
            if self.tabButton(index, QTabBar.RightSide) is button:
                self.closeTab(index)
                return

    # --------------------------------------------------------
    # Method: _syncCloseButtons
    # Purpose: Show an "x" on every tab once a second tab exists.
    #          The last tab has no close button.
    # --------------------------------------------------------
    def _syncCloseButtons(self):
        show = self.count() > 1
        for index in range(self.count()):
            existing = self.tabButton(index, QTabBar.RightSide)
            if not show:
                if existing is not None:
                    self.setTabButton(index, QTabBar.RightSide, None)
                continue
            if isinstance(existing, _TabCloseButton):
                continue
            self.setTabButton(index, QTabBar.RightSide, _TabCloseButton(self))
