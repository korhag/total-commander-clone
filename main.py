"""
Total Commander Clone - Modern Dual-Pane File Manager
Entry point for the application.
"""

import sys
import os
import ctypes
import traceback
from datetime import datetime

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt, QThread
from PyQt5.QtGui import QIcon, QPalette

from file_manager_app import FileManagerApp
from settings_manager import SettingsManager
from theme import applyTheme
from app_version import APP_VERSION


# ------------------------------------------------------------
# Function: getBasePath
# Purpose: Returns the base directory where the application
#          and its config files reside.
# ------------------------------------------------------------
def getBasePath():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------
# Function: getConfigPath
# Purpose: Returns the directory for settings.json and state.json.
#          When frozen: uses %APPDATA% so settings persist across
#          rebuilds. When dev: uses project directory.
# ------------------------------------------------------------
def configureFrozenQtEnvironment():
    """Point Qt at bundled plugins when running as a PyInstaller one-folder build."""
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    plugins = os.path.join(meipass, "PyQt5", "Qt5", "plugins")
    if os.path.isdir(plugins):
        os.environ.setdefault("QT_PLUGIN_PATH", plugins)
        platforms = os.path.join(plugins, "platforms")
        if os.path.isdir(platforms):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", platforms)
    qt_bin = os.path.join(meipass, "PyQt5", "Qt5", "bin")
    if os.path.isdir(qt_bin):
        os.environ["PATH"] = qt_bin + os.pathsep + os.environ.get("PATH", "")


def getConfigPath():
    if getattr(sys, 'frozen', False):
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "TotalCommanderClone")
    return os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------
# Function: appendDiagnosticLog
# Purpose: Append a line to a log file under the config folder.
# ------------------------------------------------------------
def appendDiagnosticLog(filename, message):
    try:
        log_dir = getConfigPath()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, filename)
        stamp = datetime.now().isoformat(timespec="seconds")
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


# ------------------------------------------------------------
# Function: showUnhandledErrorDialog
# Purpose: Tell the user that an action failed instead of letting
#          it fail silently. Only runs on the GUI thread (worker
#          threads must not create widgets) and never nests a
#          second dialog while one is already open.
# ------------------------------------------------------------
_error_dialog_open = False


def showUnhandledErrorDialog(exc_type, exc):
    global _error_dialog_open
    app = QApplication.instance()
    if app is None or _error_dialog_open:
        return
    if QThread.currentThread() is not app.thread():
        return
    _error_dialog_open = True
    try:
        log_path = os.path.join(getConfigPath(), "crash.log")
        QMessageBox.critical(
            None,
            "Unexpected error",
            f"The action could not be completed.\n\n"
            f"{exc_type.__name__}: {exc}\n\n"
            f"Details were saved to:\n{log_path}",
        )
    finally:
        _error_dialog_open = False


# ------------------------------------------------------------
# Function: installCrashLogging
# Purpose: Log unhandled exceptions to %APPDATA%\TotalCommanderClone\crash.log
#          and surface them to the user when they happen in the UI.
# ------------------------------------------------------------
def installCrashLogging():
    def _excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        appendDiagnosticLog("crash.log", f"Unhandled exception:\n{text}")
        sys.__excepthook__(exc_type, exc, tb)
        showUnhandledErrorDialog(exc_type, exc)

    sys.excepthook = _excepthook


# ------------------------------------------------------------
# Function: configureWindowsTaskbarIdentity
# Purpose: Ensures Windows groups this app with a custom
#          AppUserModelID so the taskbar uses app icon identity.
# ------------------------------------------------------------
def configureWindowsTaskbarIdentity():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "TCClone.FileExplorer"
        )
    except Exception:
        pass


# ------------------------------------------------------------
# Function: resolveAppIconPath
# Purpose: Resolves path to file-explorer.ico from common app
#          locations.
# ------------------------------------------------------------
def resolveAppIconPath(base_path):
    candidate_paths = [
        os.path.join(base_path, "file-explorer.ico"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "file-explorer.ico"),
    ]
    for icon_path in candidate_paths:
        if os.path.isfile(icon_path):
            return icon_path
    return ""


# ------------------------------------------------------------
# Function: main
# Purpose: Initializes the application, loads settings,
#          applies the dark theme, and launches the main window.
# ------------------------------------------------------------
def main():
    installCrashLogging()
    configureWindowsTaskbarIdentity()
    configureFrozenQtEnvironment()

    frozen = getattr(sys, "frozen", False)
    appendDiagnosticLog(
        "startup.log",
        f"Starting {APP_VERSION} frozen={frozen} argv={sys.argv!r}",
    )

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Qt 5.15 otherwise rounds 150% up to 200%, which makes the UI oversized.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("Total Commander Clone")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TCClone")
    app._system_style_name = app.style().objectName()
    app._system_palette = QPalette(app.palette())

    base_path = getBasePath()
    config_path = getConfigPath()
    if frozen and not os.path.isdir(config_path):
        os.makedirs(config_path, exist_ok=True)
    icon_path = resolveAppIconPath(base_path)
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # Project/git root for update checks and Publish Version.
    # Prefer walking from source/exe so frozen builds in dist\ still find the repo.
    settings_manager = SettingsManager(config_path, project_root=base_path)

    font_size = int(settings_manager.getSetting("font_size", 10))
    ui_scale = settings_manager.getSetting("ui_scale", 100)
    applyTheme(
        app,
        settings_manager.getSetting("theme_mode", "dark"),
        font_size,
        ui_scale,
    )

    try:
        window = FileManagerApp(settings_manager)
        if icon_path:
            window.setWindowIcon(QIcon(icon_path))
        window.show()
        app.processEvents()
        appendDiagnosticLog("startup.log", "Main window shown")
    except Exception:
        appendDiagnosticLog(
            "crash.log",
            f"Startup failed:\n{traceback.format_exc()}",
        )
        raise

    exit_code = app.exec_()
    settings_manager.saveAll()
    appendDiagnosticLog("startup.log", f"Exit code {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
