"""
Settings dialog: theme, font, file display, delete confirmation, default pane paths.
Includes Import / Export of a single profile file (settings + bookmarks + libraries).
"""

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QGroupBox,
)
from PyQt5.QtCore import pyqtSignal

from theme import UI_SCALE_PRESETS, getThemeChoices, normalize_ui_scale, ui_scale_label


class SettingsDialog(QDialog):
    # Emitted after a profile file is successfully imported and saved.
    profileImported = pyqtSignal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self._settings = settings_manager
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self._theme_mode = QComboBox(self)
        for theme_id, label in getThemeChoices():
            self._theme_mode.addItem(label, theme_id)
        form.addRow("Theme", self._theme_mode)

        self._font_size = QSpinBox(self)
        self._font_size.setRange(8, 24)
        self._font_size.setSuffix(" pt")
        self._font_size.setToolTip(
            "Text and layout scale together.\n"
            "10 pt = 100% (default). Larger sizes grow row height, icons, and controls."
        )
        form.addRow("Font size (10 = 100%)", self._font_size)
        font_hint = QLabel(
            "Scales text with row height, file-list icons, and control sizes so "
            "filenames stay readable. 10 pt is the default (100%).",
            self,
        )
        font_hint.setWordWrap(True)
        form.addRow("", font_hint)

        self._ui_scale = QComboBox(self)
        for pct in UI_SCALE_PRESETS:
            self._ui_scale.addItem(ui_scale_label(pct), pct)
        form.addRow("Interface density", self._ui_scale)
        density_hint = QLabel(
            "Extra spacing tweak on top of font size. "
            "Extra compact / Very compact fit small screens; Comfortable for touch or large monitors. "
            "Ctrl+mouse wheel also steps density.",
            self,
        )
        density_hint.setWordWrap(True)
        form.addRow("", density_hint)

        self._show_hidden = QCheckBox("Show hidden files", self)
        form.addRow("Files", self._show_hidden)

        self._confirm_delete = QCheckBox("Ask before deleting files", self)
        form.addRow("Delete", self._confirm_delete)

        self._check_updates = QCheckBox(
            "Check for updates from Git when the app starts", self
        )
        self._check_updates.setToolTip(
            "Compares this app’s version to APP_VERSION on the Git remote.\n"
            "If a newer version exists, you can pull and rebuild."
        )
        form.addRow("Updates", self._check_updates)

        self._cache_scans = QCheckBox(
            "Cache recursive folder scans (Subfolders search)", self
        )
        self._cache_scans.setToolTip(
            "Keeps Subfolders listings in memory and on disk so returning to the same\n"
            "folder is fast. Copy/move updates the list without a full re-scan.\n"
            "Use the filter banner Refresh (or F5) to force a full scan from disk.\n"
            "Deep changes made outside the app may need a manual Refresh."
        )
        form.addRow("Search cache", self._cache_scans)

        self._default_left_path = QLineEdit(self)
        form.addRow("Default left path", self._default_left_path)

        self._default_right_path = QLineEdit(self)
        form.addRow("Default right path", self._default_right_path)

        self._mirror_mode = QComboBox(self)
        self._mirror_mode.addItem(
            "Inactive panel follows active (open active’s folder in the other pane)",
            "to_other",
        )
        self._mirror_mode.addItem(
            "Active panel follows inactive (open inactive’s folder in the active pane)",
            "to_active",
        )
        form.addRow("Mirror (Ctrl+Shift+M)", self._mirror_mode)

        layout.addLayout(form)

        profile_box = QGroupBox("Profile (settings, bookmarks, libraries)", self)
        profile_layout = QVBoxLayout(profile_box)
        profile_hint = QLabel(
            "Export saves one file with preferences, bookmarks, libraries, tags, "
            "and saved filters. Import replaces those from a previously exported file.",
            self,
        )
        profile_hint.setWordWrap(True)
        profile_layout.addWidget(profile_hint)
        profile_buttons = QHBoxLayout()
        self._btn_export = QPushButton("Export…", self)
        self._btn_import = QPushButton("Import…", self)
        self._btn_export.setToolTip(
            "Save settings, bookmarks, libraries, and related data to a single JSON file."
        )
        self._btn_import.setToolTip(
            "Load settings, bookmarks, libraries, and related data from a profile JSON file."
        )
        self._btn_export.clicked.connect(self._onExportProfile)
        self._btn_import.clicked.connect(self._onImportProfile)
        profile_buttons.addWidget(self._btn_export)
        profile_buttons.addWidget(self._btn_import)
        profile_buttons.addStretch()
        profile_layout.addLayout(profile_buttons)
        layout.addWidget(profile_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._loadFromSettings()

    # --------------------------------------------------------
    # Method: _loadFromSettings
    # Purpose: Fill form controls from the settings manager.
    # --------------------------------------------------------
    def _loadFromSettings(self):
        current_theme = self._settings.getSetting("theme_mode", "dark")
        self._theme_mode.setCurrentIndex(max(0, self._theme_mode.findData(current_theme)))
        self._font_size.setValue(int(self._settings.getSetting("font_size", 10)))
        cur_scale = normalize_ui_scale(self._settings.getSetting("ui_scale", 100))
        self._ui_scale.setCurrentIndex(max(0, self._ui_scale.findData(cur_scale)))
        self._show_hidden.setChecked(self._settings.getSetting("show_hidden_files", False))
        self._confirm_delete.setChecked(self._settings.getSetting("confirm_delete", True))
        self._check_updates.setChecked(
            self._settings.getSetting("check_for_updates_on_startup", True)
        )
        self._cache_scans.setChecked(
            self._settings.getSetting("cache_recursive_scans", True)
        )
        self._default_left_path.setText(self._settings.getSetting("default_left_path", "") or "")
        self._default_right_path.setText(self._settings.getSetting("default_right_path", "") or "")
        cur_mirror = self._settings.getSetting("mirror_mode", "to_other")
        self._mirror_mode.setCurrentIndex(max(0, self._mirror_mode.findData(cur_mirror)))

    def values(self):
        return {
            "theme_mode": self._theme_mode.currentData(),
            "font_size": self._font_size.value(),
            "ui_scale": self._ui_scale.currentData(),
            "show_hidden_files": self._show_hidden.isChecked(),
            "confirm_delete": self._confirm_delete.isChecked(),
            "check_for_updates_on_startup": self._check_updates.isChecked(),
            "cache_recursive_scans": self._cache_scans.isChecked(),
            "default_left_path": self._default_left_path.text().strip(),
            "default_right_path": self._default_right_path.text().strip(),
            "mirror_mode": self._mirror_mode.currentData(),
        }

    # --------------------------------------------------------
    # Method: _onExportProfile
    # Purpose: Save settings + bookmarks/libraries to one JSON file.
    # --------------------------------------------------------
    def _onExportProfile(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export profile",
            "total-commander-clone-profile.json",
            "Profile JSON (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            self._settings.exportProfile(path, settings_override=self.values())
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Export complete",
            f"Profile saved to:\n{path}\n\n"
            "Includes settings, bookmarks, libraries, tags, and saved filters.",
        )

    # --------------------------------------------------------
    # Method: _onImportProfile
    # Purpose: Load a profile JSON and apply it immediately.
    # --------------------------------------------------------
    def _onImportProfile(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import profile",
            "",
            "Profile JSON (*.json);;All files (*.*)",
        )
        if not path:
            return
        reply = QMessageBox.question(
            self,
            "Import profile",
            "Importing will replace current settings, bookmarks, libraries, "
            "tags, and saved filters with the file contents.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            summary = self._settings.importProfile(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return

        self._loadFromSettings()
        self.profileImported.emit()
        keys = ", ".join(summary.get("state_keys") or []) or "(none)"
        QMessageBox.information(
            self,
            "Import complete",
            f"Loaded profile from:\n{path}\n\n"
            f"Settings keys applied: {summary.get('settings_count', 0)}\n"
            f"State sections: {keys}",
        )
