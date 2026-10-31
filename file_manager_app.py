"""
Total Commander Clone - Main Application Window
Assembles the dual-pane layout, toolbar, menu bar, status bar,
right-click context menus, keyboard shortcuts, and bookmarks.
"""

import os
import subprocess
import platform
import uuid

from PyQt5.QtWidgets import (
    QMainWindow, QSplitter, QToolBar, QAction, QActionGroup, QStatusBar,
    QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
    QMenu, QMessageBox, QInputDialog, QApplication, QLabel,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QFileDialog,
    QTabWidget, QStackedWidget, QSizePolicy, QToolButton,
)
from PyQt5.QtCore import Qt, QUrl, QTimer, QRect, QSize, QEvent, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence, QDesktopServices, QIcon

from file_panel import (
    FilePanel,
    DEFAULT_DATE_MODIFIED_FORMAT,
    formatFileSize,
    resolve_date_modified_format_key,
)
from drive_list import driveLabelForPath, listDrives
from folder_stats import DriveSpaceWorker
from recursive_scan_worker import retireThread, waitForThreads
from file_operations import renameFile
from file_operation_queue import FileOperationQueue
from transfers_bar import TransfersBar, TransfersDetailsDialog
from batch_rename_dialog import BatchRenameDialog
from bookmarks_panel import BookmarksPanel
from libraries_panel import LibrariesPanel
from library_browser_panel import LibraryBrowserPanel
from library_dialogs import LibraryRootDialog, TagAssignmentDialog
from library_manager import LibraryManager
from settings_manager import SettingsManager
from windows_shell_clipboard import setFileClipboard, getClipboardDropEffect
from app_version import APP_VERSION, APP_NAME, getWindowTitle
from file_properties_dialog import showFileProperties
from file_viewer import FileViewerWidget, FileViewerWindow, openInSystemEditor
from archive_backend import (
    archiveCacheDir,
    archiveDisplayStem,
    clearArchiveCache,
    find7zExecutable,
    getArchivePassword,
    isArchiveFile,
    isNavigablePath,
    isPasswordError,
    missing7zHint,
    pathInsideArchive,
    setArchivePassword,
    splitArchivePath,
)
from compress_dialog import CompressDialog
from panel_tabs import PanelTabBar, activeTabRecord
from responsive_layout import (
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    SIDEBAR_AUTO_COLLAPSE_WIDTH,
    scaled,
)
from settings_dialog import SettingsDialog
from sidebar_rail import SidebarRail
from terminal_launcher import openTerminalAt
from theme import applyTheme, getUiMetrics, normalize_ui_scale, step_ui_scale, ui_scale_label
from app_updater import (
    checkRemoteAppVersion,
    getPublishPreview,
    launchUpdateAndRebuild,
    publishLocalVersionToGitHub,
)
from config_backup import _loadSavedGitAuth
from git_credentials_dialog import GitCredentialsDialog


# ------------------------------------------------------------
# Shutdown waits (milliseconds) for background work on close.
# ------------------------------------------------------------
TRANSFER_SHUTDOWN_WAIT_MS = 10000
UPDATE_CHECK_SHUTDOWN_WAIT_MS = 5000
DRIVE_SPACE_SHUTDOWN_WAIT_MS = 500

# Right-click the main toolbar. Text beside the icon keeps the
# shortcut labels. Small matches the theme icon size; medium and
# large scale that size and still follow font size and density.
TOOLBAR_BUTTON_STYLES = {
    "icon_only": Qt.ToolButtonIconOnly,
    "text_beside": Qt.ToolButtonTextBesideIcon,
    "text_under": Qt.ToolButtonTextUnderIcon,
}
TOOLBAR_ICON_SCALES = {
    "small": 1.0,
    "medium": 1.5,
    "large": 2.0,
}
DEFAULT_TOOLBAR_BUTTON_STYLE = "text_beside"
DEFAULT_TOOLBAR_ICON_SIZE = "small"
TOOLBAR_STYLE_LABELS = (
    ("icon_only", "Icons only"),
    ("text_beside", "Icons and text"),
    ("text_under", "Text under icons"),
)
TOOLBAR_SIZE_LABELS = (
    ("small", "Small icons"),
    ("medium", "Medium icons"),
    ("large", "Large icons"),
)


# ------------------------------------------------------------
# Function: normalizeToolbarButtonStyle
# Purpose: A known toolbar style, or icons-and-text when the
#          saved value is missing or misspelled.
# ------------------------------------------------------------
def normalizeToolbarButtonStyle(value):
    text = str(value or "").strip().lower()
    if text in TOOLBAR_BUTTON_STYLES:
        return text
    return DEFAULT_TOOLBAR_BUTTON_STYLE


# ------------------------------------------------------------
# Function: normalizeToolbarIconSize
# Purpose: A known icon size, or small when the saved value
#          is missing or misspelled.
# ------------------------------------------------------------
def normalizeToolbarIconSize(value):
    text = str(value or "").strip().lower()
    if text in TOOLBAR_ICON_SCALES:
        return text
    return DEFAULT_TOOLBAR_ICON_SIZE


# ------------------------------------------------------------
# Function: toolbarIconPixels
# Purpose: Pixel size for the toolbar icons. `base` is the
#          theme size. Large is twice that.
# ------------------------------------------------------------
def toolbarIconPixels(base, size_id):
    scale = TOOLBAR_ICON_SCALES[normalizeToolbarIconSize(size_id)]
    return max(14, int(round(int(base) * scale)))


# ------------------------------------------------------------
# Class: UpdateCheckWorker
# Purpose: Background Git fetch + APP_VERSION compare (no UI).
# ------------------------------------------------------------
class UpdateCheckWorker(QThread):

    resultReady = pyqtSignal(dict)

    def __init__(self, project_root, local_version, skip_version="", parent=None):
        super().__init__(parent)
        self._project_root = project_root
        self._local_version = local_version
        self._skip_version = skip_version or ""

    def run(self):
        try:
            result = checkRemoteAppVersion(
                self._local_version,
                project_root=self._project_root,
                skip_version=self._skip_version,
            )
        except Exception as exc:
            result = {
                "status": "error",
                "local": self._local_version,
                "remote": "",
                "repo_root": "",
                "message": str(exc),
                "can_publish": False,
            }
        self.resultReady.emit(result)


# ------------------------------------------------------------
# Class: PublishVersionWorker
# Purpose: Background commit (if needed) + non-force git push.
# ------------------------------------------------------------
class PublishVersionWorker(QThread):

    resultReady = pyqtSignal(bool, str, bool)

    def __init__(self, repo_root, auth=None, parent=None):
        super().__init__(parent)
        self._repo_root = repo_root
        self._auth = auth

    def run(self):
        try:
            ok, message, auth_failed = publishLocalVersionToGitHub(
                self._repo_root,
                auth=self._auth,
            )
        except Exception as exc:
            ok, message, auth_failed = False, str(exc), False
        self.resultReady.emit(ok, message, auth_failed)


# ------------------------------------------------------------
# Function: sanitizeWindowGeometry
# Purpose: Clamps size and repositions the window onto a visible
#          screen (frozen builds use %APPDATA% settings that may
#          reference a disconnected monitor).
# ------------------------------------------------------------
def sanitizeWindowGeometry(geo):
    defaults = {"x": 100, "y": 100, "width": 1400, "height": 800}
    if not isinstance(geo, dict):
        return dict(defaults)

    min_w, min_h = MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
    try:
        w = int(geo.get("width", defaults["width"]))
        h = int(geo.get("height", defaults["height"]))
        x = int(geo.get("x", defaults["x"]))
        y = int(geo.get("y", defaults["y"]))
    except (TypeError, ValueError):
        return dict(defaults)

    w = max(min_w, min(w, 7680))
    h = max(min_h, min(h, 4320))

    app = QApplication.instance()
    if app is None:
        return {"x": x, "y": y, "width": w, "height": h}

    screens = app.screens()
    if not screens:
        return {"x": defaults["x"], "y": defaults["y"], "width": w, "height": h}

    window_rect = QRect(x, y, w, h)
    if any(window_rect.intersects(s.availableGeometry()) for s in screens):
        return {"x": x, "y": y, "width": w, "height": h}

    primary = app.primaryScreen()
    if primary is None:
        return dict(defaults)

    avail = primary.availableGeometry()
    x = avail.x() + max(0, (avail.width() - w) // 2)
    y = avail.y() + max(0, (avail.height() - h) // 2)
    return {"x": x, "y": y, "width": w, "height": h}


# ============================================================
# Class: FileManagerApp
# Purpose: The main application window. Manages the dual-pane
#          file browser, toolbar, menu bar, keyboard shortcuts,
#          right-click menus, drag-and-drop integration, and
#          settings persistence.
# ============================================================
class FileManagerApp(QMainWindow):

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self._settings = settings_manager
        self._library_manager = LibraryManager(settings_manager)
        self._active_panel = None
        self._clipboard_paths = []
        self._clipboard_mode = None
        self._password_declined = set()
        self._viewer_window = None
        self._drive_space_worker = None
        self._retired_drive_space_threads = set()
        self._drive_space_path = ""
        self._drive_space_closed = False

        self._initWindow()
        self._initStatusBar()
        self._initMenuBar()
        self._initToolBar()
        self._initPanels()
        self._initTransfers()
        self._initBottomBar()
        self._initShortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._applyUiMetrics()
        self._updateSidebarCollapse()
        self._updateMirrorTooltips()
        self._state_restore_done = False
        self._post_show_layout_done = False
        self._update_check_worker = None
        self._update_check_manual = False
        self._update_check_publish_intent = False
        self._publish_worker = None
        self._publish_pending_result = None
        self._configureScanCache()
        self._refreshThemedIcons()
        self._show_home_path()

    # --------------------------------------------------------
    # Method: _configureScanCache
    # Purpose: Point recursive scan cache at config dir + settings flag.
    # --------------------------------------------------------
    def _configureScanCache(self):
        from scan_cache import configureScanCache, pruneScanCacheOnStartup

        config_dir = os.path.dirname(
            getattr(self._settings, "_settings_path", "") or ""
        ) or None
        enabled = self._settings.getSetting("cache_recursive_scans", True)
        configureScanCache(config_dir, enabled=enabled)
        try:
            pruneScanCacheOnStartup()
        except Exception:
            pass

    # --------------------------------------------------------
    # Method: _show_home_path
    # Purpose: Opens local home folders immediately so the window
    #          is usable before deferred %APPDATA% state restore
    #          (network paths and library scans can block for seconds).
    # --------------------------------------------------------
    def _show_home_path(self):
        home = os.path.expanduser("~")
        for panel in (self._left_panel, self._right_panel):
            if not panel.currentPath():
                panel.navigateTo(home, add_to_history=False)

    # --------------------------------------------------------
    # Method: showEvent
    # Purpose: Ensure the window is visible on-screen, then defer
    #          saved state restore and post-show layout so startup
    #          never blocks before the first paint.
    # --------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._ensureWindowVisibleOnStartup()
        if not self._state_restore_done:
            QTimer.singleShot(100, self._deferredRestoreStateAndLayout)

    # --------------------------------------------------------
    # Method: _ensureWindowVisibleOnStartup
    # Purpose: Correct minimized, hidden, or off-screen geometry
    #          saved in settings (common after monitor changes).
    # --------------------------------------------------------
    def _ensureWindowVisibleOnStartup(self):
        if self.windowState() & Qt.WindowMinimized:
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.showNormal()

        frame = self.frameGeometry()
        app = QApplication.instance()
        screens = app.screens() if app is not None else []
        on_screen = (
            any(frame.intersects(s.availableGeometry()) for s in screens)
            if screens
            else True
        )
        if (
            not on_screen
            or frame.width() < 100
            or frame.height() < 100
            or not self.isVisible()
        ):
            geo = sanitizeWindowGeometry({
                "x": frame.x(),
                "y": frame.y(),
                "width": max(frame.width(), MIN_WINDOW_WIDTH),
                "height": max(frame.height(), MIN_WINDOW_HEIGHT),
            })
            self.setGeometry(
                geo["x"], geo["y"], geo["width"], geo["height"],
            )
            self._settings.setSetting("window_geometry", geo)

        self.raise_()
        self.activateWindow()

    # --------------------------------------------------------
    # Method: _deferredRestoreStateAndLayout
    # Purpose: Runs saved panel/library restore after the window
    #          is on screen (avoids invisible-window startup hangs).
    # --------------------------------------------------------
    def _deferredRestoreStateAndLayout(self):
        if self._state_restore_done:
            return
        self._state_restore_done = True
        self._restoreState()
        notice = self._settings.consumeBookmarkRecoveryNotice()
        if notice:
            self._showStatus(notice, timeout=12000)
        if not self._post_show_layout_done:
            self._post_show_layout_done = True
            self._runPostShowLayout()
        if self._settings.getSetting("check_for_updates_on_startup", True):
            QTimer.singleShot(1800, lambda: self._startUpdateCheck(manual=False))

    def _runPostShowLayout(self):
        self._updateSidebarCollapse()
        if not self._sidebar_collapsed:
            sizes = self._main_splitter.sizes()
            if sizes and sizes[0] < 180:
                rest = max(400, sum(sizes) - 260)
                self._main_splitter.setSizes([260, rest])
        self._applyUiMetrics()
        self._left_panel.relayoutColumns()
        self._right_panel.relayoutColumns()

    # --------------------------------------------------------
    # Method: resizeEvent
    # Purpose: Fold the sidebar, slim the center strip, and
    #          shorten the F-key labels when the window is narrow.
    # --------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_main_splitter"):
            return
        self._updateSidebarCollapse()
        self._applyCenterStripMode()
        self._applyBottomBarLabels()

    # --------------------------------------------------------
    # Method: _initWindow
    # Purpose: Configures window title, geometry, and restores
    #          saved position/size from settings.
    # --------------------------------------------------------
    def _initWindow(self):
        self.setWindowTitle(getWindowTitle())
        raw_geo = self._settings.getSetting("window_geometry", {})
        geo = sanitizeWindowGeometry(raw_geo)
        if geo != raw_geo:
            self._settings.setSetting("window_geometry", geo)
            self._settings.saveSettings()
        self.setGeometry(
            geo["x"],
            geo["y"],
            geo["width"],
            geo["height"],
        )
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

    # --------------------------------------------------------
    # Method: _initMenuBar
    # Purpose: Creates the menu bar with File, Edit, View,
    #          Bookmarks, and Help menus. Settings lives under Edit.
    # --------------------------------------------------------
    def _initMenuBar(self):
        menu_bar = self.menuBar()

        # --- File Menu ---
        file_menu = menu_bar.addMenu("&File")

        self._action_new_folder = QAction("New Folder\tF8", self)
        self._action_new_folder.setToolTip(
            "New folder\n\n"
            "Create a new folder in the active panel’s current directory. Shortcut: F8."
        )
        self._action_new_folder.triggered.connect(self._onNewFolder)
        file_menu.addAction(self._action_new_folder)

        file_menu.addSeparator()

        self._action_exit = QAction("Exit\tAlt+F4", self)
        self._action_exit.setToolTip("Exit\n\nClose the application. Shortcut: Alt+F4.")
        self._action_exit.triggered.connect(self.close)
        file_menu.addAction(self._action_exit)

        # --- Edit Menu ---
        edit_menu = menu_bar.addMenu("&Edit")

        self._action_cut = QAction("Cut\tCtrl+X", self)
        self._action_cut.setToolTip(
            "Cut\n\n"
            "Remove selected items and place them on the clipboard for moving. Shortcut: Ctrl+X."
        )
        self._action_cut.triggered.connect(self._onCut)
        edit_menu.addAction(self._action_cut)

        self._action_copy_clip = QAction("Copy\tCtrl+C", self)
        self._action_copy_clip.setToolTip(
            "Copy\n\nCopy selected items to the clipboard. Shortcut: Ctrl+C."
        )
        self._action_copy_clip.triggered.connect(self._onCopyToClipboard)
        edit_menu.addAction(self._action_copy_clip)

        self._action_paste = QAction("Paste\tCtrl+V", self)
        self._action_paste.setToolTip(
            "Paste\n\n"
            "Paste into the active panel’s folder: items copied in this app, or files/folders "
            "copied or cut in the system file manager (Explorer, Finder, …). Shortcut: Ctrl+V."
        )
        self._action_paste.triggered.connect(self._onPaste)
        edit_menu.addAction(self._action_paste)

        edit_menu.addSeparator()

        self._action_select_all = QAction("Select All\tCtrl+A", self)
        self._action_select_all.setToolTip(
            "Select all\n\nSelect every item in the active panel. Shortcut: Ctrl+A."
        )
        self._action_select_all.triggered.connect(self._onSelectAll)
        edit_menu.addAction(self._action_select_all)

        edit_menu.addSeparator()

        self._action_rename = QAction("Rename\tF2", self)
        self._action_rename.setToolTip(
            "Rename\n\nRename the selected item. Shortcut: F2."
        )
        self._action_rename.triggered.connect(self._onRename)
        edit_menu.addAction(self._action_rename)

        self._action_batch_rename = QAction("Batch Rename...\tCtrl+M", self)
        self._action_batch_rename.setToolTip(
            "Batch rename\n\n"
            "Rename multiple files using patterns and rules. Shortcut: Ctrl+M."
        )
        self._action_batch_rename.triggered.connect(self._onBatchRename)
        edit_menu.addAction(self._action_batch_rename)

        edit_menu.addSeparator()

        self._action_settings = QAction("Settings...", self)
        self._action_settings.setToolTip(
            "Settings\n\n"
            "Theme, font size, interface density, hidden files, delete confirmation, "
            "and default folder paths. Shortcut: Ctrl+,"
        )
        self._action_settings.triggered.connect(self._onOpenSettings)
        edit_menu.addAction(self._action_settings)

        # --- View Menu ---
        view_menu = menu_bar.addMenu("&View")

        self._action_refresh = QAction("Refresh (both panels)", self)
        self._action_refresh.setToolTip(
            "Refresh both panels\n\nReload file listings in the left and right panels."
        )
        self._action_refresh.triggered.connect(self._onRefresh)
        view_menu.addAction(self._action_refresh)

        self._action_view_file = QAction("View\tF3", self)
        self._action_view_file.setToolTip(
            "View\n\n"
            "Open the selected file in the built-in viewer. "
            "N and P move to the next and previous file. Shortcut: F3."
        )
        self._action_view_file.triggered.connect(self._onViewFile)
        view_menu.addAction(self._action_view_file)

        self._action_edit_file = QAction("Edit\tF4", self)
        self._action_edit_file.setToolTip(
            "Edit\n\nOpen the selected file in the system editor. Shortcut: F4."
        )
        self._action_edit_file.triggered.connect(self._onEditFile)
        view_menu.addAction(self._action_edit_file)

        self._action_quick_view = QAction("Quick View\tCtrl+Q", self)
        self._action_quick_view.setToolTip(
            "Quick view\n\n"
            "Show the selected file in the other panel. Shortcut: Ctrl+Q."
        )
        self._action_quick_view.triggered.connect(self._onToggleQuickView)
        view_menu.addAction(self._action_quick_view)

        view_menu.addSeparator()

        self._action_new_tab = QAction("New Tab\tCtrl+T", self)
        self._action_new_tab.setToolTip(
            "New tab\n\nOpen another tab on the current folder. Shortcut: Ctrl+T."
        )
        self._action_new_tab.triggered.connect(self._onNewTab)
        view_menu.addAction(self._action_new_tab)

        self._action_close_tab = QAction("Close Tab\tCtrl+W", self)
        self._action_close_tab.setToolTip(
            "Close tab\n\nClose the current tab. The last tab stays open. Shortcut: Ctrl+W."
        )
        self._action_close_tab.triggered.connect(self._onCloseTab)
        view_menu.addAction(self._action_close_tab)

        self._action_next_tab = QAction("Next Tab\tCtrl+Tab", self)
        self._action_next_tab.setToolTip(
            "Next tab\n\nSwitch to the next tab in the active panel. Shortcut: Ctrl+Tab."
        )
        self._action_next_tab.triggered.connect(self._onNextTab)
        view_menu.addAction(self._action_next_tab)

        self._action_previous_tab = QAction("Previous Tab\tCtrl+Shift+Tab", self)
        self._action_previous_tab.setToolTip(
            "Previous tab\n\nSwitch to the previous tab in the active panel. "
            "Shortcut: Ctrl+Shift+Tab."
        )
        self._action_previous_tab.triggered.connect(self._onPreviousTab)
        view_menu.addAction(self._action_previous_tab)

        view_menu.addSeparator()

        self._action_show_hidden = QAction("Show Hidden Files", self)
        self._action_show_hidden.setToolTip(
            "Show hidden files\n\nToggle display of hidden and system items."
        )
        self._action_show_hidden.setCheckable(True)
        self._action_show_hidden.setChecked(
            self._settings.getSetting("show_hidden_files", False)
        )
        self._action_show_hidden.triggered.connect(self._onToggleHidden)
        view_menu.addAction(self._action_show_hidden)

        self._action_show_sidebar = QAction("Show Sidebar\tCtrl+B", self)
        self._action_show_sidebar.setToolTip(
            "Show sidebar\n\n"
            "Show or hide Bookmarks and Libraries. "
            "A narrow window folds this to a thin strip on its own. "
            "Shortcut: Ctrl+B."
        )
        self._action_show_sidebar.setCheckable(True)
        self._action_show_sidebar.setChecked(True)
        self._action_show_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        self._action_show_sidebar.setShortcutContext(Qt.WindowShortcut)
        self._action_show_sidebar.triggered.connect(self._onToggleSidebar)
        view_menu.addAction(self._action_show_sidebar)

        view_menu.addSeparator()

        self._action_settings_view = QAction("Settings...", self)
        self._action_settings_view.setToolTip(self._action_settings.toolTip())
        self._action_settings_view.triggered.connect(self._onOpenSettings)
        view_menu.addAction(self._action_settings_view)

        view_menu.addSeparator()
        self._action_swap_panes = QAction("Swap Pane Paths\tCtrl+Shift+S", self)
        self._action_swap_panes.setToolTip(
            "Swap pane paths\n\n"
            "Exchange the left and right folder paths. Shortcut: Ctrl+Shift+S."
        )
        self._action_swap_panes.triggered.connect(self._onSwapPanels)
        view_menu.addAction(self._action_swap_panes)

        view_menu.addSeparator()
        self._action_toggle_library_active = QAction("Toggle Library Browser (Active Panel)\tCtrl+Shift+L", self)
        self._action_toggle_library_active.setToolTip(
            "Library browser (active panel)\n\n"
            "Show or hide the library browser in the active panel’s slot. Shortcut: Ctrl+Shift+L."
        )
        self._action_toggle_library_active.triggered.connect(self._onToggleLibraryBrowserActive)
        view_menu.addAction(self._action_toggle_library_active)

        self._action_toggle_library_left = QAction("Toggle Library Browser (Left)", self)
        self._action_toggle_library_left.setToolTip(
            "Library browser (left)\n\nShow or hide the library browser in the left panel slot."
        )
        self._action_toggle_library_left.triggered.connect(lambda: self._toggleLibraryBrowser("left"))
        view_menu.addAction(self._action_toggle_library_left)

        self._action_toggle_library_right = QAction("Toggle Library Browser (Right)", self)
        self._action_toggle_library_right.setToolTip(
            "Library browser (right)\n\nShow or hide the library browser in the right panel slot."
        )
        self._action_toggle_library_right.triggered.connect(lambda: self._toggleLibraryBrowser("right"))
        view_menu.addAction(self._action_toggle_library_right)

        view_menu.addSeparator()
        self._action_mirror = QAction("Mirror\tCtrl+Shift+M", self)
        self._action_mirror.triggered.connect(self._onMirrorToOther)
        view_menu.addAction(self._action_mirror)

        # --- Bookmarks Menu ---
        self._bookmarks_menu = menu_bar.addMenu("&Bookmarks")
        self._rebuildBookmarksMenu()

        # --- Libraries Menu ---
        libraries_menu = menu_bar.addMenu("&Libraries")

        self._action_add_library_root = QAction("Add Current Folder To Library...", self)
        self._action_add_library_root.setToolTip(
            "Add current folder to library\n\n"
            "Register the active panel’s folder as a library root for tagging and search."
        )
        self._action_add_library_root.triggered.connect(self._onAddCurrentFolderToLibrary)
        libraries_menu.addAction(self._action_add_library_root)

        self._action_assign_current_folder_tags = QAction("Assign Tags To Current Folder...", self)
        self._action_assign_current_folder_tags.setToolTip(
            "Assign tags to current folder\n\n"
            "Edit tags for the folder shown in the active panel."
        )
        self._action_assign_current_folder_tags.triggered.connect(self._onAssignCurrentFolderTags)
        libraries_menu.addAction(self._action_assign_current_folder_tags)

        libraries_menu.addSeparator()

        self._action_scan_libraries = QAction("Scan Library Roots", self)
        self._action_scan_libraries.setToolTip(
            "Scan library roots\n\nRescan indexed folders under each library root."
        )
        self._action_scan_libraries.triggered.connect(self._onScanLibraries)
        libraries_menu.addAction(self._action_scan_libraries)

        # --- Help Menu ---
        help_menu = menu_bar.addMenu("&Help")
        self._action_check_updates = QAction("Check for Updates...", self)
        self._action_check_updates.setToolTip(
            "Check for updates\n\n"
            "Compare this version to APP_VERSION on GitHub. "
            "If GitHub is newer, you can pull and rebuild. "
            "If your version is newer, you can publish to GitHub."
        )
        self._action_check_updates.triggered.connect(
            lambda: self._startUpdateCheck(manual=True)
        )
        help_menu.addAction(self._action_check_updates)
        self._action_publish_version = QAction("Publish Version to GitHub...", self)
        self._action_publish_version.setToolTip(
            "Publish version to GitHub\n\n"
            "If this app’s APP_VERSION is newer than GitHub, commit (if needed) "
            "and push with a normal (non-force) push. Asks for credentials when required."
        )
        self._action_publish_version.triggered.connect(self._onPublishVersionToGitHub)
        help_menu.addAction(self._action_publish_version)
        help_menu.addSeparator()
        self._action_about = QAction("About", self)
        self._action_about.setToolTip(
            "About\n\nShow the application name, version, and credits."
        )
        self._action_about.triggered.connect(self._onAbout)
        help_menu.addAction(self._action_about)

    # --------------------------------------------------------
    # Method: _initToolBar
    # Purpose: Creates the main toolbar with action buttons.
    # --------------------------------------------------------
    def _initToolBar(self):
        self._toolbar = QToolBar("Main Toolbar", self)
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)
        toolbar = self._toolbar

        self._tb_copy = QAction("Copy (F6)", self)
        self._tb_copy.setToolTip(
            "Copy to other panel\n\n"
            "Copy selected items to the opposite panel. Shortcut: F6."
        )
        self._tb_copy.triggered.connect(self._onCopyToOther)
        toolbar.addAction(self._tb_copy)

        self._tb_move = QAction("Move (F7)", self)
        self._tb_move.setToolTip(
            "Move to other panel\n\n"
            "Move selected items to the opposite panel. Shortcut: F7."
        )
        self._tb_move.triggered.connect(self._onMoveToOther)
        toolbar.addAction(self._tb_move)

        self._tb_delete = QAction("Delete (F9)", self)
        self._tb_delete.setToolTip(
            "Delete\n\nDelete selected items. Shortcut: F9."
        )
        self._tb_delete.triggered.connect(self._onDelete)
        toolbar.addAction(self._tb_delete)

        toolbar.addSeparator()

        self._tb_new_folder = QAction("New Folder (F8)", self)
        self._tb_new_folder.setToolTip(
            "New folder\n\nCreate a folder in the active panel. Shortcut: F8."
        )
        self._tb_new_folder.triggered.connect(self._onNewFolder)
        toolbar.addAction(self._tb_new_folder)

        self._tb_rename = QAction("Rename (F2)", self)
        self._tb_rename.setToolTip(
            "Rename\n\nRename the selected item. Shortcut: F2."
        )
        self._tb_rename.triggered.connect(self._onRename)
        toolbar.addAction(self._tb_rename)

        self._tb_batch_rename = QAction("Batch Rename", self)
        self._tb_batch_rename.setToolTip(
            "Batch rename\n\n"
            "Rename multiple files in the current folder. Shortcut: Ctrl+M."
        )
        self._tb_batch_rename.triggered.connect(self._onBatchRename)
        toolbar.addAction(self._tb_batch_rename)

        toolbar.addSeparator()

        self._tb_bookmark = QAction("Bookmark", self)
        self._tb_bookmark.setToolTip(
            "Bookmark folder\n\n"
            "Save the active panel’s path as a bookmark. Shortcut: Ctrl+Shift+B."
        )
        self._tb_bookmark.triggered.connect(self._onAddBookmark)
        toolbar.addAction(self._tb_bookmark)

        self._tb_open_explorer = QAction("Explorer", self)
        self._tb_open_explorer.setToolTip(
            "Open in Explorer\n\n"
            "Open the active panel’s folder in the system file manager."
        )
        self._tb_open_explorer.triggered.connect(self._onOpenActivePathInExplorer)
        toolbar.addAction(self._tb_open_explorer)

        self._tb_refresh = QAction("Refresh", self)
        self._tb_refresh.setToolTip(
            "Refresh both panels\n\n"
            "Reload both panels. F5 refreshes only the active panel."
        )
        self._tb_refresh.triggered.connect(self._onRefresh)
        toolbar.addAction(self._tb_refresh)

        toolbar.addSeparator()

        self._tb_settings = QAction("Settings", self)
        self._tb_settings.setToolTip(
            "Settings\n\n"
            "Theme, icon set, font size, interface density (Compact/Normal/Comfortable), and more. "
            "Shortcut: Ctrl+,"
        )
        self._tb_settings.triggered.connect(self._onOpenSettings)
        toolbar.addAction(self._tb_settings)

    # --------------------------------------------------------
    # Method: _applyUiMetrics
    # Purpose: Apply toolbar icon size, bottom bar height, and panel metrics.
    # --------------------------------------------------------
    def _applyUiMetrics(self):
        font_size = int(self._settings.getSetting("font_size", 10))
        ui_scale = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
        metrics = getUiMetrics(font_size, ui_scale)
        self._applyToolbarAppearance(metrics)
        if hasattr(self, "_bottom_bar"):
            self._bottom_bar.setFixedHeight(metrics["bottom_bar_height"])
        if hasattr(self, "_sidebar_rail"):
            self._sidebar_rail.applyUiMetrics(metrics)
            self._syncSidebarHostSize()
        self._applyCenterStripMode()
        self._applyTabAddButtons()
        self._applyBottomBarLabels()
        self._left_panel.applyUiMetrics(metrics)
        self._right_panel.applyUiMetrics(metrics)

    # --------------------------------------------------------
    # Method: _applyToolbarAppearance
    # Purpose: Icon size and whether the toolbar shows text.
    #          The center strip and panel buttons keep their own style.
    # --------------------------------------------------------
    def _applyToolbarAppearance(self, metrics=None):
        if not hasattr(self, "_toolbar"):
            return
        if metrics is None:
            font_size = int(self._settings.getSetting("font_size", 10))
            ui_scale = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
            metrics = getUiMetrics(font_size, ui_scale)
        size_id = normalizeToolbarIconSize(
            self._settings.getSetting("toolbar_icon_size", DEFAULT_TOOLBAR_ICON_SIZE)
        )
        pixels = toolbarIconPixels(metrics["toolbar_icon"], size_id)
        self._toolbar.setIconSize(QSize(pixels, pixels))
        style_id = normalizeToolbarButtonStyle(
            self._settings.getSetting("toolbar_button_style", DEFAULT_TOOLBAR_BUTTON_STYLE)
        )
        self._toolbar.setToolButtonStyle(TOOLBAR_BUTTON_STYLES[style_id])

    # --------------------------------------------------------
    # Method: createPopupMenu
    # Purpose: The toolbar right-click menu. The window still
    #          lists the toolbar itself, then icon size and
    #          whether the buttons show text.
    # --------------------------------------------------------
    def createPopupMenu(self):
        menu = super().createPopupMenu()
        if menu is None:
            menu = QMenu(self)
        self._addToolbarAppearanceMenu(menu)
        return menu

    # --------------------------------------------------------
    # Method: _addToolbarAppearanceMenu
    # Purpose: Checkable choices for the main toolbar. The
    #          current choice is the one that is checked.
    # --------------------------------------------------------
    def _addToolbarAppearanceMenu(self, menu):
        menu.addSeparator()
        style = normalizeToolbarButtonStyle(
            self._settings.getSetting("toolbar_button_style", DEFAULT_TOOLBAR_BUTTON_STYLE)
        )
        size = normalizeToolbarIconSize(
            self._settings.getSetting("toolbar_icon_size", DEFAULT_TOOLBAR_ICON_SIZE)
        )
        style_group = QActionGroup(menu)
        style_group.setExclusive(True)
        for key, label in TOOLBAR_STYLE_LABELS:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(key == style)
            style_group.addAction(action)
            action.triggered.connect(
                lambda checked, chosen=key: self._setToolbarButtonStyle(chosen) if checked else None
            )
            menu.addAction(action)
        menu.addSeparator()
        size_group = QActionGroup(menu)
        size_group.setExclusive(True)
        for key, label in TOOLBAR_SIZE_LABELS:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(key == size)
            size_group.addAction(action)
            action.triggered.connect(
                lambda checked, chosen=key: self._setToolbarIconSize(chosen) if checked else None
            )
            menu.addAction(action)

    # --------------------------------------------------------
    # Method: _setToolbarButtonStyle
    # Purpose: Save icons-only, icons-and-text, or text-under
    #          and apply it immediately.
    # --------------------------------------------------------
    def _setToolbarButtonStyle(self, style):
        self._settings.setSetting(
            "toolbar_button_style", normalizeToolbarButtonStyle(style)
        )
        self._settings.saveSettings()
        self._applyToolbarAppearance()

    # --------------------------------------------------------
    # Method: _setToolbarIconSize
    # Purpose: Save small, medium, or large and apply it immediately.
    # --------------------------------------------------------
    def _setToolbarIconSize(self, size):
        self._settings.setSetting(
            "toolbar_icon_size", normalizeToolbarIconSize(size)
        )
        self._settings.saveSettings()
        self._applyToolbarAppearance()

    # --------------------------------------------------------
    # Method: _layoutScale
    # Purpose: The same scale theme.getUiMetrics uses, so
    #          width cut-offs follow font size and density.
    # --------------------------------------------------------
    def _layoutScale(self):
        font_size = int(self._settings.getSetting("font_size", 10))
        ui_scale = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
        return float(getUiMetrics(font_size, ui_scale).get("layout_scale", 1.0))

    # --------------------------------------------------------
    # Method: _applyCenterStripMode
    # Purpose: The middle column is only as wide as the square
    #          buttons. Names stay in the tooltips.
    # --------------------------------------------------------
    def _applyCenterStripMode(self):
        if not hasattr(self, "_center_buttons"):
            return
        font_size = int(self._settings.getSetting("font_size", 10))
        ui_scale = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
        metrics = getUiMetrics(font_size, ui_scale)
        self._applyCenterButtonSize(metrics)
        width = max(
            metrics["center_panel_width"],
            metrics["center_button_size"] + 8,
        )
        self._center_buttons.setFixedWidth(width)

    # --------------------------------------------------------
    # Method: _applyBottomBarLabels
    # Purpose: Use "F2" instead of "F2 Rename" when the full
    #          labels do not fit. Tooltips keep the long names.
    # --------------------------------------------------------
    def _applyBottomBarLabels(self):
        specs = getattr(self, "_bottom_button_specs", None)
        if not specs or not hasattr(self, "_bottom_bar"):
            return
        full = [full_text for _btn, full_text, _short in specs]
        use_short = self.width() > 1 and not self._bottomLabelsFit(full)
        for btn, full_text, short_text in specs:
            text = short_text if use_short else full_text
            if btn.text() != text:
                btn.setText(text)

    # --------------------------------------------------------
    # Method: _bottomLabelsFit
    # Purpose: True when the widest full F-key label fits one
    #          equal slot of the bottom bar.
    # --------------------------------------------------------
    def _bottomLabelsFit(self, texts):
        count = len(texts)
        if count <= 0:
            return True
        available = self._bottom_bar.width() if hasattr(self, "_bottom_bar") else 0
        if available <= 1:
            available = self.width() - 24
        if available <= 1:
            return True
        font_size = int(self._settings.getSetting("font_size", 10))
        ui_scale = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
        metrics = getUiMetrics(font_size, ui_scale)
        margins = 12
        spacing = 4 * (count - 1)
        slot = (available - margins - spacing) / count
        pad = metrics["bottom_btn_pad_h"] * 2 + 8
        widest = max(self._bottom_bar.fontMetrics().horizontalAdvance(text) for text in texts)
        return widest + pad <= slot

    # --------------------------------------------------------
    # Method: _windowIsNarrowForSidebar
    # Purpose: True when the window is below the auto-collapse
    #          cut-off. An unknown width counts as wide.
    # --------------------------------------------------------
    def _windowIsNarrowForSidebar(self):
        if self.width() <= 1:
            return False
        return self.width() < scaled(SIDEBAR_AUTO_COLLAPSE_WIDTH, self._layoutScale())

    # --------------------------------------------------------
    # Method: _sidebarShouldCollapse
    # Purpose: Collapse when the user hid it, or when the window
    #          is narrow and they have not opened it since.
    # --------------------------------------------------------
    def _sidebarShouldCollapse(self):
        narrow = self._windowIsNarrowForSidebar()
        if not narrow:
            self._sidebar_opened_while_narrow = False
        if self._sidebar_user_hidden:
            return True
        if narrow and not self._sidebar_opened_while_narrow:
            return True
        return False

    # --------------------------------------------------------
    # Method: _updateSidebarCollapse
    # Purpose: Apply the sidebar rule for the current width.
    # --------------------------------------------------------
    def _updateSidebarCollapse(self):
        if not hasattr(self, "_sidebar_host"):
            return
        self._setSidebarCollapsed(self._sidebarShouldCollapse())

    # --------------------------------------------------------
    # Method: _setSidebarCollapsed
    # Purpose: Swap the sidebar for the icon rail, or bring
    #          the sidebar back at its last width.
    # --------------------------------------------------------
    def _setSidebarCollapsed(self, collapsed):
        collapsed = bool(collapsed)
        if not hasattr(self, "_sidebar_host"):
            return
        if self._sidebar_collapse_guard:
            return
        if collapsed == self._sidebar_collapsed and self._sidebar_collapse_ready:
            self._syncSidebarAction()
            return
        self._sidebar_collapse_guard = True
        self._sidebar_collapsed = collapsed
        try:
            if collapsed:
                sizes = self._main_splitter.sizes()
                if sizes and sizes[0] >= 180:
                    self._sidebar_expanded_width = sizes[0]
                self._sidebar_tabs.setMinimumWidth(0)
                self._sidebar_tabs.hide()
                self._sidebar_rail.show()
                rail_w = max(1, self._sidebar_rail.width())
                self._sidebar_host.setMinimumWidth(rail_w)
                self._sidebar_host.setMaximumWidth(rail_w)
                total = sum(self._main_splitter.sizes()) or (rail_w + 800)
                self._main_splitter.setSizes([rail_w, max(1, total - rail_w)])
            else:
                self._sidebar_rail.hide()
                self._sidebar_tabs.setMinimumWidth(200)
                self._sidebar_tabs.show()
                self._sidebar_host.setMinimumWidth(200)
                self._sidebar_host.setMaximumWidth(16777215)
                width = max(200, int(self._sidebar_expanded_width or 260))
                sizes = self._main_splitter.sizes()
                total = sum(sizes) if sizes else 0
                if total <= width:
                    total = width + 800
                self._main_splitter.setSizes([width, max(1, total - width)])
        finally:
            self._sidebar_collapse_guard = False
            self._sidebar_collapse_ready = True
        self._syncSidebarAction()

    # --------------------------------------------------------
    # Method: _syncSidebarHostSize
    # Purpose: Keep the collapsed host the same width as the rail
    #          after icon size changes.
    # --------------------------------------------------------
    def _syncSidebarHostSize(self):
        if not getattr(self, "_sidebar_collapsed", False):
            return
        rail_w = max(1, self._sidebar_rail.width())
        self._sidebar_host.setMinimumWidth(rail_w)
        self._sidebar_host.setMaximumWidth(rail_w)

    # --------------------------------------------------------
    # Method: _syncSidebarAction
    # Purpose: Keep View -> Show Sidebar matched to the sidebar.
    # --------------------------------------------------------
    def _syncSidebarAction(self):
        action = getattr(self, "_action_show_sidebar", None)
        if action is None:
            return
        visible = not self._sidebar_collapsed
        if action.isChecked() == visible:
            return
        action.blockSignals(True)
        action.setChecked(visible)
        action.blockSignals(False)

    # --------------------------------------------------------
    # Method: _onToggleSidebar
    # Purpose: View menu and Ctrl+B. An explicit hide is saved.
    #          Opening it while the window is narrow keeps it
    #          open until the window is wide again.
    # --------------------------------------------------------
    def _onToggleSidebar(self, checked):
        self._sidebar_user_hidden = not bool(checked)
        if checked and self._windowIsNarrowForSidebar():
            self._sidebar_opened_while_narrow = True
        if not checked:
            self._sidebar_opened_while_narrow = False
        self._persistSidebarVisibility()
        self._updateSidebarCollapse()

    # --------------------------------------------------------
    # Method: _onSidebarRailRequested
    # Purpose: A rail button opens the sidebar on that tab.
    # --------------------------------------------------------
    def _onSidebarRailRequested(self, index):
        self._sidebar_user_hidden = False
        if self._windowIsNarrowForSidebar():
            self._sidebar_opened_while_narrow = True
        if 0 <= index < self._sidebar_tabs.count():
            self._sidebar_tabs.setCurrentIndex(index)
        self._persistSidebarVisibility()
        self._setSidebarCollapsed(False)

    # --------------------------------------------------------
    # Method: _persistSidebarVisibility
    # Purpose: Remember an explicit show or hide. Auto-collapse
    #          does not call this.
    # --------------------------------------------------------
    def _persistSidebarVisibility(self):
        current = "libraries" if self._sidebar_tabs.currentIndex() == 1 else "bookmarks"
        self._settings.setSidebarState({
            "current_tab": current,
            "hidden": bool(self._sidebar_user_hidden),
        })
        self._settings.saveSettings()

    # --------------------------------------------------------
    # Method: _adjustUiScale
    # Purpose: Step Interface density (85/100/115) and refresh UI live.
    # --------------------------------------------------------
    def _adjustUiScale(self, direction):
        current = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
        new_scale = step_ui_scale(current, direction)
        if new_scale == current:
            return False

        self._settings.setSetting("ui_scale", new_scale)
        app = QApplication.instance()
        applyTheme(
            app,
            self._settings.getSetting("theme_mode", "dark"),
            int(self._settings.getSetting("font_size", 10)),
            new_scale,
        )
        self._applyUiMetrics()
        self._left_panel.relayoutColumns()
        self._right_panel.relayoutColumns()
        self._refreshThemedIcons()
        self._settings.saveSettings()
        self._showStatus(f"Interface density: {ui_scale_label(new_scale)}")
        return True

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and self._wheelTargetsMainWindow(obj):
            mods = QApplication.keyboardModifiers()
            if mods & Qt.ControlModifier:
                delta = event.angleDelta().y()
                if delta == 0:
                    delta = event.angleDelta().x()
                if delta != 0:
                    direction = 1 if delta > 0 else -1
                    if self._adjustUiScale(direction):
                        return True
        return super().eventFilter(obj, event)

    # --------------------------------------------------------
    # Method: _wheelTargetsMainWindow
    # Purpose: Ctrl+wheel density zoom applies only to widgets in
    #          this window, never inside dialogs or popups.
    # --------------------------------------------------------
    def _wheelTargetsMainWindow(self, obj):
        if QApplication.activeModalWidget() is not None:
            return False
        if not isinstance(obj, QWidget):
            return False
        return obj.window() is self
    # Purpose: Creates the layout: bookmarks pane | dual file panes
    #          with a center column of Copy/Move/Swap/Mirror buttons.
    #          Each panel slot is a QStackedWidget that can toggle
    #          between a FilePanel and a LibraryBrowserPanel.
    # --------------------------------------------------------
    def _initPanels(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 0)
        main_layout.setSpacing(0)

        panels_layout = QHBoxLayout()
        panels_layout.setSpacing(0)

        self._left_panel = FilePanel("left", self, settings_manager=self._settings)
        self._right_panel = FilePanel("right", self, settings_manager=self._settings)

        self._left_library_browser = LibraryBrowserPanel("left", self)
        self._right_library_browser = LibraryBrowserPanel("right", self)
        self._connectLibraryBrowser(self._left_library_browser, "left")
        self._connectLibraryBrowser(self._right_library_browser, "right")

        self._left_stack = QStackedWidget()
        self._left_stack.addWidget(self._left_panel)
        self._left_stack.addWidget(self._left_library_browser)

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._right_panel)
        self._right_stack.addWidget(self._right_library_browser)

        self._left_quick_view = FileViewerWidget()
        self._right_quick_view = FileViewerWidget()
        self._left_stack.addWidget(self._left_quick_view)
        self._right_stack.addWidget(self._right_quick_view)

        self._left_tabs = PanelTabBar(self._left_panel)
        self._right_tabs = PanelTabBar(self._right_panel)
        self._left_tabs.tabDisplayed.connect(
            lambda: self._showFilePanel("left")
        )
        self._right_tabs.tabDisplayed.connect(
            lambda: self._showFilePanel("right")
        )
        self._left_tabs.newTabRequested.connect(
            lambda: self._onNewTabFor("left")
        )
        self._right_tabs.newTabRequested.connect(
            lambda: self._onNewTabFor("right")
        )
        self._left_tabs.openInExplorerRequested.connect(self._openFolderInExplorer)
        self._right_tabs.openInExplorerRequested.connect(self._openFolderInExplorer)
        self._left_tabs.openInTerminalRequested.connect(self._openFolderInTerminal)
        self._right_tabs.openInTerminalRequested.connect(self._openFolderInTerminal)
        self._left_panel.setStateSnapshot(lambda: self._savePanelTabs("left"))
        self._right_panel.setStateSnapshot(lambda: self._savePanelTabs("right"))

        self._center_buttons = self._buildCenterButtons()

        panels_layout.addWidget(
            self._panelSideHost(self._left_tabs, self._left_stack, "left"), 1
        )
        panels_layout.addWidget(self._center_buttons)
        panels_layout.addWidget(
            self._panelSideHost(self._right_tabs, self._right_stack, "right"), 1
        )

        file_panes_widget = QWidget()
        file_panes_widget.setLayout(panels_layout)

        self._bookmarks_panel = BookmarksPanel(self._settings, self)
        self._bookmarks_panel.setCurrentPathProvider(self._getActivePanelPath)
        self._bookmarks_panel.bookmarkActivated.connect(self._onBookmarkPanelActivated)
        self._bookmarks_panel.structureChanged.connect(self._onBookmarksStructureChanged)
        self._bookmarks_panel.addCurrentFolderRequested.connect(self._onAddBookmark)

        self._libraries_panel = LibrariesPanel(self)
        self._libraries_panel.navigateRequested.connect(self._onLibraryNavigateRequested)
        self._libraries_panel.addLibraryRequested.connect(self._onAddCurrentFolderToLibrary)
        self._libraries_panel.scanLibrariesRequested.connect(self._onScanLibraries)

        self._sidebar_tabs = QTabWidget(self)
        self._sidebar_tabs.setObjectName("sidebarTabs")
        self._sidebar_tabs.addTab(self._bookmarks_panel, "Bookmarks")
        self._sidebar_tabs.addTab(self._libraries_panel, "Libraries")
        self._sidebar_tabs.setTabToolTip(
            0,
            "Bookmarks\n\nQuick access to saved folder and file shortcuts.",
        )
        self._sidebar_tabs.setTabToolTip(
            1,
            "Libraries\n\nTag-based library roots and matching folders.",
        )
        sidebar_tab_bar = self._sidebar_tabs.tabBar()
        sidebar_tab_bar.setElideMode(Qt.ElideNone)
        sidebar_tab_bar.setExpanding(False)
        sidebar_tab_bar.setUsesScrollButtons(True)
        self._sidebar_tabs.setMinimumWidth(200)

        self._sidebar_rail = SidebarRail(self)
        self._sidebar_rail.tabRequested.connect(self._onSidebarRailRequested)
        self._sidebar_rail.hide()

        self._sidebar_host = QWidget()
        sidebar_host_layout = QHBoxLayout(self._sidebar_host)
        sidebar_host_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_host_layout.setSpacing(0)
        sidebar_host_layout.addWidget(self._sidebar_rail)
        sidebar_host_layout.addWidget(self._sidebar_tabs, 1)

        self._sidebar_collapsed = False
        self._sidebar_collapse_ready = True
        self._sidebar_collapse_guard = False
        self._sidebar_user_hidden = False
        self._sidebar_opened_while_narrow = False
        self._sidebar_expanded_width = 260

        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.addWidget(self._sidebar_host)
        self._main_splitter.addWidget(file_panes_widget)

        # Prevent sidebar from collapsing to zero; file area can shrink freely.
        self._main_splitter.setCollapsible(0, False)
        self._main_splitter.setCollapsible(1, True)

        bm_width = self._settings.getState("bookmarks_panel_width")
        if bm_width and isinstance(bm_width, (int, float)) and 180 <= bm_width <= 600:
            self._sidebar_expanded_width = int(bm_width)
            self._main_splitter.setSizes([int(bm_width), 1200])
        else:
            self._main_splitter.setSizes([260, 1200])

        main_layout.addWidget(self._main_splitter, 1)

        self.setCentralWidget(central)

        self._left_panel.activated.connect(lambda: self._setActivePanel(self._left_panel))
        self._right_panel.activated.connect(lambda: self._setActivePanel(self._right_panel))
        self._left_panel.tableView().clicked.connect(lambda: self._setActivePanel(self._left_panel))
        self._right_panel.tableView().clicked.connect(lambda: self._setActivePanel(self._right_panel))

        self._left_panel.fileDoubleClicked.connect(self._onFileOpen)
        self._right_panel.fileDoubleClicked.connect(self._onFileOpen)

        self._left_panel.filesDropped.connect(self._onDroppedFiles)
        self._right_panel.filesDropped.connect(self._onDroppedFiles)

        self._left_panel.pathCopied.connect(
            lambda p: self._showStatus(f"Copied path: {p}")
        )
        self._right_panel.pathCopied.connect(
            lambda p: self._showStatus(f"Copied path: {p}")
        )

        self._left_panel.folderCreated.connect(self._onFolderCreatedFromPanel)
        self._right_panel.folderCreated.connect(self._onFolderCreatedFromPanel)

        self._left_panel.selectionChanged.connect(self._updateStatusBar)
        self._right_panel.selectionChanged.connect(self._updateStatusBar)
        self._left_panel.listingFinished.connect(self._onPanelListingFinished)
        self._right_panel.listingFinished.connect(self._onPanelListingFinished)
        self._left_panel.pathChanged.connect(self._onActivePanelPathChanged)
        self._right_panel.pathChanged.connect(self._onActivePanelPathChanged)
        self._left_panel.selectionChanged.connect(
            lambda: self._refreshQuickView(self._left_panel)
        )
        self._right_panel.selectionChanged.connect(
            lambda: self._refreshQuickView(self._right_panel)
        )

        self._left_panel.dateModifiedFormatChanged.connect(self._onDateModifiedFormatChanged)
        self._right_panel.dateModifiedFormatChanged.connect(self._onDateModifiedFormatChanged)
        self._left_panel.favoriteRequested.connect(
            lambda: self._onAddBookmark(self._left_panel)
        )
        self._right_panel.favoriteRequested.connect(
            lambda: self._onAddBookmark(self._right_panel)
        )

        self._left_panel.tableView().setContextMenuPolicy(Qt.CustomContextMenu)
        self._left_panel.tableView().customContextMenuRequested.connect(
            lambda pos: self._showContextMenu(self._left_panel, pos)
        )
        self._right_panel.tableView().setContextMenuPolicy(Qt.CustomContextMenu)
        self._right_panel.tableView().customContextMenuRequested.connect(
            lambda pos: self._showContextMenu(self._right_panel, pos)
        )

        self._setActivePanel(self._left_panel)

    # --------------------------------------------------------
    # Method: _panelSideHost
    # Purpose: Tab strip above the file / library / quick-view stack,
    #          with a "+" button at the right of that strip.
    # Input: tabs (PanelTabBar), stack (QStackedWidget), side (str)
    # Output: QWidget - The column for one panel.
    # --------------------------------------------------------
    def _panelSideHost(self, tabs, stack, side):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tab_row = QWidget()
        tab_row.setObjectName("panelTabRow")
        row = QHBoxLayout(tab_row)
        row.setContentsMargins(0, 0, 2, 0)
        row.setSpacing(0)
        # The bar itself fills the strip, so a double-click on the
        # empty part lands on PanelTabBar rather than a spacer.
        tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(tabs, 1)

        add_button = QToolButton(tab_row)
        add_button.setObjectName("panelTabAddButton")
        add_button.setText("+")
        add_button.setToolTip(
            "New tab (Ctrl+T)\n\n"
            "Open another tab on this panel's current folder."
        )
        add_button.setAutoRaise(True)
        add_button.setFocusPolicy(Qt.NoFocus)
        add_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        add_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        add_button.clicked.connect(
            lambda checked, panel_side=side: self._onNewTabFor(panel_side)
        )
        row.addWidget(add_button, 0, Qt.AlignVCenter)
        if side == "right":
            self._right_tab_add = add_button
        else:
            self._left_tab_add = add_button

        layout.addWidget(tab_row)
        layout.addWidget(stack, 1)
        return host

    # --------------------------------------------------------
    # Method: _applyTabAddButtons
    # Purpose: The "+" matches the tab height and is square, so
    #          it lines up with the folder tabs beside it.
    # --------------------------------------------------------
    def _applyTabAddButtons(self):
        pairs = (
            (getattr(self, "_left_tabs", None), getattr(self, "_left_tab_add", None)),
            (getattr(self, "_right_tabs", None), getattr(self, "_right_tab_add", None)),
        )
        for tabs, button in pairs:
            if tabs is None or button is None or tabs.count() < 1:
                continue
            height = tabs.tabSizeHint(0).height()
            if height < 16:
                height = max(16, tabs.sizeHint().height())
            button.setFixedSize(height, height)

    def _showFilePanel(self, side):
        if side == "left":
            self._left_stack.setCurrentWidget(self._left_panel)
        else:
            self._right_stack.setCurrentWidget(self._right_panel)

    def _savePanelTabs(self, side):
        tabs = self._left_tabs if side == "left" else self._right_tabs
        self._settings.setPanelState(side, tabs.exportState())
        self._settings.saveSettings()

    def _tabsForActive(self):
        if self._active_panel is self._right_panel:
            return self._right_tabs
        return self._left_tabs

    # --------------------------------------------------------
    # Method: _buildCenterButtons
    # Purpose: Creates the vertical column of directional
    #          copy/move buttons that sits between the panels.
    #          Arrows update dynamically based on active panel.
    # --------------------------------------------------------
    # --------------------------------------------------------
    # Method: _makeCenterButton
    # Purpose: One square button for the strip between the
    #          panels. Every action uses this, so Copy, Move,
    #          Special, Swap, and Mirror stay the same size.
    # --------------------------------------------------------
    def _makeCenterButton(self, tooltip):
        button = QToolButton()
        button.setObjectName("centerActionButton")
        button.setFocusPolicy(Qt.NoFocus)
        button.setAutoRaise(False)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setToolTip(tooltip)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return button

    # --------------------------------------------------------
    # Method: _addCenterGroup
    # Purpose: One square button, then a small gap before the
    #          next action. The name is the tooltip.
    # --------------------------------------------------------
    def _addCenterGroup(self, layout, button):
        layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addSpacing(8)

    # --------------------------------------------------------
    # Method: _applyCenterButtonSize
    # Purpose: Keep every center button the metric square, so
    #          font size and density change them together.
    # --------------------------------------------------------
    def _applyCenterButtonSize(self, metrics):
        buttons = getattr(self, "_center_action_buttons", None)
        if not buttons or not metrics:
            return
        size = int(metrics["center_button_size"])
        icon = max(16, size - 8)
        for button in buttons:
            button.setFixedSize(size, size)
            button.setIconSize(QSize(icon, icon))

    def _buildCenterButtons(self):
        frame = QFrame()
        frame.setObjectName("centerPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)

        layout.addStretch(1)

        self._btn_copy_dir = self._makeCenterButton(
            "Copy to other panel\n\n"
            "Copy selected items from the active panel to the opposite panel. Shortcut: F6."
        )
        self._btn_copy_dir.clicked.connect(self._onCopyToOther)
        self._addCenterGroup(layout, self._btn_copy_dir)

        self._btn_move_dir = self._makeCenterButton(
            "Move to other panel\n\n"
            "Move selected items from the active panel to the opposite panel. Shortcut: F7."
        )
        self._btn_move_dir.clicked.connect(self._onMoveToOther)
        self._addCenterGroup(layout, self._btn_move_dir)

        self._btn_special = self._makeCenterButton(
            "Special transfers\n\n"
            "Copy or move while keeping folder structure relative to the "
            "active panel’s current folder (search root). Also copy relative "
            "or full paths to the clipboard."
        )
        self._btn_special.setPopupMode(QToolButton.InstantPopup)
        special_menu = QMenu(self._btn_special)
        act_copy_struct = special_menu.addAction("Copy keeping structure")
        act_copy_struct.setToolTip(
            "Copy selected items to the other panel, recreating paths under "
            "the active panel’s current folder."
        )
        act_copy_struct.triggered.connect(self._onSpecialCopyKeepStructure)
        act_move_struct = special_menu.addAction("Move keeping structure")
        act_move_struct.setToolTip(
            "Move selected items to the other panel, recreating paths under "
            "the active panel’s current folder."
        )
        act_move_struct.triggered.connect(self._onSpecialMoveKeepStructure)
        special_menu.addSeparator()
        act_rel_paths = special_menu.addAction("Copy relative paths")
        act_rel_paths.setToolTip(
            "Copy selected paths relative to the active panel’s current folder."
        )
        act_rel_paths.triggered.connect(self._onSpecialCopyRelativePaths)
        act_full_paths = special_menu.addAction("Copy full paths")
        act_full_paths.setToolTip("Copy absolute paths of the selection.")
        act_full_paths.triggered.connect(self._onSpecialCopyFullPaths)
        special_menu.addSeparator()
        act_compare = special_menu.addAction("Compare with other panel…")
        act_compare.setToolTip(
            "Compare the selected item with the matching path (or selection) "
            "on the other panel: size, file counts, and modified time."
        )
        act_compare.triggered.connect(lambda: self._onCompareWithOtherPanel())
        self._btn_special.setMenu(special_menu)
        self._addCenterGroup(layout, self._btn_special)

        self._btn_swap = self._makeCenterButton(
            "Swap panes\n\n"
            "Exchange the left and right folder paths. Shortcut: Ctrl+Shift+S."
        )
        self._btn_swap.setText("\u21C4")
        self._btn_swap.clicked.connect(self._onSwapPanels)
        self._addCenterGroup(layout, self._btn_swap)

        self._btn_mirror = self._makeCenterButton("")
        self._btn_mirror.setText("\u21C9")
        self._btn_mirror.clicked.connect(self._onMirrorToOther)
        self._addCenterGroup(layout, self._btn_mirror)

        self._center_action_buttons = (
            self._btn_copy_dir,
            self._btn_move_dir,
            self._btn_special,
            self._btn_swap,
            self._btn_mirror,
        )

        layout.addStretch(1)

        self._updateDirectionButtons()
        return frame

    # --------------------------------------------------------
    # Method: _updateDirectionButtons
    # Purpose: Updates arrow direction on center buttons based
    #          on which panel is currently active.
    # --------------------------------------------------------
    def _updateDirectionButtons(self):
        if self._active_panel == self._left_panel:
            arrow = "\u2192"
            flow = "Left \u2192 Right"
            other = "right"
        else:
            arrow = "\u2190"
            flow = "Right \u2192 Left"
            other = "left"
        self._setCenterIcon(self._btn_copy_dir, "copy", arrow)
        self._setCenterIcon(self._btn_move_dir, "move", arrow)
        self._btn_copy_dir.setToolTip(
            "Copy to other panel\n\n"
            f"Copy selected items to the {other} panel. Flow: {flow}. Shortcut: F6."
        )
        self._btn_move_dir.setToolTip(
            "Move to other panel\n\n"
            f"Move selected items to the {other} panel. Flow: {flow}. Shortcut: F7."
        )
        if hasattr(self, "_btn_special"):
            self._setCenterIcon(self._btn_special, "special", arrow)
            self._btn_special.setToolTip(
                "Special transfers\n\n"
                f"Copy or move keeping structure to the {other} panel "
                f"(Flow: {flow}), or copy relative/full paths to the clipboard."
            )
        self._setCenterIcon(self._btn_swap, "swap", "\u21C4")
        self._setCenterIcon(self._btn_mirror, "mirror", "\u21C9")

    # --------------------------------------------------------
    # Method: _setCenterIcon
    # Purpose: Draw the action icon, flipped when the arrow
    #          points left. The text arrow remains if the
    #          sheet did not load.
    # --------------------------------------------------------
    def _setCenterIcon(self, button, action_id, fallback):
        from action_icons import iconForAction

        point_left = self._active_panel is self._right_panel
        directional = action_id in ("copy", "move", "special")
        icon = iconForAction(action_id, mirrored=directional and point_left)
        if icon.isNull():
            button.setText(fallback)
            return
        button.setIcon(icon)
        button.setText("")
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)

    # --------------------------------------------------------
    # Method: _initTransfers
    # Purpose: Non-blocking file transfer queue with a compact
    #          bottom row and optional details popup.
    # --------------------------------------------------------
    def _initTransfers(self):
        self._transfer_queue = FileOperationQueue(self)
        self._transfer_queue.setParentWindow(self)
        self._transfers_details = None

        self._transfers_bar = TransfersBar(self)
        self._transfers_bar.cancelButton().clicked.connect(
            self._transfer_queue.cancelActive
        )
        self._transfers_bar.detailsRequested.connect(self._showTransfersDetails)

        self._transfer_queue.taskAdded.connect(self._onTransferTaskAdded)
        self._transfer_queue.taskUpdated.connect(self._onTransferTaskUpdated)
        self._transfer_queue.taskFinished.connect(self._onTransferTaskFinished)
        self._transfer_queue.queueIdle.connect(self._onTransferQueueIdle)

        self.centralWidget().layout().addWidget(self._transfers_bar)

    def _showTransfersDetails(self):
        if self._transfers_details is None:
            self._transfers_details = TransfersDetailsDialog(
                self._transfer_queue, self
            )
        else:
            self._transfers_details._rebuildRows()
        self._transfers_details.show()
        self._transfers_details.raise_()
        self._transfers_details.activateWindow()

    def _onTransferTaskAdded(self, task):
        self._transfers_bar.updateFromQueue(self._transfer_queue)
        if self._transfers_details is not None and self._transfers_details.isVisible():
            self._transfers_details.onTaskAdded(task)

    def _onTransferTaskUpdated(self, task):
        self._transfers_bar.updateFromQueue(self._transfer_queue)
        if self._transfers_details is not None and self._transfers_details.isVisible():
            self._transfers_details.onTaskUpdated(task)

    def _onTransferTaskFinished(self, task, success, message):
        self._transfers_bar.updateFromQueue(self._transfer_queue)
        if self._transfers_details is not None and self._transfers_details.isVisible():
            self._transfers_details.onTaskFinished(task, success, message)
        if not success:
            self._refreshBothPanels()
            if (
                getattr(task, "operation", "") == "extract"
                and isPasswordError(message)
                and getattr(task, "archive_path", "")
            ):
                if self._promptArchivePassword(task.archive_path):
                    self._showStatus("Password saved. Run the extract again.")
                    return
            self._showStatus(message)
            return
        for panel in (self._left_panel, self._right_panel):
            result = panel.applyTransferResult(task)
            if result == "fallback":
                panel.refresh(force_rescan=True)
        self._showStatus(message)

    def _onTransferQueueIdle(self):
        self._transfers_bar.updateFromQueue(self._transfer_queue)

    def _clearClipboard(self):
        self._clipboard_paths = []
        self._clipboard_mode = None
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasUrls():
            clipboard.clear()

    # --------------------------------------------------------
    # Method: _initBottomBar
    # Purpose: Creates the Total Commander-style bottom button
    #          bar with F-key shortcuts.
    # --------------------------------------------------------
    def _initBottomBar(self):
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("bottomBar")

        layout = QHBoxLayout(self._bottom_bar)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        button_defs = [
            (
                "F2 Rename",
                self._onRename,
                "Rename\n\nRename the selected item in the active panel. Shortcut: F2.",
            ),
            (
                "F3 View",
                self._onViewFile,
                "View\n\nOpen the selected file in the built-in viewer. Shortcut: F3.",
            ),
            (
                "F4 Edit",
                self._onEditFile,
                "Edit\n\nOpen the selected file in the system editor. Shortcut: F4.",
            ),
            (
                "F5 Refresh",
                self._onRefreshActivePanel,
                "Refresh\n\nReload the listing for the active panel only. Shortcut: F5.",
            ),
            (
                "F6 Copy",
                self._onCopyToOther,
                "Copy\n\nCopy selected items to the opposite panel. Shortcut: F6.",
            ),
            (
                "F7 Move",
                self._onMoveToOther,
                "Move\n\nMove selected items to the opposite panel. Shortcut: F7.",
            ),
            (
                "F8 NewFolder",
                self._onNewFolder,
                "New folder\n\nCreate a folder in the active panel. Shortcut: F8.",
            ),
            (
                "F9 Delete",
                self._onDelete,
                "Delete\n\nDelete selected items. Shortcut: F9.",
            ),
        ]

        self._bottom_button_specs = []
        for text, callback, tip in button_defs:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(callback)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            short = text.split(" ", 1)[0]
            self._bottom_button_specs.append((btn, text, short))
            layout.addWidget(btn, 1)

        self.centralWidget().layout().addWidget(self._bottom_bar)

    # --------------------------------------------------------
    # Method: _initStatusBar
    # --------------------------------------------------------
    def _initStatusBar(self):
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_info = QLabel("Ready")
        self._status_info.setObjectName("statusLabel")
        self._status_bar.addWidget(self._status_info, 1)

        self._drive_space_label = QLabel("")
        self._drive_space_label.setObjectName("statusLabel")
        self._status_bar.addPermanentWidget(self._drive_space_label)

        self._version_label = QLabel(f"v{APP_VERSION}")
        self._version_label.setObjectName("statusLabel")
        self._version_label.setToolTip(f"{APP_NAME} {APP_VERSION}")
        self._status_bar.addPermanentWidget(self._version_label)

    # --------------------------------------------------------
    # Method: _initShortcuts
    # Purpose: Registers all keyboard shortcuts.
    # --------------------------------------------------------
    def _initShortcuts(self):
        shortcuts = {
            QKeySequence(Qt.Key_F2):                     self._onRename,
            QKeySequence(Qt.Key_F3):                     self._onViewFile,
            QKeySequence(Qt.Key_F4):                     self._onEditFile,
            QKeySequence(Qt.Key_F5):                     self._onRefreshActivePanel,
            QKeySequence(Qt.Key_F6):                     self._onCopyToOther,
            QKeySequence(Qt.Key_F7):                     self._onMoveToOther,
            QKeySequence(Qt.Key_F8):                     self._onNewFolder,
            QKeySequence(Qt.Key_F9):                     self._onDelete,
            QKeySequence(Qt.Key_Delete):                  self._onDelete,
            QKeySequence(Qt.Key_Return):                  self._onEnterPressed,
            QKeySequence(Qt.Key_Backspace):               self._onBackspace,
            QKeySequence("Ctrl+L"):                       self._onFocusAddressBar,
            QKeySequence(Qt.Key_Tab):                     self._onSwitchPanel,
            QKeySequence("Ctrl+A"):                       self._onSelectAll,
            QKeySequence("Ctrl+Shift+B"):                 self._onAddBookmark,
            QKeySequence("Ctrl+X"):                       self._onCut,
            QKeySequence("Ctrl+C"):                       self._onCopyToClipboard,
            QKeySequence("Ctrl+V"):                       self._onPaste,
            QKeySequence("Ctrl+M"):                       self._onBatchRename,
            QKeySequence("Ctrl+Shift+S"):                 self._onSwapPanels,
            QKeySequence("Ctrl+Shift+L"):                 self._onToggleLibraryBrowserActive,
            QKeySequence("Ctrl+Shift+M"):                 self._onMirrorToOther,
            QKeySequence("Ctrl+Q"):                       self._onToggleQuickView,
            QKeySequence("Ctrl+T"):                       self._onNewTab,
            QKeySequence("Ctrl+W"):                       self._onCloseTab,
            QKeySequence("Ctrl+Tab"):                     self._onNextTab,
            QKeySequence("Ctrl+Shift+Tab"):               self._onPreviousTab,
            QKeySequence("Ctrl+,"):                       self._onOpenSettings,
        }

        for key_seq, callback in shortcuts.items():
            action = QAction(self)
            action.setShortcut(key_seq)
            action.setShortcutContext(Qt.WindowShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    # --------------------------------------------------------
    # Method: _panelMovedSinceStartup
    # Purpose: True when the user opened another folder in this
    #          panel before the deferred state restore ran.
    # --------------------------------------------------------
    @staticmethod
    def _panelMovedSinceStartup(panel, home):
        current = panel.currentPath()
        if not current:
            return False
        return os.path.normcase(os.path.normpath(current)) != os.path.normcase(
            os.path.normpath(home)
        )

    # --------------------------------------------------------
    # Method: _restoreState
    # Purpose: Loads saved panel paths from state.json and
    #          navigates both panels to their last location.
    # --------------------------------------------------------
    def _restoreState(self):
        home = os.path.expanduser("~")

        left_state = self._settings.getPanelState("left")
        right_state = self._settings.getPanelState("right")

        saved_left = activeTabRecord(left_state).get("current_path", "") or ""
        saved_right = activeTabRecord(right_state).get("current_path", "") or ""
        if not isinstance(saved_left, str):
            saved_left = ""
        if not isinstance(saved_right, str):
            saved_right = ""
        left_path = saved_left or self._settings.getSetting("default_left_path", "") or home
        right_path = saved_right or self._settings.getSetting("default_right_path", "") or home

        if not isNavigablePath(left_path):
            left_path = home
        if not isNavigablePath(right_path):
            right_path = home

        # Home is shown before this runs, so currentPath() is already set.
        # A panel the user already navigated away from home keeps that folder.
        # Otherwise apply defaults when the saved folder is missing, not only when empty.
        for panel, tabs, state, saved, fallback in (
            (self._left_panel, self._left_tabs, left_state, saved_left, left_path),
            (self._right_panel, self._right_tabs, right_state, saved_right, right_path),
        ):
            if self._panelMovedSinceStartup(panel, home):
                continue
            tabs.importState(state)
            if not isNavigablePath(saved):
                panel.navigateTo(fallback)

        fallback_widths = self._settings.getSetting("column_widths", {})
        if fallback_widths and not activeTabRecord(left_state).get("column_widths"):
            self._left_panel.applyColumnWidths(fallback_widths)
        if fallback_widths and not activeTabRecord(right_state).get("column_widths"):
            self._right_panel.applyColumnWidths(fallback_widths)

        show_hidden = self._settings.getSetting("show_hidden_files", False)
        self._left_panel.setShowHidden(show_hidden)
        self._right_panel.setShowHidden(show_hidden)

        date_fmt = resolve_date_modified_format_key(
            self._settings.getSetting("date_modified_format", DEFAULT_DATE_MODIFIED_FORMAT)
        )
        self._left_panel.applyDateModifiedFormat(date_fmt, persist=False)
        self._right_panel.applyDateModifiedFormat(date_fmt, persist=False)

        sidebar_state = self._settings.getSidebarState()
        current_tab = sidebar_state.get("current_tab", "bookmarks")
        if current_tab == "libraries":
            self._sidebar_tabs.setCurrentIndex(1)
        else:
            self._sidebar_tabs.setCurrentIndex(0)
        self._sidebar_user_hidden = bool(sidebar_state.get("hidden", False))
        self._updateSidebarCollapse()

        QTimer.singleShot(200, self._deferredLibraryRefresh)

    # --------------------------------------------------------
    # Method: _deferredLibraryRefresh
    # Purpose: Runs library marker scans after panel paths restore
    #          so drive scans never block the first paint.
    # --------------------------------------------------------
    def _deferredLibraryRefresh(self):
        self._library_manager.refreshLibraries()
        self._reloadLibrariesPanel()

    # --------------------------------------------------------
    # Active Panel Management
    # --------------------------------------------------------
    def _setActivePanel(self, panel):
        if self._active_panel == panel:
            return
        if self._active_panel:
            self._active_panel.setActive(False)
        self._active_panel = panel
        panel.setActive(True)
        self._updateStatusBar()
        self._refreshDriveSpace()
        if hasattr(self, "_btn_copy_dir"):
            self._updateDirectionButtons()

    def _getInactivePanel(self):
        if self._active_panel == self._left_panel:
            return self._right_panel
        return self._left_panel

    # --------------------------------------------------------
    # Method: _activePanelReady
    # Purpose: True when the active file panel is on screen. While
    #          the library browser covers it, file actions would hit
    #          a hidden selection, so they are refused instead.
    # --------------------------------------------------------
    def _activePanelReady(self):
        if not self._active_panel:
            return False
        stack = self._left_stack if self._active_panel == self._left_panel else self._right_stack
        if stack.currentWidget() is not self._active_panel:
            self._showStatus("Switch back to the file panel to work with files.")
            return False
        return True

    # --------------------------------------------------------
    # Swap pane paths: left <-> right
    # --------------------------------------------------------
    def _onSwapPanels(self):
        left_path = self._left_panel.currentPath()
        right_path = self._right_panel.currentPath()
        if not left_path or not right_path:
            return
        self._left_panel.navigateTo(right_path)
        self._right_panel.navigateTo(left_path)
        self._showStatus("Panes swapped.")

    # --------------------------------------------------------
    # Archives: browse is read-only. Extract and compress go
    # through the same transfer queue as copy and move.
    # --------------------------------------------------------
    def _require7z(self):
        if find7zExecutable():
            return True
        QMessageBox.information(self, "Archives", missing7zHint())
        return False

    def _promptArchivePassword(self, archive_path):
        """Ask once. Cancel is remembered until a later extract asks again."""
        if not archive_path:
            return False
        name = os.path.basename(archive_path)
        text, ok = QInputDialog.getText(
            self,
            "Password",
            f"Password for {name}:",
            QLineEdit.Password,
        )
        key = os.path.normcase(os.path.normpath(archive_path))
        if not ok:
            self._password_declined.add(key)
            return False
        setArchivePassword(archive_path, text)
        self._password_declined.discard(key)
        return True

    def _offerArchivePassword(self, panel):
        """After a listing, ask when the archive itself is encrypted
        or a member is marked encrypted. A cancelled prompt is not repeated
        until an extract fails."""
        current = panel.currentPath() or ""
        split = splitArchivePath(current)
        if not split:
            return
        archive_path = split[0]
        error = panel.sourceModel().loadError()
        failed = isPasswordError(error)
        encrypted_member = False
        if not failed and not getArchivePassword(archive_path):
            model = panel.sourceModel()
            for row in range(model.rowCount()):
                entry = model.entryAt(row)
                if entry and entry.get("encrypted"):
                    encrypted_member = True
                    break
        if not failed and not encrypted_member:
            return
        key = os.path.normcase(os.path.normpath(archive_path))
        if not failed and key in self._password_declined:
            return
        if not self._promptArchivePassword(archive_path):
            return
        if failed:
            panel.refresh(force_rescan=True)

    def _queueExtract(self, archive_path, destination, members, on_success=None):
        if not archive_path or not destination:
            self._showStatus("No destination folder.")
            return
        if splitArchivePath(destination):
            self._showStatus("Archive is read-only.")
            return
        if not self._require7z():
            return
        self._transfer_queue.enqueueExtract(
            archive_path,
            destination,
            members=members,
            password=getArchivePassword(archive_path),
            on_success=on_success,
        )
        if members:
            self._showStatus(f"Extract queued ({len(members)} item(s)).")
        else:
            self._showStatus("Extract queued.")

    def _extractMembers(self, paths, destination):
        """Extract panel paths that point inside one archive."""
        if not destination or splitArchivePath(destination):
            self._showStatus("Archive is read-only.")
            return
        if not os.path.isdir(destination):
            self._showStatus("No destination folder.")
            return
        groups = {}
        for path in paths:
            split = splitArchivePath(path)
            if not split or not split[1]:
                continue
            groups.setdefault(split[0], []).append(split[1])
        if not groups:
            self._showStatus("Nothing to extract.")
            return
        if len(groups) > 1:
            self._showStatus("Select items from one archive at a time.")
            return
        archive_path, members = next(iter(groups.items()))
        self._queueExtract(archive_path, destination, members)

    def _extractSelectionTo(self, destination):
        if not self._active_panel or not self._active_panel.isInArchive():
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        self._extractMembers(paths, destination)

    def _extractArchiveTo(self, archive_path, destination):
        if not isArchiveFile(archive_path):
            self._showStatus("Not an archive.")
            return
        self._queueExtract(archive_path, destination, None)

    def _openArchiveMember(self, entry):
        archive_path = entry.get("archive_path") or ""
        member = (entry.get("member") or "").replace("\\", "/")
        if not archive_path or not member:
            self._showStatus("Nothing to open.")
            return
        if entry.get("encrypted") and not getArchivePassword(archive_path):
            if not self._promptArchivePassword(archive_path):
                self._showStatus("Archive is encrypted.")
                return
        dest = os.path.join(archiveCacheDir(), "open-" + uuid.uuid4().hex[:12])
        base_name = os.path.basename(member)

        def _open_extracted():
            extracted = os.path.join(dest, base_name)
            if not os.path.exists(extracted):
                self._showStatus("Could not open the extracted file.")
                return
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(extracted))
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"Could not open file:\n{exc}")

        self._queueExtract(archive_path, dest, [member], on_success=_open_extracted)

    def _onCompress(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        if not self._require7z():
            return
        other = self._getInactivePanel()
        dialog = CompressDialog(
            paths,
            self._active_panel.currentPath(),
            other.currentPath() if other else "",
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        chosen = dialog.values()
        target = chosen["archive_path"]
        if chosen.get("replace") and os.path.lexists(target):
            try:
                if os.path.isdir(target):
                    QMessageBox.warning(
                        self,
                        "Compress",
                        "A folder with that name already exists.",
                    )
                    return
                os.remove(target)
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    "Compress",
                    f"Could not replace the existing file:\n{exc}",
                )
                return
        self._transfer_queue.enqueueCompress(
            paths,
            target,
            chosen["format"],
            chosen["level"],
            password=chosen.get("password") or "",
            base_dir=chosen.get("base_dir") or self._active_panel.currentPath(),
        )
        self._showStatus(f"Compress queued ({len(paths)} item(s)).")

    # --------------------------------------------------------
    # File Operation Handlers
    # --------------------------------------------------------
    def _onCopyToOther(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            dest = self._getInactivePanel().currentPath()
            self._extractSelectionTo(dest)
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        dest = self._getInactivePanel().currentPath()
        if not dest:
            self._showStatus("No destination panel.")
            return
        if splitArchivePath(dest):
            self._showStatus("Archive is read-only.")
            return

        self._transfer_queue.enqueueCopy(paths, dest)
        self._showStatus(f"Copy queued ({len(paths)} item(s)).")

    def _onMoveToOther(self):
        if not self._activePanelReady():
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        if self._active_panel.isInArchive() or any(pathInsideArchive(p) for p in paths):
            self._showStatus("Archive is read-only.")
            return
        dest = self._getInactivePanel().currentPath()
        if not dest:
            self._showStatus("No destination panel.")
            return
        if splitArchivePath(dest):
            self._showStatus("Archive is read-only.")
            return

        self._transfer_queue.enqueueMove(paths, dest)
        self._showStatus(f"Move queued ({len(paths)} item(s)).")

    # --------------------------------------------------------
    # Special transfers (keep structure relative to search root)
    # --------------------------------------------------------
    def _prepareStructureTransfer(self, verb):
        """Return (paths, rels, dest) or (None, None, None) after UI feedback."""
        if not self._activePanelReady():
            return None, None, None
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return None, None, None
        specs, err = self._active_panel.selectedTransferSpecs()
        if err or not specs:
            self._showStatus(err or "No files selected.")
            if err and "outside" in err.lower():
                QMessageBox.warning(self, f"{verb} keeping structure", err)
            return None, None, None
        dest = self._getInactivePanel().currentPath()
        if not dest:
            self._showStatus("No destination panel.")
            return None, None, None
        if splitArchivePath(dest):
            self._showStatus("Archive is read-only.")
            return None, None, None
        root = self._active_panel.currentPath() or ""
        paths = [s["full_path"] for s in specs]
        rels = [s["relative_path"] for s in specs]
        sample = rels[0]
        extra = f"\n… and {len(rels) - 1} more" if len(rels) > 1 else ""
        reply = QMessageBox.question(
            self,
            f"{verb} keeping structure",
            f"{verb} {len(paths)} item(s) to the other panel while keeping "
            f"paths relative to:\n{root}\n\n"
            f"Example:\n  {sample}\n"
            f"  → {os.path.join(dest, sample)}{extra}\n\n"
            "Only selected items are transferred; unmatched siblings are not copied.\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return None, None, None
        return paths, rels, dest

    def _onSpecialCopyKeepStructure(self):
        paths, rels, dest = self._prepareStructureTransfer("Copy")
        if not paths:
            return
        self._transfer_queue.enqueueCopy(paths, dest, relative_paths=rels)
        self._showStatus(f"Copy (structure) queued ({len(paths)} item(s)).")

    def _onSpecialMoveKeepStructure(self):
        paths, rels, dest = self._prepareStructureTransfer("Move")
        if not paths:
            return
        self._transfer_queue.enqueueMove(paths, dest, relative_paths=rels)
        self._showStatus(f"Move (structure) queued ({len(paths)} item(s)).")

    def _onSpecialCopyRelativePaths(self):
        if not self._active_panel:
            return
        specs, err = self._active_panel.selectedTransferSpecs()
        if err or not specs:
            self._showStatus(err or "No files selected.")
            return
        text = "\n".join(s["relative_path"] for s in specs)
        QApplication.clipboard().setText(text)
        self._showStatus(f"Copied {len(specs)} relative path(s).")

    def _onSpecialCopyFullPaths(self):
        if not self._active_panel:
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        QApplication.clipboard().setText("\n".join(paths))
        self._showStatus(f"Copied {len(paths)} full path(s).")

    # --------------------------------------------------------
    # Method: _onCompareWithOtherPanel
    # Purpose: Open side-by-side compare for active selection vs
    #          counterpart under the other panel (or its selection).
    # --------------------------------------------------------
    def _onCompareWithOtherPanel(self, panel=None):
        from compare_paths_dialog import ComparePathsDialog

        active = panel or self._active_panel
        if not active:
            return
        self._setActivePanel(active)
        entries = active.selectedEntries()
        if not entries:
            self._showStatus("Select an item to compare.")
            return
        if len(entries) > 1:
            self._showStatus("Select a single item to compare.")
            return

        entry = entries[0]
        left_path = entry.get("full_path") or ""
        other = self._getInactivePanel()
        other_root = other.currentPath() if other else ""
        right_path = ""

        # Prefer same relative path under the other panel's root.
        rel = ""
        if active.sourceModel().isRecursive():
            rel = (entry.get("name") or "").replace("/", os.sep).strip()
        if not rel:
            try:
                root = active.currentPath() or ""
                if root and left_path:
                    rel = os.path.relpath(left_path, root).replace("/", os.sep)
                    if rel.startswith(".." + os.sep) or rel == "..":
                        rel = ""
            except ValueError:
                rel = ""
        if other_root and rel and rel not in (".", ""):
            parts = [p for p in rel.split(os.sep) if p and p != "."]
            if parts and ".." not in parts:
                right_path = os.path.normpath(os.path.join(other_root, *parts))

        # Fall back to other panel's single selection.
        if not right_path or not os.path.lexists(right_path):
            other_entries = other.selectedEntries() if other else []
            if len(other_entries) == 1:
                right_path = other_entries[0].get("full_path") or right_path

        if not right_path:
            QMessageBox.information(
                self,
                "Compare with other panel",
                "Could not resolve a counterpart on the other panel.\n\n"
                "Open the matching folder on the other side (same relative path "
                "under that panel’s root), or select one item there to compare.",
            )
            return

        dlg = ComparePathsDialog(
            left_path,
            right_path,
            left_title="Active panel",
            right_title="Other panel",
            parent=self,
        )
        dlg.exec_()

    def _onDelete(self):
        if not self._activePanelReady() or self._active_panel.isRenaming():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return

        confirm = self._settings.getSetting("confirm_delete", True)
        if confirm:
            names = "\n".join(os.path.basename(p) for p in paths[:10])
            if len(paths) > 10:
                names += f"\n... and {len(paths) - 10} more"
            reply = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Are you sure you want to delete {len(paths)} item(s)?\n\n{names}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self._showStatus("Delete cancelled.")
                return

        self._transfer_queue.enqueueDelete(paths)
        self._showStatus(f"Delete queued ({len(paths)} item(s)).")

    def _onRename(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return
        if self._active_panel.isRenaming():
            return
        self._active_panel.startRename()

    def _onFolderCreatedFromPanel(self, folder_name):
        self._showStatus(f"Created folder: {folder_name}")

    def _onNewFolder(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return
        self._active_panel.createNewFolder()

    # --------------------------------------------------------
    # Batch Rename: Opens the multi-rename dialog.
    # If files are selected, operates on selection only.
    # Otherwise operates on the rows currently visible in the panel.
    # --------------------------------------------------------
    def _onBatchRename(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return
        current_dir = self._active_panel.currentPath()
        if not current_dir:
            return

        entries = self._active_panel.selectedEntries()
        if not entries:
            proxy = self._active_panel.proxyModel()
            model = self._active_panel.sourceModel()
            entries = []
            for row in range(proxy.rowCount()):
                source_index = proxy.mapToSource(proxy.index(row, 0))
                entry = model.entryAt(source_index.row())
                if entry is not None:
                    entries.append(entry)

        if not entries:
            self._showStatus("No files to rename.")
            return

        dialog = BatchRenameDialog(entries, current_dir, self)
        if dialog.exec_() == QDialog.Accepted:
            self._refreshBothPanels()
            self._showStatus(f"Batch rename complete.")

    # --------------------------------------------------------
    # F5: Refresh active panel only (Explorer-style)
    # --------------------------------------------------------
    def _onRefreshActivePanel(self):
        if not self._active_panel:
            return
        self._active_panel.refresh()
        self._showStatus("Refreshed.")

    # --------------------------------------------------------
    # Enter Key: If renaming, commit the rename. Otherwise
    # open the file or navigate into the folder.
    # --------------------------------------------------------
    def _onEnterPressed(self):
        if not self._active_panel:
            return
        if self._active_panel.isRenaming():
            self._active_panel.commitRename()
            return
        entries = self._active_panel.selectedEntries()
        if len(entries) == 1:
            entry = entries[0]
            if entry["is_dir"]:
                self._active_panel.navigateTo(entry["full_path"])
            elif isArchiveFile(entry.get("full_path")) and not entry.get("in_archive"):
                if find7zExecutable():
                    self._active_panel.navigateTo(entry["full_path"])
                else:
                    self._onFileOpen(entry)
            else:
                self._onFileOpen(entry)

    # --------------------------------------------------------
    # Open file with system default application
    # --------------------------------------------------------
    def _onFileOpen(self, entry):
        if entry.get("in_archive"):
            self._openArchiveMember(entry)
            return
        path = entry.get("full_path") or ""
        if isArchiveFile(path) and not find7zExecutable():
            QMessageBox.information(self, "Archives", missing7zHint())
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{e}")

    # --------------------------------------------------------
    # Method: _onViewFile
    # Purpose: F3. Open the built-in viewer for the selected file.
    # --------------------------------------------------------
    def _onViewFile(self):
        if not self._activePanelReady():
            return
        entry = self._active_panel.primaryFileEntry()
        if (
            entry
            and entry.get("in_archive")
            and entry.get("encrypted")
            and not getArchivePassword(entry.get("archive_path") or "")
        ):
            if not self._promptArchivePassword(entry.get("archive_path") or ""):
                self._showStatus("Archive is encrypted.")
                return
        if self._viewer_window is None:
            self._viewer_window = FileViewerWindow(self)
        self._viewer_window.viewPanelFile(self._active_panel)

    # --------------------------------------------------------
    # Method: _onEditFile
    # Purpose: F4. Open the selected file in the system editor.
    # --------------------------------------------------------
    def _onEditFile(self):
        if not self._activePanelReady():
            return
        entry = self._active_panel.primaryFileEntry()
        if entry is None:
            self._showStatus("Select a file to edit.")
            return
        if entry.get("in_archive") or pathInsideArchive(entry.get("full_path")):
            self._showStatus("Archive is read-only. Extract the file first.")
            return
        ok, message = openInSystemEditor(entry["full_path"])
        if not ok:
            QMessageBox.warning(self, "Edit", message or "Could not open the editor.")

    # --------------------------------------------------------
    # Method: _onToggleQuickView
    # Purpose: Ctrl+Q. Show the active panel's file in the
    #          other panel, or hide quick view if it is on.
    # --------------------------------------------------------
    def _onToggleQuickView(self):
        if not self._active_panel:
            return
        left_on = self._left_stack.currentWidget() is self._left_quick_view
        right_on = self._right_stack.currentWidget() is self._right_quick_view
        if left_on or right_on:
            if left_on:
                self._left_stack.setCurrentWidget(self._left_panel)
            if right_on:
                self._right_stack.setCurrentWidget(self._right_panel)
            self._showStatus("Quick view off.")
            return

        other = self._getInactivePanel()
        stack = self._left_stack if other is self._left_panel else self._right_stack
        viewer = self._left_quick_view if other is self._left_panel else self._right_quick_view
        stack.setCurrentWidget(viewer)
        self._refreshQuickView(self._active_panel)
        self._showStatus("Quick view on. Ctrl+Q hides it.")

    # --------------------------------------------------------
    # Method: _onNewTabFor
    # Purpose: Open another tab on one panel and make that panel
    #          active. The file list is shown first, so the click
    #          still works while quick view or a library is up.
    # Input: side (str) - "left" or "right".
    # --------------------------------------------------------
    def _onNewTabFor(self, side):
        if side == "right":
            panel = self._right_panel
            tabs = self._right_tabs
        else:
            side = "left"
            panel = self._left_panel
            tabs = self._left_tabs
        self._showFilePanel(side)
        self._setActivePanel(panel)
        tabs.newTab()

    # --------------------------------------------------------
    # Method: _onNewTab
    # Purpose: Ctrl+T. Another tab on the active panel's folder.
    # --------------------------------------------------------
    def _onNewTab(self):
        if self._active_panel is self._right_panel:
            side = "right"
        elif self._active_panel is self._left_panel:
            side = "left"
        else:
            return
        self._onNewTabFor(side)

    def _onCloseTab(self):
        if not self._activePanelReady():
            return
        if not self._tabsForActive().closeTab():
            self._showStatus("The last tab stays open.")

    def _onNextTab(self):
        if not self._active_panel:
            return
        self._tabsForActive().selectRelative(1)

    def _onPreviousTab(self):
        if not self._active_panel:
            return
        self._tabsForActive().selectRelative(-1)

    def _openInNewTab(self, panel, path):
        tabs = self._left_tabs if panel is self._left_panel else self._right_tabs
        side = "left" if panel is self._left_panel else "right"
        self._showFilePanel(side)
        if not tabs.openInNewTab(path):
            self._showStatus("That folder cannot be opened.")
            return
        self._setActivePanel(panel)
        self._showStatus(f"Opened in a new tab: {path}")

    # --------------------------------------------------------
    # Method: _refreshQuickView
    # Purpose: If the other panel is showing quick view, update
    #          it to the source panel's selected file.
    # --------------------------------------------------------
    def _refreshQuickView(self, source_panel):
        if source_panel is self._left_panel:
            viewer = self._right_quick_view
            stack = self._right_stack
        else:
            viewer = self._left_quick_view
            stack = self._left_stack
        if stack.currentWidget() is not viewer:
            return
        entry = source_panel.primaryFileEntry()
        if entry is None:
            viewer.clear("Select a file to preview.")
            return
        viewer.showPath(entry["full_path"])

    # --------------------------------------------------------
    # Navigation
    # --------------------------------------------------------
    def _onBackspace(self):
        if not self._activePanelReady() or self._active_panel.isRenaming():
            return
        self._active_panel.goUp()

    def _onFocusAddressBar(self):
        if self._active_panel:
            self._active_panel.pathEdit().setFocus()
            self._active_panel.pathEdit().selectAll()

    def _onSwitchPanel(self):
        if self._active_panel == self._left_panel:
            self._setActivePanel(self._right_panel)
            self._right_panel.tableView().setFocus()
        else:
            self._setActivePanel(self._left_panel)
            self._left_panel.tableView().setFocus()

    # --------------------------------------------------------
    # Clipboard Operations
    # --------------------------------------------------------
    def _onCut(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return
        self._clipboard_paths = self._active_panel.selectedPaths()
        self._clipboard_mode = "cut"
        if self._clipboard_paths:
            self._syncNativeFileClipboard()
            self._showStatus(f"Cut {len(self._clipboard_paths)} item(s)")

    def _onCopyToClipboard(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only. Use Extract to copy files out.")
            return
        self._clipboard_paths = self._active_panel.selectedPaths()
        self._clipboard_mode = "copy"
        if self._clipboard_paths:
            self._syncNativeFileClipboard()
            self._showStatus(f"Copied {len(self._clipboard_paths)} item(s) to clipboard")

    def _pathsFromOsClipboard(self):
        """
        Return (paths, mode) from the OS file clipboard (local file URLs).
        mode is 'copy' or 'cut' (Windows Explorer cut sets move → 'cut').
        Returns ([], None) if the clipboard has no usable file paths.
        """
        md = QApplication.clipboard().mimeData()
        if not md or not md.hasUrls():
            return [], None
        paths = []
        for u in md.urls():
            if u.isLocalFile():
                p = os.path.normpath(u.toLocalFile())
                if p and os.path.exists(p):
                    paths.append(p)
        if not paths:
            return [], None
        seen = set()
        uniq = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        paths = uniq

        mode = "copy"
        eff = getClipboardDropEffect()
        if eff == "move":
            mode = "cut"
        return paths, mode

    def _hasPasteSource(self):
        if self._clipboard_paths:
            return True
        paths, _ = self._pathsFromOsClipboard()
        return bool(paths)

    def _onPaste(self):
        if not self._activePanelReady():
            return
        if self._active_panel.isInArchive():
            self._showStatus("Archive is read-only.")
            return

        dest = self._active_panel.currentPath()
        if not dest:
            return

        os_paths, os_mode = self._pathsFromOsClipboard()
        if os_paths:
            if os_mode == "cut":
                self._transfer_queue.enqueueMove(
                    os_paths,
                    dest,
                    on_success=self._clearClipboard,
                    clear_clipboard_on_success=True,
                )
                self._showStatus(f"Move queued ({len(os_paths)} item(s)).")
            else:
                self._transfer_queue.enqueueCopy(os_paths, dest)
                self._showStatus(f"Copy queued ({len(os_paths)} item(s)).")
            return

        self._clipboard_paths = [p for p in self._clipboard_paths if os.path.exists(p)]
        if not self._clipboard_paths:
            self._showStatus("Nothing to paste.")
            return

        if self._clipboard_mode == "copy":
            self._transfer_queue.enqueueCopy(self._clipboard_paths, dest)
            self._showStatus(f"Copy queued ({len(self._clipboard_paths)} item(s)).")
        elif self._clipboard_mode == "cut":
            self._transfer_queue.enqueueMove(
                self._clipboard_paths,
                dest,
                on_success=self._clearClipboard,
                clear_clipboard_on_success=True,
            )
            self._showStatus(f"Move queued ({len(self._clipboard_paths)} item(s)).")
        else:
            return

    # --------------------------------------------------------
    # Method: _syncNativeFileClipboard
    # Purpose: Mirrors the app clipboard to the Windows shell
    #          clipboard so files can be pasted into Explorer.
    # --------------------------------------------------------
    def _syncNativeFileClipboard(self):
        if not self._clipboard_paths or self._clipboard_mode not in ("copy", "cut"):
            return False
        return setFileClipboard(self._clipboard_paths, self._clipboard_mode)

    # --------------------------------------------------------
    # Select All
    # --------------------------------------------------------
    def _onSelectAll(self):
        if self._active_panel:
            self._active_panel.tableView().selectAll()

    # --------------------------------------------------------
    # View
    # --------------------------------------------------------
    def _onRefresh(self):
        self._left_panel.refresh(force_rescan=True)
        self._right_panel.refresh(force_rescan=True)
        self._showStatus("Refreshed.")

    def _onToggleHidden(self, checked):
        self._settings.setSetting("show_hidden_files", checked)
        self._left_panel.setShowHidden(checked)
        self._right_panel.setShowHidden(checked)

    def _onOpenSettings(self):
        dialog = SettingsDialog(
            self._settings,
            self,
            on_theme_preview=self._previewTheme,
        )
        dialog.profileImported.connect(self._onSettingsProfileImported)
        if dialog.exec_() != QDialog.Accepted:
            return

        values = dialog.values()
        for key, value in values.items():
            self._settings.setSetting(key, value)

        self._applySettingsValues(values)
        saved = self._settings.saveSettings()
        self._updateMirrorTooltips()
        if self._warnIfSaveFailed(saved):
            self._showStatus("Settings saved.")

    # --------------------------------------------------------
    # Method: _previewTheme
    # Purpose: Paint a theme while the theme list is open.
    #          Font size and density stay as they are saved.
    # --------------------------------------------------------
    def _previewTheme(self, theme_id):
        app = QApplication.instance()
        applyTheme(
            app,
            theme_id,
            int(self._settings.getSetting("font_size", 10)),
            self._settings.getSetting("ui_scale", 100),
        )
        self._applyUiMetrics()
        self._refreshThemedIcons()

    # --------------------------------------------------------
    # Method: _applySettingsValues
    # Purpose: Apply theme/density/hidden-files from a values dict.
    # --------------------------------------------------------
    def _applySettingsValues(self, values):
        self._action_show_hidden.setChecked(values["show_hidden_files"])
        self._left_panel.setShowHidden(values["show_hidden_files"])
        self._right_panel.setShowHidden(values["show_hidden_files"])

        if "cache_recursive_scans" in values:
            from scan_cache import setScanCacheEnabled

            setScanCacheEnabled(bool(values["cache_recursive_scans"]))

        auto_refresh = bool(self._settings.getSetting("auto_refresh_panels", True))
        self._left_panel.setAutoRefreshEnabled(auto_refresh)
        self._right_panel.setAutoRefreshEnabled(auto_refresh)

        app = QApplication.instance()
        applyTheme(
            app,
            values["theme_mode"],
            int(values["font_size"]),
            values["ui_scale"],
        )
        self._applyUiMetrics()
        self._left_panel.relayoutColumns()
        self._right_panel.relayoutColumns()
        self._refreshThemedIcons()

    # --------------------------------------------------------
    # Method: _refreshThemedIcons
    # Purpose: Folders take the accent of the theme just applied.
    #          File-type pictures stay as drawn on the sheet.
    # --------------------------------------------------------
    def _refreshThemedIcons(self):
        from action_icons import applyThemeIconColors, setIconSet
        from file_icons import applyThemeAccent

        setIconSet(self._settings.getSetting("action_icon_set", "tile"))
        accent_changed = applyThemeAccent()
        applyThemeIconColors()
        self._applyToolbarIcons()
        self._updateDirectionButtons()
        if hasattr(self, "_left_panel"):
            self._left_panel.applyActionIcons()
            self._right_panel.applyActionIcons()
        if not accent_changed:
            return
        self._left_panel.refreshItemIcons()
        self._right_panel.refreshItemIcons()
        if hasattr(self, "_bookmarks_panel"):
            self._bookmarks_panel.refreshIcons()

    # --------------------------------------------------------
    # Method: _applyToolbarIcons
    # Purpose: Put the chosen action-icon set on the toolbar.
    #          Copy and Move point toward the other panel.
    # --------------------------------------------------------
    def _applyToolbarIcons(self):
        from action_icons import iconForAction

        point_left = self._active_panel is self._right_panel
        mapping = (
            (getattr(self, "_tb_copy", None), "copy", True),
            (getattr(self, "_tb_move", None), "move", True),
            (getattr(self, "_tb_delete", None), "delete", False),
            (getattr(self, "_tb_new_folder", None), "new_folder", False),
            (getattr(self, "_tb_rename", None), "rename", False),
            (getattr(self, "_tb_batch_rename", None), "batch_rename", False),
            (getattr(self, "_tb_bookmark", None), "bookmark", False),
            (getattr(self, "_tb_open_explorer", None), "reveal", False),
            (getattr(self, "_tb_refresh", None), "refresh", False),
            (getattr(self, "_tb_settings", None), "settings", False),
        )
        for action, action_id, directional in mapping:
            if action is None:
                continue
            icon = iconForAction(action_id, mirrored=directional and point_left)
            if not icon.isNull():
                action.setIcon(icon)

    # --------------------------------------------------------
    # Method: _onSettingsProfileImported
    # Purpose: Refresh UI after Import from the Settings dialog.
    # --------------------------------------------------------
    def _onSettingsProfileImported(self):
        values = {
            "theme_mode": self._settings.getSetting("theme_mode", "dark"),
            "font_size": int(self._settings.getSetting("font_size", 10)),
            "ui_scale": self._settings.getSetting("ui_scale", 100),
            "show_hidden_files": self._settings.getSetting("show_hidden_files", False),
        }
        self._applySettingsValues(values)
        self._bookmarks_panel.loadStructure()
        self._rebuildBookmarksMenu()
        self._reloadLibrariesPanel()
        for side in ("left", "right"):
            tabs = self._left_tabs if side == "left" else self._right_tabs
            panel_state = self._settings.getPanelState(side)
            if isinstance(panel_state, dict):
                tabs.importState(panel_state)
        self._updateMirrorTooltips()
        self._showStatus("Profile imported.")

    # --------------------------------------------------------
    # Bookmarks
    # --------------------------------------------------------
    def _getActivePanelPath(self):
        if self._active_panel:
            return self._active_panel.currentPath()
        return ""

    def _onAddBookmark(self, panel=None):
        # The shortcut is a QAction, so triggered passes a bool.
        if not isinstance(panel, FilePanel):
            panel = None
        target = panel if panel is not None else self._active_panel
        if target is None:
            return
        path = target.currentPath()
        if not path:
            return

        default_name = os.path.basename(path) or path
        name, ok = QInputDialog.getText(
            self, "Add Bookmark", "Bookmark name:", text=default_name
        )
        if ok and name.strip():
            self._settings.addBookmark(name.strip(), path)
            self._bookmarks_panel.loadStructure()
            self._rebuildBookmarksMenu()
            self._showStatus(f"Bookmarked: {name.strip()}")

    def _onAddFileBookmark(self, entry):
        """Add the selected file as a bookmark (double-click in bookmarks pane will run it)."""
        path = entry.get("full_path")
        if not path or not os.path.isfile(path):
            return
        default_name = entry.get("name", os.path.basename(path))
        name, ok = QInputDialog.getText(
            self, "Add File Bookmark", "Bookmark name:", text=default_name
        )
        if ok and name.strip():
            self._settings.addBookmark(name.strip(), path)
            self._bookmarks_panel.loadStructure()
            self._rebuildBookmarksMenu()
            self._showStatus(f"Bookmarked: {name.strip()}")

    def _rebuildBookmarksMenu(self):
        self._bookmarks_menu.clear()

        add_action = QAction("Add Current Folder...", self)
        add_action.setToolTip(
            "Add bookmark\n\n"
            "Save the active panel’s current folder as a named bookmark."
        )
        add_action.triggered.connect(self._onAddBookmark)
        self._bookmarks_menu.addAction(add_action)

        self._bookmarks_menu.addSeparator()

        export_action = QAction("Export Bookmarks...", self)
        export_action.setToolTip(
            "Export bookmarks\n\n"
            "Save the bookmark list to a JSON file you can keep or copy to another computer."
        )
        export_action.triggered.connect(self._onExportBookmarks)
        self._bookmarks_menu.addAction(export_action)

        import_action = QAction("Import Bookmarks...", self)
        import_action.setToolTip(
            "Import bookmarks\n\n"
            "Replace the list or merge bookmarks from a JSON file."
        )
        import_action.triggered.connect(self._onImportBookmarks)
        self._bookmarks_menu.addAction(import_action)

        self._bookmarks_menu.addSeparator()

        bookmarks = self._settings.getBookmarks()
        if not bookmarks:
            empty_action = QAction("(no bookmarks)", self)
            empty_action.setToolTip(
                "No bookmarks\n\nUse “Add Current Folder…” to create your first bookmark."
            )
            empty_action.setEnabled(False)
            self._bookmarks_menu.addAction(empty_action)
        else:
            for bm in bookmarks:
                bm_name = bm.get("name", "")
                bm_path = bm.get("path", "")
                action = QAction(f"{bm_name}  \u2192  {bm_path}", self)
                action.setToolTip(
                    "Go to bookmark\n\n"
                    f"Open this path: {bm_path}"
                )
                action.setData(bm_path)
                action.triggered.connect(self._onBookmarkClicked)
                self._bookmarks_menu.addAction(action)

            self._bookmarks_menu.addSeparator()
            manage_action = QAction("Remove a Bookmark...", self)
            manage_action.setToolTip(
                "Remove bookmark\n\nChoose a bookmark to delete from the list."
            )
            manage_action.triggered.connect(self._onRemoveBookmark)
            self._bookmarks_menu.addAction(manage_action)

    def _onBookmarkClicked(self):
        action = self.sender()
        if not action:
            return
        path = action.data()
        if not path:
            return
        if os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif os.path.isdir(path) and self._active_panel:
            self._active_panel.navigateTo(path)

    def _onBookmarkPanelActivated(self, path):
        """Navigate the active pane to the clicked bookmark path."""
        if self._active_panel and path and os.path.isdir(path):
            self._active_panel.navigateTo(path)

    def _onBookmarksStructureChanged(self, structure):
        """Persist bookmarks structure when user reorders or edits in the panel."""
        self._settings.setBookmarksStructure(structure, user_edit=True)
        self._rebuildBookmarksMenu()

    def _onExportBookmarks(self):
        if hasattr(self, "_bookmarks_panel"):
            self._bookmarks_panel.exportBookmarksInteractive()

    def _onImportBookmarks(self):
        if hasattr(self, "_bookmarks_panel"):
            self._bookmarks_panel.importBookmarksInteractive()

    def _onRemoveBookmark(self):
        bookmarks = self._settings.getBookmarks()
        if not bookmarks:
            return

        names = [f"{bm['name']} -> {bm['path']}" for bm in bookmarks]
        from PyQt5.QtWidgets import QInputDialog
        item, ok = QInputDialog.getItem(
            self, "Remove Bookmark", "Select bookmark to remove:", names, 0, False
        )
        if ok and item:
            idx = names.index(item)
            self._settings.removeBookmark(bookmarks[idx]["path"])
            self._bookmarks_panel.loadStructure()
            self._rebuildBookmarksMenu()
            self._showStatus("Bookmark removed.")

    # --------------------------------------------------------
    # Libraries / Tags
    # --------------------------------------------------------
    def _reloadLibrariesPanel(self, selected_library_id=""):
        if not selected_library_id and hasattr(self, "_libraries_panel"):
            selected_library_id = self._libraries_panel.selectedLibraryId()
        libraries = self._library_manager.getLibraries()
        tagged_folders = self._library_manager.getTaggedFolders()
        self._libraries_panel.setData(libraries, tagged_folders, selected_library_id)

        if hasattr(self, "_left_library_browser"):
            self._left_library_browser.setData(
                libraries, tagged_folders, self._left_library_browser.selectedLibraryId()
            )
        if hasattr(self, "_right_library_browser"):
            self._right_library_browser.setData(
                libraries, tagged_folders, self._right_library_browser.selectedLibraryId()
            )

    def _onScanLibraries(self):
        self._library_manager.refreshLibraries()
        self._reloadLibrariesPanel()
        self._showStatus("Library roots scanned.")

    def _onLibraryNavigateRequested(self, path):
        if not path or not os.path.isdir(path):
            self._showStatus("Selected library folder is offline or missing.")
            return
        if self._active_panel is None:
            self._setActivePanel(self._left_panel)
        self._active_panel.navigateTo(path)
        self._showStatus(f"Opened library folder: {path}")

    def _activeFolderCandidate(self):
        if not self._active_panel:
            return ""
        entries = self._active_panel.selectedEntries()
        if len(entries) == 1 and entries[0]["is_dir"]:
            return entries[0]["full_path"]
        current = self._active_panel.currentPath()
        return current if current and os.path.isdir(current) else ""

    def _promptLibraryRegistration(self, initial_root_path, initial_library_name=""):
        existing_names = [lib.get("name", "") for lib in self._library_manager.getLibraries()]
        dialog = LibraryRootDialog(
            existing_names,
            initial_root_path=initial_root_path,
            initial_library_name=initial_library_name,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return None

        values = dialog.values()
        library_name = values.get("library_name", "").strip()
        root_path = values.get("root_path", "").strip()
        if not library_name:
            QMessageBox.warning(self, "Library", "Library name is required.")
            return None
        if not root_path or not os.path.isdir(root_path):
            QMessageBox.warning(self, "Library", "Choose a valid root folder.")
            return None

        result = self._library_manager.registerLibraryRoot(
            library_name,
            root_path,
            root_name=values.get("root_name", "").strip(),
        )
        if result is None:
            QMessageBox.warning(self, "Library", "Could not register the selected library root.")
        return result

    def _onAddCurrentFolderToLibrary(self):
        folder_path = self._activeFolderCandidate()
        if not folder_path:
            QMessageBox.information(self, "Library", "Select a folder or open one in the active panel first.")
            return
        self._onAddFolderToLibrary(folder_path)

    def _onAddFolderToLibrary(self, folder_path):
        result = self._promptLibraryRegistration(folder_path)
        if result is None:
            return None
        self._reloadLibrariesPanel(result["library"]["id"])
        self._showStatus(
            f"Added root to library: {result['library'].get('name', 'Library')} -> {result['root'].get('path', '')}"
        )
        return result

    def _ensureLibraryContext(self, folder_path):
        context = self._library_manager.resolveFolderContext(folder_path)
        if context is not None:
            return context

        answer = QMessageBox.question(
            self,
            "Library required",
            "This folder is not under a known library root yet.\n\nAdd a library root now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return None

        result = self._promptLibraryRegistration(folder_path)
        if result is None:
            return None

        self._reloadLibrariesPanel(result["library"]["id"])
        return self._library_manager.resolveFolderContext(folder_path)

    def _onAssignCurrentFolderTags(self):
        folder_path = self._activeFolderCandidate()
        if not folder_path:
            QMessageBox.information(self, "Tags", "Select a folder or open one in the active panel first.")
            return
        self._onAssignFolderTags(folder_path)

    def _onAssignFolderTags(self, folder_path):
        if not folder_path or not os.path.isdir(folder_path):
            QMessageBox.warning(self, "Tags", "Choose a valid folder first.")
            return

        context = self._ensureLibraryContext(folder_path)
        if context is None:
            return

        record = self._library_manager.getFolderRecordForPath(folder_path) or {}
        known_tags = self._library_manager.getAvailableTags()
        dialog = TagAssignmentDialog(
            folder_path,
            existing_tags=record.get("tags", []),
            existing_note=record.get("note", ""),
            known_tags=known_tags,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        values = dialog.values()
        self._library_manager.assignTagsToFolder(folder_path, values.get("tags", []), values.get("note", ""))
        self._reloadLibrariesPanel(context["library"]["id"])
        self._showStatus(f"Tags updated for: {folder_path}")

    # --------------------------------------------------------
    # Library Browser Panel (full panel view)
    # --------------------------------------------------------
    def _connectLibraryBrowser(self, browser, side):
        browser.navigateRequested.connect(
            lambda path: self._onBrowserNavigateRequested(path, side)
        )
        browser.navigateInPanelRequested.connect(self._onBrowserNavigateInPanel)
        browser.switchToFilePanelRequested.connect(
            lambda: self._toggleLibraryBrowser(side)
        )
        browser.addLibraryRequested.connect(self._onAddCurrentFolderToLibrary)
        browser.scanLibrariesRequested.connect(self._onScanLibraries)
        browser.assignTagsRequested.connect(self._onAssignCurrentFolderTags)

    def _onBrowserNavigateRequested(self, path, browser_side):
        if not path or not os.path.isdir(path):
            self._showStatus("Selected folder is offline or missing.")
            return
        stack = self._left_stack if browser_side == "left" else self._right_stack
        panel = self._left_panel if browser_side == "left" else self._right_panel
        stack.setCurrentWidget(panel)
        panel.navigateTo(path)
        self._setActivePanel(panel)
        self._showStatus(f"Opened library folder: {path}")

    def _onBrowserNavigateInPanel(self, path, panel_side):
        if not path or not os.path.isdir(path):
            self._showStatus("Selected folder is offline or missing.")
            return
        panel = self._left_panel if panel_side == "left" else self._right_panel
        stack = self._left_stack if panel_side == "left" else self._right_stack
        stack.setCurrentWidget(panel)
        panel.navigateTo(path)
        self._showStatus(f"Opened library folder: {path}")

    def _onToggleLibraryBrowserActive(self):
        if self._active_panel == self._left_panel:
            self._toggleLibraryBrowser("left")
        else:
            self._toggleLibraryBrowser("right")

    def _toggleLibraryBrowser(self, side):
        stack = self._left_stack if side == "left" else self._right_stack
        browser = self._left_library_browser if side == "left" else self._right_library_browser

        if stack.currentWidget() == browser:
            file_panel = self._left_panel if side == "left" else self._right_panel
            stack.setCurrentWidget(file_panel)
            self._showStatus("Switched to file panel.")
        else:
            self._reloadLibraryBrowser(side)
            stack.setCurrentWidget(browser)
            self._showStatus("Switched to library browser.")

    def _reloadLibraryBrowser(self, side):
        browser = self._left_library_browser if side == "left" else self._right_library_browser
        libraries = self._library_manager.getLibraries()
        tagged_folders = self._library_manager.getTaggedFolders()
        selected_id = browser.selectedLibraryId()
        browser.setData(libraries, tagged_folders, selected_id)

    # --------------------------------------------------------
    # Mirror: Sync folder between panels (direction from Settings)
    # --------------------------------------------------------
    def _updateMirrorTooltips(self):
        tip = self._mirrorToolTipText()
        self._action_mirror.setToolTip(tip)
        if hasattr(self, "_btn_mirror"):
            self._btn_mirror.setToolTip(tip)

    def _mirrorToolTipText(self):
        mode = self._settings.getSetting("mirror_mode", "to_other")
        if mode == "to_active":
            body = (
                "Navigate the active panel to the inactive panel’s folder "
                "(Edit → Settings → Mirror: active follows inactive)."
            )
        else:
            body = (
                "Navigate the inactive panel to the active panel’s folder "
                "(Edit → Settings → Mirror: inactive follows active)."
            )
        return f"Mirror\n\n{body}\nShortcut: Ctrl+Shift+M."

    def _onMirrorToOther(self):
        if not self._active_panel:
            return
        mode = self._settings.getSetting("mirror_mode", "to_other")
        inactive = self._getInactivePanel()
        active = self._active_panel
        if mode == "to_active":
            source, target = inactive, active
            err = "Inactive panel has no folder to mirror."
            ok_msg = "Mirrored to active panel: {path}"
        else:
            source, target = active, inactive
            err = "Active panel has no folder to mirror."
            ok_msg = "Mirrored to other panel: {path}"
        path = source.currentPath()
        if not path or not os.path.isdir(path):
            self._showStatus(err)
            return
        target.navigateTo(path)
        self._showStatus(ok_msg.format(path=path))

    # --------------------------------------------------------
    # Right-Click Context Menu
    # --------------------------------------------------------
    def _showContextMenu(self, panel, pos):
        self._setActivePanel(panel)
        table = panel.tableView()
        index = table.indexAt(pos)

        # Right-click on a row selects it when it is not already part of
        # the selection (so Open / Explorer / Terminal target that item).
        if index.isValid():
            sm = table.selectionModel()
            if sm is not None and not sm.isSelected(index):
                table.selectRow(index.row())

        menu = QMenu(self)

        entries = panel.selectedEntries()
        has_selection = len(entries) > 0
        single_selection = len(entries) == 1
        in_archive = panel.isInArchive()

        file_entries = [e for e in entries if not e["is_dir"]]

        if single_selection:
            entry = entries[0]
            if entry["is_dir"]:
                open_label = "Open"
                open_tip = (
                    "Open\n\n"
                    "Open this folder in the current panel."
                )
            else:
                open_label = "Open File"
                open_tip = (
                    "Open file\n\n"
                    "Open this file with its default application."
                )
            open_action = menu.addAction(open_label)
            open_action.setToolTip(open_tip)
            open_action.triggered.connect(lambda: self._onContextOpen(entry))

            if (
                not entry["is_dir"]
                and not in_archive
                and isArchiveFile(entry.get("full_path"))
            ):
                archive_path = entry["full_path"]
                stem = archiveDisplayStem(archive_path)
                here = os.path.dirname(archive_path) or panel.currentPath()
                into_folder = os.path.join(here, stem) if here else stem
                other_path = self._getInactivePanel().currentPath()

                open_inside = menu.addAction("Open in Panel")
                open_inside.setToolTip(
                    "Open in panel\n\nBrowse this archive like a folder."
                )
                open_inside.triggered.connect(
                    lambda checked, path=archive_path, target=panel: target.navigateTo(path)
                )

                extract_here = menu.addAction("Extract Here")
                extract_here.setToolTip(
                    "Extract here\n\nUnpack this archive into the current folder."
                )
                extract_here.triggered.connect(
                    lambda checked, path=archive_path, dest=here: self._extractArchiveTo(path, dest)
                )

                extract_sub = menu.addAction(f"Extract to {stem}/")
                extract_sub.setToolTip(
                    "Extract to folder\n\nCreate a folder named after the archive and unpack into it."
                )
                extract_sub.triggered.connect(
                    lambda checked, path=archive_path, dest=into_folder: self._extractArchiveTo(path, dest)
                )

                extract_other = menu.addAction("Extract to Other Panel")
                extract_other.setToolTip(
                    "Extract to other panel\n\nUnpack this archive into the opposite panel."
                )
                extract_other.triggered.connect(
                    lambda checked, path=archive_path, dest=other_path: self._extractArchiveTo(path, dest)
                )

            if entry["is_dir"]:
                folder_path = entry["full_path"]

                def _open_folder_in_new_tab(checked=False, path=folder_path, target=panel):
                    self._openInNewTab(target, path)

                new_tab_action = menu.addAction("Open in New Tab")
                new_tab_action.setToolTip(
                    "Open in new tab\n\nOpen this folder in another tab on this panel."
                )
                new_tab_action.triggered.connect(_open_folder_in_new_tab)

            if not entry["is_dir"]:
                view_action = menu.addAction("View\tF3")
                view_action.setToolTip(
                    "View\n\nOpen this file in the built-in viewer. Shortcut: F3."
                )
                view_action.triggered.connect(self._onViewFile)
                edit_action = menu.addAction("Edit\tF4")
                edit_action.setToolTip(
                    "Edit\n\nOpen this file in the system editor. Shortcut: F4."
                )
                edit_action.triggered.connect(self._onEditFile)

            if not in_archive:
                reveal_action = menu.addAction("Open in File Explorer")
                reveal_action.setToolTip(
                    "Open in File Explorer\n\n"
                    "Show this item in the system file manager "
                    "(selects the file or folder in Explorer)."
                )
                reveal_action.triggered.connect(
                    lambda: self._onRevealInFileExplorer(entry)
                )

                terminal_action = menu.addAction("Open Folder in Terminal")
                terminal_action.setToolTip(
                    "Open folder in Terminal\n\n"
                    "Open a Command Prompt / terminal window in the folder "
                    "that contains this item (or in the folder itself)."
                )
                terminal_action.triggered.connect(
                    lambda: self._onOpenFolderInTerminal(entry)
                )

        if file_entries and not in_archive:
            open_with_action = menu.addAction("Open With...")
            open_with_tip = (
                "Open with\n\n"
                "Choose another application to open this file (Windows “Open with” dialog)."
            )
            if len(file_entries) > 1:
                open_with_tip += (
                    "\n\nWhen several files are selected, the dialog opens for the "
                    "first selected file."
                )
            open_with_action.setToolTip(open_with_tip)
            open_with_action.triggered.connect(
                lambda: self._onOpenWith(file_entries)
            )

        if single_selection or file_entries:
            menu.addSeparator()

        if has_selection and not in_archive:
            cut_action = menu.addAction("Cut\tCtrl+X")
            cut_action.setToolTip(
                "Cut\n\n"
                "Remove selected items and place them on the clipboard. Shortcut: Ctrl+X."
            )
            cut_action.triggered.connect(self._onCut)

            copy_action = menu.addAction("Copy\tCtrl+C")
            copy_action.setToolTip(
                "Copy\n\nCopy selected items to the clipboard. Shortcut: Ctrl+C."
            )
            copy_action.triggered.connect(self._onCopyToClipboard)

        if not in_archive:
            paste_action = menu.addAction("Paste\tCtrl+V")
            paste_action.setToolTip(
                "Paste\n\n"
                "Paste items from this app’s clipboard, or files/folders copied or cut in "
                "Explorer / Finder. Shortcut: Ctrl+V."
            )
            paste_action.triggered.connect(self._onPaste)
            paste_action.setEnabled(self._hasPasteSource())

        menu.addSeparator()

        if has_selection:
            if in_archive:
                copy_other_action = menu.addAction("Extract to Other Panel\tF6")
                copy_other_action.setToolTip(
                    "Extract to other panel\n\n"
                    "Extract the selected items into the opposite panel. Shortcut: F6."
                )
            else:
                copy_other_action = menu.addAction("Copy to Other Panel\tF6")
                copy_other_action.setToolTip(
                    "Copy to other panel\n\nCopy selected items to the opposite panel. Shortcut: F6."
                )
            copy_other_action.triggered.connect(self._onCopyToOther)

        if has_selection and not in_archive:
            move_other_action = menu.addAction("Move to Other Panel\tF7")
            move_other_action.setToolTip(
                "Move to other panel\n\nMove selected items to the opposite panel. Shortcut: F7."
            )
            move_other_action.triggered.connect(self._onMoveToOther)

            copy_struct_action = menu.addAction("Copy Keeping Structure…")
            copy_struct_action.setToolTip(
                "Copy keeping structure\n\n"
                "Copy to the other panel while recreating paths under this panel’s folder."
            )
            copy_struct_action.triggered.connect(self._onSpecialCopyKeepStructure)

            move_struct_action = menu.addAction("Move Keeping Structure…")
            move_struct_action.setToolTip(
                "Move keeping structure\n\n"
                "Move to the other panel while recreating paths under this panel’s folder."
            )
            move_struct_action.triggered.connect(self._onSpecialMoveKeepStructure)

            compare_action = menu.addAction("Compare with Other Panel…")
            compare_action.setToolTip(
                "Compare with other panel\n\n"
                "Compare this item’s path, size, and file counts with the other panel."
            )
            compare_action.triggered.connect(
                lambda: self._onCompareWithOtherPanel(panel)
            )

            menu.addSeparator()

        if single_selection and not in_archive:
            rename_action = menu.addAction("Rename\tF2")
            rename_action.setToolTip(
                "Rename\n\nRename the selected item. Shortcut: F2."
            )
            rename_action.triggered.connect(self._onRename)

        if has_selection and not in_archive:
            delete_action = menu.addAction("Delete\tF9")
            delete_action.setToolTip(
                "Delete\n\nDelete selected items. Shortcut: F9."
            )
            delete_action.triggered.connect(self._onDelete)

        if not in_archive:
            menu.addSeparator()

            new_folder_action = menu.addAction("New Folder\tF8")
            new_folder_action.setToolTip(
                "New folder\n\nCreate a folder in the current directory. Shortcut: F8."
            )
            new_folder_action.triggered.connect(self._onNewFolder)

            batch_rename_action = menu.addAction("Batch Rename...\tCtrl+M")
            batch_rename_action.setToolTip(
                "Batch rename\n\nRename multiple files using patterns. Shortcut: Ctrl+M."
            )
            batch_rename_action.triggered.connect(self._onBatchRename)

        if has_selection and not in_archive:
            compress_action = menu.addAction("Compress...")
            compress_action.setToolTip(
                "Compress\n\n"
                "Create a zip, 7z, tar, tar.gz, or tar.xz archive from the selection."
            )
            compress_action.triggered.connect(self._onCompress)

        menu.addSeparator()

        if single_selection:
            copy_path_action = menu.addAction("Copy Path to Clipboard")
            copy_path_action.setToolTip(
                "Copy path\n\nCopy the full path of this item as text."
            )
            copy_path_action.triggered.connect(
                lambda: self._copyPathToClipboard(entries[0]["full_path"])
            )

        if single_selection and entries[0]["is_dir"] and not in_archive:
            add_to_library_action = menu.addAction("Add To Library...")
            add_to_library_action.setToolTip(
                "Add to library\n\nRegister this folder as a library root."
            )
            add_to_library_action.triggered.connect(
                lambda: self._onAddFolderToLibrary(entries[0]["full_path"])
            )

            assign_tags_action = menu.addAction("Assign Tags...")
            assign_tags_action.setToolTip(
                "Assign tags\n\nEdit tags for this folder in the library system."
            )
            assign_tags_action.triggered.connect(
                lambda: self._onAssignFolderTags(entries[0]["full_path"])
            )

        if not has_selection and not in_archive:
            terminal_here_action = menu.addAction("Open Terminal Here")
            terminal_here_action.setToolTip(
                "Open terminal here\n\n"
                "Open the default terminal in this panel's current folder."
            )
            terminal_here_action.triggered.connect(
                lambda: self._onOpenFolderInTerminal(
                    {"full_path": panel.currentPath(), "is_dir": True}
                )
            )

        if not in_archive:
            bookmark_action = menu.addAction("Bookmark This Folder")
            bookmark_action.setToolTip(
                "Bookmark folder\n\nSave the current folder as a bookmark."
            )
            bookmark_action.triggered.connect(self._onAddBookmark)

        if single_selection and not entries[0]["is_dir"] and not in_archive:
            bookmark_file_action = menu.addAction("Bookmark This File")
            bookmark_file_action.setToolTip(
                "Bookmark file\n\nSave this file path as a bookmark (double-click opens it)."
            )
            bookmark_file_action.triggered.connect(
                lambda: self._onAddFileBookmark(entries[0])
            )

        if single_selection and not in_archive:
            menu.addSeparator()
            props_action = menu.addAction("Properties")
            props_action.setToolTip(
                "Properties\n\n"
                "Open a tabbed dialog: General (location, size, dates), Details (MIME, permissions), "
                "and checksums for files."
            )
            props_action.triggered.connect(lambda: self._showProperties(entries[0]))

        menu.exec_(table.viewport().mapToGlobal(pos))

    def _onContextOpen(self, entry):
        if entry["is_dir"]:
            self._active_panel.navigateTo(entry["full_path"])
        else:
            self._onFileOpen(entry)

    # --------------------------------------------------------
    # Method: _onRevealInFileExplorer
    # Purpose: Show the selected file or folder in the OS file
    #          manager (Explorer “/select”, Finder “-R”, etc.).
    # --------------------------------------------------------
    def _onRevealInFileExplorer(self, entry):
        path = entry.get("full_path") or ""
        if not path or not os.path.exists(path):
            QMessageBox.warning(
                self,
                "Open in File Explorer",
                "The selected item no longer exists.",
            )
            return
        path = os.path.normpath(path)
        try:
            system = platform.system()
            if system == "Windows":
                # /select, highlights the item; works for files and folders.
                subprocess.Popen(["explorer", "/select,", path])
            elif system == "Darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                folder = path if entry.get("is_dir") else os.path.dirname(path)
                if folder and os.path.isdir(folder):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
                else:
                    raise OSError(f"Folder not found: {folder}")
            self._showStatus(f"Opened in File Explorer: {path}")
        except Exception as e:
            QMessageBox.warning(
                self,
                "Open in File Explorer",
                f"Could not open in the file explorer:\n{e}",
            )

    # --------------------------------------------------------
    # Method: _onOpenFolderInTerminal
    # Purpose: Open a terminal / Command Prompt in the item’s
    #          folder (parent for files, the folder itself for dirs).
    # --------------------------------------------------------
    def _onOpenFolderInTerminal(self, entry):
        path = entry.get("full_path") or ""
        if entry.get("is_dir"):
            folder = path
        else:
            folder = os.path.dirname(path) if path else ""
        folder = os.path.normpath(folder) if folder else ""
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(
                self,
                "Open Folder in Terminal",
                "Could not resolve a folder for this item.",
            )
            return
        try:
            openTerminalAt(folder)
            self._showStatus(f"Opened terminal in: {folder}")
        except Exception as e:
            QMessageBox.warning(
                self,
                "Open Folder in Terminal",
                f"Could not open a terminal:\n{e}",
            )

    def _onDateModifiedFormatChanged(self, format_key):
        sender = self.sender()
        for panel in (self._left_panel, self._right_panel):
            if panel is not sender:
                panel.applyDateModifiedFormat(format_key, persist=False)

    def _onOpenWith(self, entries):
        if platform.system() != "Windows":
            QMessageBox.information(
                self,
                "Open With",
                "The “Open with” dialog is only available on Windows.",
            )
            return
        if not entries:
            return
        path = os.path.normpath(os.path.abspath(entries[0]["full_path"]))
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Open With", f"Not a file:\n{path}")
            return
        try:
            subprocess.Popen(["rundll32", "shell32.dll,OpenAs_RunDLL", path])
        except Exception as e:
            QMessageBox.warning(self, "Open With", str(e))

    def _copyPathToClipboard(self, path):
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
        self._showStatus(f"Copied path: {path}")

    # --------------------------------------------------------
    # Method: _onOpenActivePathInExplorer
    # Purpose: Opens the active panel path in the system file
    #          explorer for quick handoff to native workflows.
    # --------------------------------------------------------
    def _onOpenActivePathInExplorer(self):
        if not self._active_panel:
            return
        self._openFolderInExplorer(self._active_panel.currentPath())

    # --------------------------------------------------------
    # Method: _openFolderInExplorer
    # Purpose: Open one folder in the system file manager.
    #          A tab's right-click menu passes that tab's path.
    # --------------------------------------------------------
    def _openFolderInExplorer(self, path):
        if not path or not os.path.isdir(path):
            self._showStatus("No folder to open.")
            return

        try:
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", os.path.normpath(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            self._showStatus(f"Opened in explorer: {path}")
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                f"Could not open the folder in the file explorer:\n{e}",
            )

    # --------------------------------------------------------
    # Method: _openFolderInTerminal
    # Purpose: Open the default terminal in one folder.
    #          A tab's right-click menu passes that tab's path.
    # --------------------------------------------------------
    def _openFolderInTerminal(self, path):
        self._onOpenFolderInTerminal({"full_path": path or "", "is_dir": True})

    # --------------------------------------------------------
    # Properties Dialog
    # --------------------------------------------------------
    def _showProperties(self, entry):
        showFileProperties(entry, self)

    # --------------------------------------------------------
    # Drag-and-Drop from Panel
    # --------------------------------------------------------
    def _onDroppedFiles(self, file_paths, drop_target, is_copy):
        if splitArchivePath(drop_target):
            self._showStatus("Archive is read-only.")
            return
        inner = [path for path in file_paths if pathInsideArchive(path)]
        if inner:
            if len(inner) != len(file_paths):
                self._showStatus("Extract archive items on their own, not mixed with other files.")
                return
            if not is_copy:
                self._showStatus("Archive is read-only, so the items will be extracted.")
            self._extractMembers(inner, drop_target)
            return
        if is_copy:
            self._transfer_queue.enqueueCopy(file_paths, drop_target)
            self._showStatus(f"Copy queued ({len(file_paths)} item(s)).")
        else:
            self._transfer_queue.enqueueMove(file_paths, drop_target)
            self._showStatus(f"Move queued ({len(file_paths)} item(s)).")

    # --------------------------------------------------------
    # About Dialog
    # --------------------------------------------------------
    def _onAbout(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"{APP_NAME}\n"
            f"Version {APP_VERSION}\n\n"
            "A modern dual-pane file manager.\n\n"
            "Built with Python + PyQt5\n"
            "Dark theme inspired by Catppuccin Mocha"
        )

    # --------------------------------------------------------
    # Updates (Git remote APP_VERSION → pull + rebuild / publish)
    # --------------------------------------------------------
    def _startUpdateCheck(self, manual=False, publish_intent=False):
        if self._update_check_worker is not None and self._update_check_worker.isRunning():
            if manual or publish_intent:
                self._showStatus("Update check already running…")
            return

        self._update_check_manual = bool(manual) or bool(publish_intent)
        self._update_check_publish_intent = bool(publish_intent)
        if self._update_check_manual:
            self._showStatus(
                "Checking GitHub to publish…"
                if publish_intent
                else "Checking Git for updates…"
            )

        skip = ""
        if not self._update_check_manual:
            skip = self._settings.getSetting("skip_update_version", "") or ""

        project_root = getattr(self._settings, "_project_root", None)
        worker = UpdateCheckWorker(
            project_root,
            APP_VERSION,
            skip_version=skip,
            parent=self,
        )
        worker.resultReady.connect(self._onUpdateCheckResult)
        self._update_check_worker = worker
        worker.start()

    def _onPublishVersionToGitHub(self):
        self._startUpdateCheck(manual=True, publish_intent=True)

    def _onUpdateCheckResult(self, result):
        manual = self._update_check_manual
        publish_intent = self._update_check_publish_intent
        self._update_check_publish_intent = False
        status = (result or {}).get("status", "error")
        message = (result or {}).get("message", "")
        remote = (result or {}).get("remote", "")
        repo_root = (result or {}).get("repo_root", "")
        can_publish = bool((result or {}).get("can_publish"))

        if status == "update_available":
            if publish_intent:
                QMessageBox.information(
                    self,
                    "Publish Version to GitHub",
                    "GitHub already has a newer or equal version.\n\n"
                    + (message or f"Remote: v{remote}"),
                )
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("Update available")
            box.setText(message)
            update_btn = box.addButton("Update now", QMessageBox.AcceptRole)
            later_btn = box.addButton("Later", QMessageBox.RejectRole)
            skip_btn = box.addButton("Skip this version", QMessageBox.DestructiveRole)
            box.setDefaultButton(later_btn)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is update_btn:
                self._beginUpdateAndRebuild(repo_root)
            elif clicked is skip_btn and remote:
                self._settings.setSetting("skip_update_version", remote)
                self._settings.saveSettings()
                self._showStatus(f"Skipped update to v{remote}.")
            else:
                self._showStatus("Update postponed.")
            return

        if status == "local_ahead":
            if not manual:
                return
            if not can_publish:
                QMessageBox.warning(
                    self,
                    "Publish Version to GitHub"
                    if publish_intent
                    else "Local version is ahead",
                    message
                    or "Cannot publish: need a Git source checkout and Git installed.",
                )
                return
            if publish_intent:
                self._offerPublishToGitHub(result)
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("Local version is ahead")
            box.setText(message)
            publish_btn = box.addButton(
                "Publish to GitHub…", QMessageBox.AcceptRole
            )
            box.addButton("Close", QMessageBox.RejectRole)
            box.setDefaultButton(publish_btn)
            box.exec_()
            if box.clickedButton() is publish_btn:
                self._offerPublishToGitHub(result)
            return

        if status == "skipped" and not manual:
            return

        if not manual:
            # Stay quiet on automatic startup checks unless an update exists.
            return

        title = (
            "Publish Version to GitHub"
            if publish_intent
            else "Check for Updates"
        )
        if status == "up_to_date":
            if publish_intent:
                QMessageBox.information(
                    self,
                    title,
                    "Local and GitHub versions match "
                    f"(v{(result or {}).get('local', APP_VERSION)}). "
                    "Nothing to publish.",
                )
            else:
                QMessageBox.information(self, title, message or "You are up to date.")
        else:
            QMessageBox.warning(
                self,
                title,
                message or "Could not check for updates.",
            )

    def _offerPublishToGitHub(self, result):
        repo_root = (result or {}).get("repo_root", "")
        local_v = (result or {}).get("local", APP_VERSION)
        remote_v = (result or {}).get("remote", "")
        if not repo_root:
            QMessageBox.warning(
                self,
                "Publish Version to GitHub",
                "No Git project root was found.",
            )
            return

        preview = getPublishPreview(repo_root, local_v, remote_v)
        if preview.get("can_publish") and preview.get("dirty") is None:
            QMessageBox.warning(
                self,
                "Publish Version to GitHub",
                "Could not read git status for this project, so it is unclear "
                "what would be committed. Publish was not started.",
            )
            return
        dirty_line = (
            "Uncommitted changes will be committed as "
            f"\"release: v{local_v}\"."
            if preview.get("dirty")
            else "Working tree is clean (no new commit needed)."
        )
        text = (
            f"Publish local v{local_v} to GitHub (currently v{remote_v})?\n\n"
            f"Branch:  {preview.get('branch', '')}\n"
            f"Remote:  {preview.get('remote_url', '')}\n\n"
            f"{dirty_line}\n\n"
            "This uses a normal git push (never force-push)."
        )
        reply = QMessageBox.question(
            self,
            "Publish Version to GitHub",
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self._publish_pending_result = result
        auth = _loadSavedGitAuth(repo_root)
        if not auth or not auth.get("pat"):
            dlg = GitCredentialsDialog(
                repo_root,
                parent=self,
                message=(
                    "No saved GitHub credentials were found. "
                    "Enter a username and Personal Access Token (PAT) to push."
                ),
            )
            if dlg.exec_() != QDialog.Accepted:
                return
            auth = dlg.authDict()

        self._startPublishWorker(repo_root, auth)

    def _startPublishWorker(self, repo_root, auth):
        if self._publish_worker is not None and self._publish_worker.isRunning():
            self._showStatus("Publish already running…")
            return
        self._showStatus("Publishing version to GitHub…")
        worker = PublishVersionWorker(repo_root, auth=auth, parent=self)
        worker.resultReady.connect(self._onPublishVersionResult)
        self._publish_worker = worker
        worker.start()

    def _onPublishVersionResult(self, ok, message, auth_failed):
        pending = self._publish_pending_result or {}
        repo_root = pending.get("repo_root", "")
        if ok:
            self._publish_pending_result = None
            QMessageBox.information(
                self,
                "Publish Version to GitHub",
                message or "Published successfully.",
            )
            self._showStatus("Published version to GitHub.")
            return

        if auth_failed and repo_root:
            dlg = GitCredentialsDialog(
                repo_root,
                parent=self,
                message=(
                    "GitHub rejected the credentials. "
                    "Enter a valid username and PAT, then try again.\n\n"
                    f"{(message or '')[:300]}"
                ),
            )
            if dlg.exec_() == QDialog.Accepted:
                self._startPublishWorker(repo_root, dlg.authDict())
                return

        self._publish_pending_result = None
        QMessageBox.warning(
            self,
            "Publish Version to GitHub",
            message or "Publish failed.",
        )
        self._showStatus("Publish failed.")

    def _beginUpdateAndRebuild(self, repo_root):
        if not repo_root:
            QMessageBox.warning(
                self,
                "Update",
                "No Git project root was found for the update script.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Update and rebuild",
            "The app will close now.\n\n"
            "A console window will get the latest public sources "
            "(git pull, or GitHub zip if Git is not installed), rebuild with "
            "scripts\\build.bat, and start the new version.\n\n"
            "No GitHub login is required. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        # Clear skip so a failed update can prompt again next time.
        self._settings.setSetting("skip_update_version", "")
        try:
            self._settings.saveAll()
        except Exception:
            try:
                self._settings.saveSettings()
            except Exception:
                pass

        ok, err = launchUpdateAndRebuild(repo_root)
        if not ok:
            QMessageBox.warning(self, "Update", err or "Could not start the update script.")
            return

        self._showStatus("Updater started — closing…")
        QTimer.singleShot(200, QApplication.instance().quit)

    # --------------------------------------------------------
    # Utility
    # --------------------------------------------------------
    def _refreshBothPanels(self):
        self._left_panel.refresh(force_rescan=True)
        self._right_panel.refresh(force_rescan=True)

    def _showStatus(self, message, timeout=5000):
        self._status_info.setText(message)
        QTimer.singleShot(timeout, lambda: self._status_info.setText("Ready"))

    def _updateStatusBar(self):
        if not self._active_panel:
            return
        entries = self._active_panel.selectedEntries()
        if entries:
            total_size = sum(e["size"] for e in entries if not e["is_dir"] and e["size"] >= 0)
            dirs = sum(1 for e in entries if e["is_dir"])
            files = len(entries) - dirs
            parts = []
            if files:
                parts.append(f"{files} file(s)")
            if dirs:
                parts.append(f"{dirs} folder(s)")
            parts.append(f"Total: {formatFileSize(total_size)}")
            self._status_info.setText(" | ".join(parts))
        else:
            self._status_info.setText("Ready")

    # --------------------------------------------------------
    # Method: _activePanelSideName
    # Purpose: "Left" or "Right" for the panel that has focus.
    # --------------------------------------------------------
    def _activePanelSideName(self):
        if self._active_panel is self._left_panel:
            return "Left"
        return "Right"

    # --------------------------------------------------------
    # Method: _driveSpacePrefix
    # Purpose: "Left · /" style lead-in for the status label.
    #          The drive name matches the panel dropdown.
    # --------------------------------------------------------
    def _driveSpacePrefix(self, path):
        side = self._activePanelSideName()
        drive = driveLabelForPath(listDrives(), path) if path else ""
        if not drive:
            return side
        return f"{side} \u00b7 {drive}"

    # --------------------------------------------------------
    # Method: _onPanelListingFinished
    # Purpose: A folder reload finished (open, tab switch, F5,
    #          or a refresh after a transfer). Re-read space only
    #          for the panel that is active.
    # --------------------------------------------------------
    def _onPanelListingFinished(self):
        panel = self.sender()
        if panel is self._active_panel:
            self._refreshDriveSpace()
        if panel is self._left_panel or panel is self._right_panel:
            self._offerArchivePassword(panel)

    # --------------------------------------------------------
    # Method: _onActivePanelPathChanged
    # Purpose: The active panel opened another folder. A listing
    #          that already started a read for this path is left
    #          alone. Recursive cache hits never emit
    #          listingFinished, so this still updates the label.
    # --------------------------------------------------------
    def _onActivePanelPathChanged(self, path):
        if self.sender() is not self._active_panel:
            return
        # A flat listing still in flight emits listingFinished when it
        # finishes, and that starts the read. Starting one here as well
        # would stat a slow mount twice.
        if self._active_panel.sourceModel().isLoading():
            return
        if path and path == self._drive_space_path:
            return
        self._refreshDriveSpace()

    # --------------------------------------------------------
    # Method: _refreshDriveSpace
    # Purpose: Show which drive the active panel is on, then
    #          read used and free space on a background thread.
    # --------------------------------------------------------
    def _refreshDriveSpace(self):
        if not hasattr(self, "_drive_space_label"):
            return
        panel = self._active_panel
        if panel is None:
            return
        path = panel.currentPath() or ""
        self._drive_space_path = path
        self._drive_space_label.setToolTip(path)
        if not path:
            self._drive_space_label.setText("")
            self._retireDriveSpaceWorker()
            return
        prefix = self._driveSpacePrefix(path)
        self._drive_space_label.setText(f"{prefix} \u2014 reading\u2026")
        self._retireDriveSpaceWorker()
        worker = DriveSpaceWorker(path)
        worker.finishedOk.connect(self._onDriveSpaceRead)
        self._drive_space_worker = worker
        worker.start()

    # --------------------------------------------------------
    # Method: _onDriveSpaceRead
    # Purpose: Apply a finished space reading. A result for a
    #          folder the active panel has since left is ignored.
    # --------------------------------------------------------
    def _onDriveSpaceRead(self, path, space):
        if getattr(self, "_drive_space_closed", False):
            return
        if not self._active_panel:
            return
        if path != self._active_panel.currentPath():
            return
        prefix = self._driveSpacePrefix(path)
        if space is None:
            detail = "space unavailable"
        else:
            detail = (
                f"{formatFileSize(space.used)} used, "
                f"{formatFileSize(space.free)} free of {formatFileSize(space.total)}"
            )
        self._drive_space_label.setText(f"{prefix} \u2014 {detail}")

    # --------------------------------------------------------
    # Method: _retireDriveSpaceWorker
    # Purpose: Drop the in-flight space read without waiting.
    #          Its result is ignored because the slot is disconnected.
    # --------------------------------------------------------
    def _retireDriveSpaceWorker(self):
        worker = self._drive_space_worker
        self._drive_space_worker = None
        if worker is None:
            return
        try:
            worker.finishedOk.disconnect(self._onDriveSpaceRead)
        except TypeError:
            pass
        retireThread(worker, self._retired_drive_space_threads)

    # --------------------------------------------------------
    # Method: _stopDriveSpaceWorker
    # Purpose: Cancel the space read when the window closes so
    #          it cannot touch the status bar after it is gone.
    # --------------------------------------------------------
    def _stopDriveSpaceWorker(self):
        self._drive_space_closed = True
        self._retireDriveSpaceWorker()
        waitForThreads(
            list(self._retired_drive_space_threads),
            DRIVE_SPACE_SHUTDOWN_WAIT_MS,
        )

    # --------------------------------------------------------
    # Method: _stopTransfersForClose
    # Purpose: Ask before closing with transfers still queued or
    #          running, then cancel them. Returns False when the
    #          window should stay open.
    # --------------------------------------------------------
    def _stopTransfersForClose(self):
        if not self._transfer_queue.hasActiveWork():
            return True
        reply = QMessageBox.question(
            self,
            "Transfers in progress",
            "File transfers are still running.\n\nCancel them and exit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False
        if self._transfer_queue.shutdown(TRANSFER_SHUTDOWN_WAIT_MS):
            return True
        self._showStatus("Still stopping the current transfer. Try closing again in a moment.")
        return False

    # --------------------------------------------------------
    # Method: _detachUpdateCheckWorker
    # Purpose: Stop a running update check from showing UI on a
    #          closing window, and give it a moment to finish.
    # --------------------------------------------------------
    def _detachUpdateCheckWorker(self):
        worker = self._update_check_worker
        if worker is None:
            return
        try:
            worker.resultReady.disconnect(self._onUpdateCheckResult)
        except TypeError:
            pass
        if worker.isRunning():
            worker.wait(UPDATE_CHECK_SHUTDOWN_WAIT_MS)

    # --------------------------------------------------------
    # Window Close: Save State
    # --------------------------------------------------------
    def closeEvent(self, event):
        if not self._stopTransfersForClose():
            event.ignore()
            return
        self._detachUpdateCheckWorker()
        self._stopDriveSpaceWorker()

        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

        geo = self.geometry()
        self._settings.setSetting("window_geometry", {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
        })

        self._settings.setPanelState("left", self._left_tabs.exportState())
        self._settings.setPanelState("right", self._right_tabs.exportState())

        bm_width = self._main_splitter.sizes()[0]
        if bm_width >= 180:
            self._settings.setState("bookmarks_panel_width", bm_width)

        self._settings.applyBookmarkTreeSnapshot(self._bookmarks_panel.getStructure())

        current_tab = "libraries" if self._sidebar_tabs.currentIndex() == 1 else "bookmarks"
        self._settings.setSidebarState({
            "current_tab": current_tab,
            "hidden": bool(self._sidebar_user_hidden),
        })

        self._warnIfSaveFailed(self._settings.saveAll())
        self._left_panel.shutdownBackgroundWork()
        self._right_panel.shutdownBackgroundWork()
        clearArchiveCache()
        event.accept()

    # --------------------------------------------------------
    # Method: _warnIfSaveFailed
    # Purpose: Tell the user when settings could not be written
    #          (disk full, permissions) instead of failing silently.
    # Output: bool - the saved flag passed in.
    # --------------------------------------------------------
    def _warnIfSaveFailed(self, saved):
        if not saved:
            config_dir = os.path.dirname(getattr(self._settings, "_settings_path", "") or "")
            QMessageBox.warning(
                self,
                "Settings not saved",
                "Your settings could not be written to disk.\n\n"
                f"Check free space and permissions for:\n{config_dir}",
            )
        return saved
