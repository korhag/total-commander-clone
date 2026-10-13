"""
Total Commander Clone - Folder tabs for one file panel

One file panel stays on each side. Each tab stores the dictionary
from FilePanel.getHistoryData(). Switching tabs saves the panel you
are leaving and restores the other tab.
"""

import copy
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QTabBar


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
# Class: PanelTabBar
# Purpose: The tab strip above one file panel.
# ------------------------------------------------------------
class PanelTabBar(QTabBar):

    # Emitted after a tab switch has loaded that tab's folder.
    tabDisplayed = pyqtSignal()

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
        self.setElideMode(Qt.ElideRight)
        self.setDrawBase(True)
        self.setTabsClosable(False)

        self._guard = True
        self.addTab("New tab")
        self._guard = False

        self.currentChanged.connect(self._onCurrentChanged)
        self.tabCloseRequested.connect(self.closeTab)
        panel.pathChanged.connect(self._onPathChanged)

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
        if not path or not os.path.isdir(path):
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
            if isinstance(path, str) and path and os.path.isdir(path):
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

    def _syncCloseButtons(self):
        self.setTabsClosable(self.count() > 1)
