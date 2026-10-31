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
    QScrollArea,
    QSizePolicy,
    QWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal

from action_icons import iconSetChoices, normalizeIconSet
from theme import UI_SCALE_PRESETS, getThemeChoices, normalize_ui_scale, ui_scale_label
from theme_picker import ThemePreviewDialog


class SettingsDialog(QDialog):
    # Emitted after a profile file is successfully imported and saved.
    profileImported = pyqtSignal()

    def __init__(self, settings_manager, parent=None, on_theme_preview=None):
        super().__init__(parent)
        self._settings = settings_manager
        self._on_theme_preview = on_theme_preview
        self._theme_id = "dark"
        self.setWindowTitle("Settings")
        self.setModal(True)

        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._theme_button = QPushButton(self)
        self._theme_button.setToolTip(
            "Open the theme list.\n"
            "A click previews that theme. Accept keeps it. Cancel restores the previous one."
        )
        self._theme_button.clicked.connect(self._openThemePreview)
        form.addRow("Theme", self._theme_button)

        self._icon_set = QComboBox(self)
        for set_id, label in iconSetChoices():
            self._icon_set.addItem(label, set_id)
        self._icon_set.setToolTip(
            "Toolbar, panel, and center-strip icons.\n"
            "Tiles follow the theme accent. Line icons follow the text color.\n"
            "Mixed uses tiles for the first row (Copy through Delete) and line icons after that."
        )
        form.addRow("Icon set", self._icon_set)

        self._font_size = QSpinBox(self)
        self._font_size.setRange(8, 24)
        self._font_size.setSuffix(" pt")
        self._font_size.setToolTip(
            "Text and layout scale together.\n"
            "10 pt = 100% (default). Larger sizes grow row height, icons, and controls."
        )
        form.addRow("Font size (10 = 100%)", self._font_size)
        self._font_hint = self._hintLabel(
            "Scales text with row height, file-list icons, and control sizes so "
            "filenames stay readable. 10 pt is the default (100%)."
        )
        form.addRow(self._font_hint)

        self._ui_scale = QComboBox(self)
        for pct in UI_SCALE_PRESETS:
            self._ui_scale.addItem(ui_scale_label(pct), pct)
        form.addRow("Interface density", self._ui_scale)
        self._density_hint = self._hintLabel(
            "Extra spacing tweak on top of font size. "
            "Extra compact / Very compact fit small screens; Comfortable for touch or large monitors. "
            "Ctrl+mouse wheel also steps density."
        )
        form.addRow(self._density_hint)

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
            "Changes inside subfolders still need a manual Refresh."
        )
        form.addRow("Search cache", self._cache_scans)

        self._auto_refresh = QCheckBox(
            "Reload panels when the folder changes outside this app", self
        )
        self._auto_refresh.setToolTip(
            "When a download, Explorer, or another program changes the open folder,\n"
            "the file list updates on its own. Subfolders mode does not rescan the\n"
            "whole tree; press Refresh (F5) there."
        )
        form.addRow("Auto-refresh", self._auto_refresh)

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

        body_layout.addLayout(form)

        profile_box = QGroupBox("Profile (settings, bookmarks, libraries)", self)
        profile_layout = QVBoxLayout(profile_box)
        self._profile_hint = self._hintLabel(
            "Export saves one file with preferences, bookmarks, libraries, fields, "
            "and saved filters. Import replaces those from a previously exported file."
        )
        profile_layout.addWidget(self._profile_hint)
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
        body_layout.addWidget(profile_box)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._loadFromSettings()
        self._fitToText()

    # --------------------------------------------------------
    # Method: _setThemeId
    # Purpose: Remember the theme and show its name on the button.
    # --------------------------------------------------------
    def _setThemeId(self, theme_id):
        labels = dict(getThemeChoices())
        self._theme_id = theme_id if theme_id in labels else "dark"
        self._theme_button.setText(labels.get(self._theme_id, "Dark"))

    # --------------------------------------------------------
    # Method: _openThemePreview
    # Purpose: The five-row list. Accept saves the theme at once.
    #          Cancel has already put the previous theme back.
    # --------------------------------------------------------
    def _openThemePreview(self):
        dialog = ThemePreviewDialog(
            getThemeChoices(),
            self._theme_id,
            self._previewTheme,
            self,
        )
        origin = self._theme_button.mapToGlobal(self._theme_button.rect().bottomLeft())
        dialog.move(origin)
        if dialog.exec_() != QDialog.Accepted:
            return
        chosen = dialog.chosenTheme()
        if not chosen:
            return
        self._setThemeId(chosen)
        self._settings.setSetting("theme_mode", chosen)
        self._settings.saveSettings()

    # --------------------------------------------------------
    # Method: _previewTheme
    # Purpose: Ask the main window to paint this theme now.
    # --------------------------------------------------------
    def _previewTheme(self, theme_id):
        if self._on_theme_preview is not None:
            self._on_theme_preview(theme_id)

    # --------------------------------------------------------
    # Method: _hintLabel
    # Purpose: A note under a setting. It uses the form width
    #          and wraps, so the sentence is not cut off.
    # --------------------------------------------------------
    def _hintLabel(self, text):
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return label

    # --------------------------------------------------------
    # Method: _fitToText
    # Purpose: The window is at least as wide as the longest
    #          label and choice, so nothing is clipped.
    # --------------------------------------------------------
    def _fitToText(self):
        metrics = self.fontMetrics()
        longest_label = 0
        labels = (
            "Font size (10 = 100%)",
            "Interface density",
            "Mirror (Ctrl+Shift+M)",
            "Default right path",
            "Search cache",
            "Auto-refresh",
        )
        for text in labels:
            longest_label = max(longest_label, metrics.horizontalAdvance(text))
        longest_field = 0
        for _theme_id, label in getThemeChoices():
            longest_field = max(longest_field, metrics.horizontalAdvance(label))
        for combo in (
            self._icon_set,
            self._ui_scale,
            self._mirror_mode,
        ):
            for index in range(combo.count()):
                longest_field = max(
                    longest_field,
                    metrics.horizontalAdvance(combo.itemText(index)),
                )
        for box in (
            self._show_hidden,
            self._confirm_delete,
            self._check_updates,
            self._cache_scans,
            self._auto_refresh,
        ):
            longest_field = max(
                longest_field,
                metrics.horizontalAdvance(box.text()) + 28,
            )
        width = longest_label + longest_field + 96
        self.setMinimumWidth(max(680, width))
        self.resize(self.minimumWidth(), max(520, self.sizeHint().height()))

    # --------------------------------------------------------
    # Method: _loadFromSettings
    # Purpose: Fill form controls from the settings manager.
    # --------------------------------------------------------
    def _loadFromSettings(self):
        self._setThemeId(self._settings.getSetting("theme_mode", "dark"))
        current_icons = normalizeIconSet(self._settings.getSetting("action_icon_set", "tile"))
        self._icon_set.setCurrentIndex(max(0, self._icon_set.findData(current_icons)))
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
        self._auto_refresh.setChecked(
            self._settings.getSetting("auto_refresh_panels", True)
        )
        self._default_left_path.setText(self._settings.getSetting("default_left_path", "") or "")
        self._default_right_path.setText(self._settings.getSetting("default_right_path", "") or "")
        cur_mirror = self._settings.getSetting("mirror_mode", "to_other")
        self._mirror_mode.setCurrentIndex(max(0, self._mirror_mode.findData(cur_mirror)))

    def values(self):
        return {
            "theme_mode": self._theme_id,
            "action_icon_set": self._icon_set.currentData(),
            "font_size": self._font_size.value(),
            "ui_scale": self._ui_scale.currentData(),
            "show_hidden_files": self._show_hidden.isChecked(),
            "confirm_delete": self._confirm_delete.isChecked(),
            "check_for_updates_on_startup": self._check_updates.isChecked(),
            "cache_recursive_scans": self._cache_scans.isChecked(),
            "auto_refresh_panels": self._auto_refresh.isChecked(),
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
            "Includes settings, bookmarks, libraries, fields, and saved filters.",
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
            "fields, and saved filters with the file contents.\n\nContinue?",
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
