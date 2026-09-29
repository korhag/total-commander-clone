"""
Total Commander Clone - Main Application Window
Assembles the dual-pane layout, toolbar, menu bar, status bar,
right-click context menus, keyboard shortcuts, and bookmarks.
"""

import os
import shutil
import subprocess
import platform

from PyQt5.QtWidgets import (
    QMainWindow, QSplitter, QToolBar, QAction, QStatusBar,
    QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget,
    QMenu, QMessageBox, QInputDialog, QApplication, QLabel,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QFileDialog,
    QStyle, QTabWidget, QStackedWidget, QSizePolicy, QToolButton,
)
from PyQt5.QtCore import Qt, QUrl, QTimer, QRect, QSize, QEvent, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence, QDesktopServices, QIcon

from file_panel import FilePanel, DEFAULT_DATE_MODIFIED_FORMAT, resolve_date_modified_format_key
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
from settings_dialog import SettingsDialog
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

    min_w, min_h = 800, 500
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
        self._updateMirrorTooltips()
        self._state_restore_done = False
        self._post_show_layout_done = False
        self._update_check_worker = None
        self._update_check_manual = False
        self._update_check_publish_intent = False
        self._publish_worker = None
        self._publish_pending_result = None
        self._configureScanCache()
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
                "width": max(frame.width(), 800),
                "height": max(frame.height(), 500),
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
        sizes = self._main_splitter.sizes()
        if sizes and sizes[0] < 180:
            rest = max(400, sum(sizes) - 260)
            self._main_splitter.setSizes([260, rest])
        self._applyUiMetrics()
        self._left_panel.relayoutColumns()
        self._right_panel.relayoutColumns()

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
        self.setMinimumSize(800, 500)

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
        style = QApplication.instance().style()
        toolbar = self._toolbar

        self._tb_copy = QAction("\U0001F4CB Copy (F6)", self)
        self._tb_copy.setToolTip(
            "Copy to other panel\n\n"
            "Copy selected items to the opposite panel. Shortcut: F6."
        )
        self._tb_copy.triggered.connect(self._onCopyToOther)
        toolbar.addAction(self._tb_copy)

        self._tb_move = QAction("\U0001F4E6 Move (F7)", self)
        self._tb_move.setToolTip(
            "Move to other panel\n\n"
            "Move selected items to the opposite panel. Shortcut: F7."
        )
        self._tb_move.triggered.connect(self._onMoveToOther)
        toolbar.addAction(self._tb_move)

        self._tb_delete = QAction("\U0001F5D1 Delete (F9)", self)
        self._tb_delete.setToolTip(
            "Delete\n\nDelete selected items. Shortcut: F9."
        )
        self._tb_delete.triggered.connect(self._onDelete)
        toolbar.addAction(self._tb_delete)

        toolbar.addSeparator()

        self._tb_new_folder = QAction("\U0001F4C1 New Folder (F8)", self)
        self._tb_new_folder.setToolTip(
            "New folder\n\nCreate a folder in the active panel. Shortcut: F8."
        )
        self._tb_new_folder.triggered.connect(self._onNewFolder)
        toolbar.addAction(self._tb_new_folder)

        self._tb_rename = QAction("\u270F Rename (F2)", self)
        self._tb_rename.setToolTip(
            "Rename\n\nRename the selected item. Shortcut: F2."
        )
        self._tb_rename.triggered.connect(self._onRename)
        toolbar.addAction(self._tb_rename)

        self._tb_batch_rename = QAction("\U0001F504 Batch Rename", self)
        self._tb_batch_rename.setToolTip(
            "Batch rename\n\n"
            "Rename multiple files in the current folder. Shortcut: Ctrl+M."
        )
        self._tb_batch_rename.triggered.connect(self._onBatchRename)
        toolbar.addAction(self._tb_batch_rename)

        toolbar.addSeparator()

        self._tb_bookmark = QAction("\u2B50 Bookmark", self)
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
        self._tb_open_explorer.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self._tb_open_explorer.triggered.connect(self._onOpenActivePathInExplorer)
        toolbar.addAction(self._tb_open_explorer)

        self._tb_refresh = QAction("\U0001F504 Refresh", self)
        self._tb_refresh.setToolTip(
            "Refresh both panels\n\n"
            "Reload both panels. F5 refreshes only the active panel."
        )
        self._tb_refresh.triggered.connect(self._onRefresh)
        toolbar.addAction(self._tb_refresh)

        toolbar.addSeparator()

        self._tb_settings = QAction("\u2699 Settings", self)
        self._tb_settings.setToolTip(
            "Settings\n\n"
            "Theme, font size, interface density (Compact/Normal/Comfortable), and more. "
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
        icon = metrics["toolbar_icon"]
        if hasattr(self, "_toolbar"):
            self._toolbar.setIconSize(QSize(icon, icon))
        if hasattr(self, "_bottom_bar"):
            self._bottom_bar.setFixedHeight(metrics["bottom_bar_height"])
        if hasattr(self, "_center_buttons"):
            w = metrics["center_panel_width"]
            self._center_buttons.setFixedWidth(w)
        self._left_panel.applyUiMetrics(metrics)
        self._right_panel.applyUiMetrics(metrics)

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
        self._settings.saveSettings()
        self._showStatus(f"Interface density: {ui_scale_label(new_scale)}")
        return True

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
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
    # Method: _initPanels
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

        self._center_buttons = self._buildCenterButtons()

        panels_layout.addWidget(self._left_stack, 1)
        panels_layout.addWidget(self._center_buttons)
        panels_layout.addWidget(self._right_stack, 1)

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

        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.addWidget(self._sidebar_tabs)
        self._main_splitter.addWidget(file_panes_widget)

        # Prevent sidebar from collapsing to zero; file area can shrink freely.
        self._main_splitter.setCollapsible(0, False)
        self._main_splitter.setCollapsible(1, True)

        bm_width = self._settings.getState("bookmarks_panel_width")
        if bm_width and isinstance(bm_width, (int, float)) and 180 <= bm_width <= 600:
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
        self._left_panel.compareRequested.connect(
            lambda: self._onCompareWithOtherPanel(self._left_panel)
        )
        self._right_panel.compareRequested.connect(
            lambda: self._onCompareWithOtherPanel(self._right_panel)
        )

        self._left_panel.dateModifiedFormatChanged.connect(self._onDateModifiedFormatChanged)
        self._right_panel.dateModifiedFormatChanged.connect(self._onDateModifiedFormatChanged)

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
    # Method: _buildCenterButtons
    # Purpose: Creates the vertical column of directional
    #          copy/move buttons that sits between the panels.
    #          Arrows update dynamically based on active panel.
    # --------------------------------------------------------
    def _buildCenterButtons(self):
        frame = QFrame()
        frame.setObjectName("centerPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(4)

        layout.addStretch(1)

        self._btn_copy_dir = QPushButton()
        self._btn_copy_dir.setToolTip(
            "Copy to other panel\n\n"
            "Copy selected items from the active panel to the opposite panel. Shortcut: F6."
        )
        self._btn_copy_dir.setFocusPolicy(Qt.NoFocus)
        self._btn_copy_dir.clicked.connect(self._onCopyToOther)
        layout.addWidget(self._btn_copy_dir)

        self._lbl_copy = QLabel("COPY")
        self._lbl_copy.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_copy)

        layout.addSpacing(6)

        self._btn_move_dir = QPushButton()
        self._btn_move_dir.setToolTip(
            "Move to other panel\n\n"
            "Move selected items from the active panel to the opposite panel. Shortcut: F7."
        )
        self._btn_move_dir.setFocusPolicy(Qt.NoFocus)
        self._btn_move_dir.clicked.connect(self._onMoveToOther)
        layout.addWidget(self._btn_move_dir)

        self._lbl_move = QLabel("MOVE")
        self._lbl_move.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_move)

        layout.addSpacing(8)

        self._btn_special = QToolButton()
        self._btn_special.setObjectName("centerSpecialButton")
        self._btn_special.setPopupMode(QToolButton.InstantPopup)
        self._btn_special.setFocusPolicy(Qt.NoFocus)
        self._btn_special.setToolTip(
            "Special transfers\n\n"
            "Copy or move while keeping folder structure relative to the "
            "active panel’s current folder (search root). Also copy relative "
            "or full paths to the clipboard."
        )
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
        layout.addWidget(self._btn_special)

        self._lbl_special = QLabel("SPECIAL")
        self._lbl_special.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_special)

        layout.addSpacing(8)

        self._btn_swap = QPushButton("\u21C4")
        self._btn_swap.setToolTip(
            "Swap panes\n\n"
            "Exchange the left and right folder paths. Shortcut: Ctrl+Shift+S."
        )
        self._btn_swap.setFocusPolicy(Qt.NoFocus)
        self._btn_swap.clicked.connect(self._onSwapPanels)
        layout.addWidget(self._btn_swap)

        self._lbl_swap = QLabel("SWAP")
        self._lbl_swap.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_swap)

        layout.addSpacing(8)

        self._btn_mirror = QPushButton("\u229C")
        self._btn_mirror.setFocusPolicy(Qt.NoFocus)
        self._btn_mirror.clicked.connect(self._onMirrorToOther)
        layout.addWidget(self._btn_mirror)

        self._lbl_mirror = QLabel("MIRROR")
        self._lbl_mirror.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_mirror)

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
            arrow = "\u27A1"
            flow = "Left \u2192 Right"
            other = "right"
        else:
            arrow = "\u2B05"
            flow = "Right \u2192 Left"
            other = "left"
        self._btn_copy_dir.setText(arrow)
        self._btn_move_dir.setText(arrow)
        self._btn_copy_dir.setToolTip(
            "Copy to other panel\n\n"
            f"Copy selected items to the {other} panel. Flow: {flow}. Shortcut: F6."
        )
        self._btn_move_dir.setToolTip(
            "Move to other panel\n\n"
            f"Move selected items to the {other} panel. Flow: {flow}. Shortcut: F7."
        )
        if hasattr(self, "_btn_special"):
            self._btn_special.setText(arrow)
            self._btn_special.setToolTip(
                "Special transfers\n\n"
                f"Copy or move keeping structure to the {other} panel "
                f"(Flow: {flow}), or copy relative/full paths to the clipboard."
            )

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

        for text, callback, tip in button_defs:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(callback)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            layout.addWidget(btn)
        layout.addStretch(1)

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

    # --------------------------------------------------------
    # Method: _initShortcuts
    # Purpose: Registers all keyboard shortcuts.
    # --------------------------------------------------------
    def _initShortcuts(self):
        shortcuts = {
            QKeySequence(Qt.Key_F2):                     self._onRename,
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
            QKeySequence("Ctrl+,"):                       self._onOpenSettings,
        }

        for key_seq, callback in shortcuts.items():
            action = QAction(self)
            action.setShortcut(key_seq)
            action.setShortcutContext(Qt.WindowShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    # --------------------------------------------------------
    # Method: _restoreState
    # Purpose: Loads saved panel paths from state.json and
    #          navigates both panels to their last location.
    # --------------------------------------------------------
    def _restoreState(self):
        home = os.path.expanduser("~")

        left_state = self._settings.getPanelState("left")
        right_state = self._settings.getPanelState("right")

        left_path = left_state.get("current_path", "") or self._settings.getSetting("default_left_path", "") or home
        right_path = right_state.get("current_path", "") or self._settings.getSetting("default_right_path", "") or home

        if not os.path.isdir(left_path):
            left_path = home
        if not os.path.isdir(right_path):
            right_path = home

        self._left_panel.restoreHistoryData(left_state)
        self._right_panel.restoreHistoryData(right_state)

        if not self._left_panel.currentPath():
            self._left_panel.navigateTo(left_path)
        if not self._right_panel.currentPath():
            self._right_panel.navigateTo(right_path)

        fallback_widths = self._settings.getSetting("column_widths", {})
        if fallback_widths and not left_state.get("column_widths"):
            self._left_panel.applyColumnWidths(fallback_widths)
        if fallback_widths and not right_state.get("column_widths"):
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
        if hasattr(self, "_btn_copy_dir"):
            self._updateDirectionButtons()

    def _getInactivePanel(self):
        if self._active_panel == self._left_panel:
            return self._right_panel
        return self._left_panel

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
    # File Operation Handlers
    # --------------------------------------------------------
    def _onCopyToOther(self):
        if not self._active_panel:
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        dest = self._getInactivePanel().currentPath()
        if not dest:
            self._showStatus("No destination panel.")
            return

        self._transfer_queue.enqueueCopy(paths, dest)
        self._showStatus(f"Copy queued ({len(paths)} item(s)).")

    def _onMoveToOther(self):
        if not self._active_panel:
            return
        paths = self._active_panel.selectedPaths()
        if not paths:
            self._showStatus("No files selected.")
            return
        dest = self._getInactivePanel().currentPath()
        if not dest:
            self._showStatus("No destination panel.")
            return

        self._transfer_queue.enqueueMove(paths, dest)
        self._showStatus(f"Move queued ({len(paths)} item(s)).")

    # --------------------------------------------------------
    # Special transfers (keep structure relative to search root)
    # --------------------------------------------------------
    def _prepareStructureTransfer(self, verb):
        """Return (paths, rels, dest) or (None, None, None) after UI feedback."""
        if not self._active_panel:
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
        if not self._active_panel or self._active_panel.isRenaming():
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
        if not self._active_panel:
            return
        if self._active_panel.isRenaming():
            return
        self._active_panel.startRename()

    def _onFolderCreatedFromPanel(self, folder_name):
        self._showStatus(f"Created folder: {folder_name}")

    def _onNewFolder(self):
        if not self._active_panel:
            return
        self._active_panel.createNewFolder()

    # --------------------------------------------------------
    # Batch Rename: Opens the multi-rename dialog.
    # If files are selected, operates on selection only.
    # Otherwise operates on all files in the current folder.
    # --------------------------------------------------------
    def _onBatchRename(self):
        if not self._active_panel:
            return
        current_dir = self._active_panel.currentPath()
        if not current_dir:
            return

        model = self._active_panel.sourceModel()
        entries = [
            model.entryAt(i) for i in range(model.rowCount())
            if model.entryAt(i) is not None
        ]

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
            else:
                self._onFileOpen(entry)

    # --------------------------------------------------------
    # Open file with system default application
    # --------------------------------------------------------
    def _onFileOpen(self, entry):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(entry["full_path"]))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{e}")

    # --------------------------------------------------------
    # Navigation
    # --------------------------------------------------------
    def _onBackspace(self):
        if not self._active_panel or self._active_panel.isRenaming():
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
        if not self._active_panel:
            return
        self._clipboard_paths = self._active_panel.selectedPaths()
        self._clipboard_mode = "cut"
        if self._clipboard_paths:
            self._syncNativeFileClipboard()
            self._showStatus(f"Cut {len(self._clipboard_paths)} item(s)")

    def _onCopyToClipboard(self):
        if not self._active_panel:
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
        if not self._active_panel:
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
        dialog = SettingsDialog(self._settings, self)
        dialog.profileImported.connect(self._onSettingsProfileImported)
        if dialog.exec_() != QDialog.Accepted:
            return

        values = dialog.values()
        for key, value in values.items():
            self._settings.setSetting(key, value)

        self._applySettingsValues(values)
        self._settings.saveSettings()
        self._updateMirrorTooltips()
        self._showStatus("Settings saved.")

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
            panel = self._left_panel if side == "left" else self._right_panel
            panel_state = self._settings.getPanelState(side)
            if isinstance(panel_state, dict):
                panel.applyFilterState(panel_state)
                panel.restoreHistoryData(panel_state)
        self._updateMirrorTooltips()
        self._showStatus("Profile imported.")

    # --------------------------------------------------------
    # Bookmarks
    # --------------------------------------------------------
    def _getActivePanelPath(self):
        if self._active_panel:
            return self._active_panel.currentPath()
        return ""

    def _onAddBookmark(self):
        if not self._active_panel:
            return
        path = self._active_panel.currentPath()
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

            reveal_action = menu.addAction("Open in File Explorer")
            reveal_action.setToolTip(
                "Open in File Explorer\n\n"
                "Show this item in the system file manager "
                "(selects the file or folder in Explorer)."
            )
            reveal_action.triggered.connect(
                lambda e=entry: self._onRevealInFileExplorer(e)
            )

            terminal_action = menu.addAction("Open Folder in Terminal")
            terminal_action.setToolTip(
                "Open folder in Terminal\n\n"
                "Open a Command Prompt / terminal window in the folder "
                "that contains this item (or in the folder itself)."
            )
            terminal_action.triggered.connect(
                lambda e=entry: self._onOpenFolderInTerminal(e)
            )

        if file_entries:
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
                lambda fe=list(file_entries): self._onOpenWith(fe)
            )

        if single_selection or file_entries:
            menu.addSeparator()

        if has_selection:
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
            copy_other_action = menu.addAction("Copy to Other Panel\tF6")
            copy_other_action.setToolTip(
                "Copy to other panel\n\nCopy selected items to the opposite panel. Shortcut: F6."
            )
            copy_other_action.triggered.connect(self._onCopyToOther)

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

        if single_selection:
            rename_action = menu.addAction("Rename\tF2")
            rename_action.setToolTip(
                "Rename\n\nRename the selected item. Shortcut: F2."
            )
            rename_action.triggered.connect(self._onRename)

        if has_selection:
            delete_action = menu.addAction("Delete\tF9")
            delete_action.setToolTip(
                "Delete\n\nDelete selected items. Shortcut: F9."
            )
            delete_action.triggered.connect(self._onDelete)

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

        menu.addSeparator()

        if single_selection:
            copy_path_action = menu.addAction("Copy Path to Clipboard")
            copy_path_action.setToolTip(
                "Copy path\n\nCopy the full path of this item as text."
            )
            copy_path_action.triggered.connect(
                lambda: self._copyPathToClipboard(entries[0]["full_path"])
            )

        if single_selection and entries[0]["is_dir"]:
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

        bookmark_action = menu.addAction("Bookmark This Folder")
        bookmark_action.setToolTip(
            "Bookmark folder\n\nSave the current folder as a bookmark."
        )
        bookmark_action.triggered.connect(self._onAddBookmark)

        if single_selection and not entries[0]["is_dir"]:
            bookmark_file_action = menu.addAction("Bookmark This File")
            bookmark_file_action.setToolTip(
                "Bookmark file\n\nSave this file path as a bookmark (double-click opens it)."
            )
            bookmark_file_action.triggered.connect(
                lambda: self._onAddFileBookmark(entries[0])
            )

        if single_selection:
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
                subprocess.Popen(
                    f'explorer /select,"{path}"',
                    shell=True,
                )
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
            system = platform.system()
            if system == "Windows":
                wt = shutil.which("wt")
                if wt:
                    subprocess.Popen([wt, "-d", folder])
                else:
                    # CREATE_NEW_CONSOLE so cmd opens in its own window.
                    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                    subprocess.Popen(
                        ["cmd.exe", "/K", f'cd /d "{folder}"'],
                        creationflags=creationflags,
                    )
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", "Terminal", folder])
            else:
                launched = False
                for cmd in (
                    ["x-terminal-emulator", f"--working-directory={folder}"],
                    ["gnome-terminal", f"--working-directory={folder}"],
                    ["konsole", "--workdir", folder],
                    ["xfce4-terminal", f"--working-directory={folder}"],
                ):
                    exe = shutil.which(cmd[0])
                    if exe:
                        subprocess.Popen([exe] + cmd[1:])
                        launched = True
                        break
                if not launched:
                    raise OSError(
                        "No supported terminal found "
                        "(tried x-terminal-emulator, gnome-terminal, "
                        "konsole, xfce4-terminal)."
                    )
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

        path = self._active_panel.currentPath()
        if not path or not os.path.isdir(path):
            self._showStatus("No active folder to open.")
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
                f"Could not open the active folder in the file explorer:\n{e}",
            )

    # --------------------------------------------------------
    # Properties Dialog
    # --------------------------------------------------------
    def _showProperties(self, entry):
        showFileProperties(entry, self)

    # --------------------------------------------------------
    # Drag-and-Drop from Panel
    # --------------------------------------------------------
    def _onDroppedFiles(self, file_paths, drop_target, is_copy):
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
            "scripts\\build-user.bat, and start the new version.\n\n"
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
            from file_panel import formatFileSize
            parts.append(f"Total: {formatFileSize(total_size)}")
            self._status_info.setText(" | ".join(parts))
        else:
            self._status_info.setText("Ready")

    # --------------------------------------------------------
    # Window Close: Save State
    # --------------------------------------------------------
    def closeEvent(self, event):
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

        self._settings.setPanelState("left", self._left_panel.getHistoryData())
        self._settings.setPanelState("right", self._right_panel.getHistoryData())

        bm_width = self._main_splitter.sizes()[0]
        if bm_width >= 180:
            self._settings.setState("bookmarks_panel_width", bm_width)

        self._settings.applyBookmarkTreeSnapshot(self._bookmarks_panel.getStructure())

        current_tab = "libraries" if self._sidebar_tabs.currentIndex() == 1 else "bookmarks"
        self._settings.setSidebarState({
            "current_tab": current_tab,
        })

        self._settings.saveAll()
        event.accept()
