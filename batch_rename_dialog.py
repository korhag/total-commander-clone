"""
Total Commander Clone - Batch Rename Dialog
Provides a multi-rename tool for bulk renaming files using
find/replace, prefix/suffix, and regex patterns with a live
preview table showing before/after names.
"""

import os
import re

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QCheckBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QMessageBox,
    QComboBox, QAbstractItemView, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from theme import themeColor


# ============================================================
# Class: BatchRenameDialog
# Purpose: Modal dialog for renaming multiple files at once.
#          Supports find/replace (plain text or regex),
#          add/remove prefix and suffix, and shows a live
#          preview of all changes before applying.
# ============================================================
class BatchRenameDialog(QDialog):

    # --------------------------------------------------------
    # Method: __init__
    # Input:  file_entries (list[dict]) - entries from FileSystemModel
    #         current_dir (str) - directory containing the files
    #         parent - parent widget
    # --------------------------------------------------------
    def __init__(self, file_entries, current_dir, parent=None):
        super().__init__(parent)
        self._entries = file_entries
        self._current_dir = current_dir
        self._renamed_count = 0

        self.setWindowTitle("Batch Rename")
        self.setMinimumSize(750, 550)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._initUI()
        self._connectSignals()
        self._updatePreview()

    # --------------------------------------------------------
    # Method: _initUI
    # --------------------------------------------------------
    def _initUI(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Find / Replace group ---
        find_group = QGroupBox("Find and Replace")
        find_layout = QGridLayout(find_group)
        find_layout.setSpacing(8)

        find_layout.addWidget(QLabel("Find:"), 0, 0)
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText('e.g.  _  or  \\d+  (regex)')
        find_layout.addWidget(self._find_edit, 0, 1)

        find_layout.addWidget(QLabel("Replace:"), 1, 0)
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText('e.g.  (space)  or  $1')
        find_layout.addWidget(self._replace_edit, 1, 1)

        options_layout = QHBoxLayout()
        self._chk_regex = QCheckBox("Regex")
        self._chk_regex.setToolTip("Treat Find pattern as a regular expression")
        self._chk_case = QCheckBox("Case sensitive")
        self._chk_case.setChecked(True)
        self._chk_ext = QCheckBox("Include extension")
        self._chk_ext.setToolTip("Apply find/replace to the file extension too")
        options_layout.addWidget(self._chk_regex)
        options_layout.addWidget(self._chk_case)
        options_layout.addWidget(self._chk_ext)
        options_layout.addStretch()
        find_layout.addLayout(options_layout, 2, 0, 1, 2)

        layout.addWidget(find_group)

        # --- Prefix / Suffix group ---
        affix_group = QGroupBox("Add Prefix / Suffix")
        affix_layout = QGridLayout(affix_group)
        affix_layout.setSpacing(8)

        affix_layout.addWidget(QLabel("Add prefix:"), 0, 0)
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText("Text to add before the name")
        affix_layout.addWidget(self._prefix_edit, 0, 1)

        affix_layout.addWidget(QLabel("Add suffix:"), 1, 0)
        self._suffix_edit = QLineEdit()
        self._suffix_edit.setPlaceholderText("Text to add after the name (before extension)")
        affix_layout.addWidget(self._suffix_edit, 1, 1)

        layout.addWidget(affix_group)

        # --- Preview table ---
        preview_label = QLabel("Preview:")
        preview_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(preview_label)

        self._preview_table = QTableWidget()
        self._preview_table.setObjectName("batchPreview")
        self._preview_table.setColumnCount(2)
        self._preview_table.setHorizontalHeaderLabels(["Original Name", "New Name"])
        self._preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.verticalHeader().setVisible(False)

        header = self._preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        layout.addWidget(self._preview_table, 1)

        # --- Summary + buttons ---
        bottom_layout = QHBoxLayout()
        self._summary_label = QLabel("0 files will be renamed")
        bottom_layout.addWidget(self._summary_label)
        bottom_layout.addStretch()

        self._btn_apply = QPushButton("Apply Rename")
        self._btn_apply.setObjectName("accentButton")
        self._btn_apply.setMinimumWidth(130)
        self._btn_apply.clicked.connect(self._onApply)
        bottom_layout.addWidget(self._btn_apply)

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(self._btn_cancel)

        layout.addLayout(bottom_layout)

    # --------------------------------------------------------
    # Method: _connectSignals
    # Purpose: Connects all input fields to live preview updates.
    # --------------------------------------------------------
    def _connectSignals(self):
        self._find_edit.textChanged.connect(self._updatePreview)
        self._replace_edit.textChanged.connect(self._updatePreview)
        self._prefix_edit.textChanged.connect(self._updatePreview)
        self._suffix_edit.textChanged.connect(self._updatePreview)
        self._chk_regex.stateChanged.connect(self._updatePreview)
        self._chk_case.stateChanged.connect(self._updatePreview)
        self._chk_ext.stateChanged.connect(self._updatePreview)

    # --------------------------------------------------------
    # Method: _computeNewName
    # Purpose: Applies all rename rules to a single filename
    #          and returns the new name.
    # Input:  original (str) - the original filename
    #         is_dir (bool) - whether it's a directory
    # Output: str - the transformed filename
    # --------------------------------------------------------
    def _computeNewName(self, original, is_dir):
        find_text = self._find_edit.text()
        replace_text = self._replace_edit.text()
        use_regex = self._chk_regex.isChecked()
        case_sensitive = self._chk_case.isChecked()
        include_ext = self._chk_ext.isChecked()
        prefix = self._prefix_edit.text()
        suffix = self._suffix_edit.text()

        if is_dir or include_ext:
            stem = original
            ext = ""
        else:
            dot_pos = original.rfind(".")
            if dot_pos > 0:
                stem = original[:dot_pos]
                ext = original[dot_pos:]
            else:
                stem = original
                ext = ""

        if find_text:
            try:
                if use_regex:
                    flags = 0 if case_sensitive else re.IGNORECASE
                    stem = re.sub(find_text, replace_text, stem, flags=flags)
                    if include_ext and ext:
                        ext = re.sub(find_text, replace_text, ext, flags=flags)
                else:
                    if case_sensitive:
                        stem = stem.replace(find_text, replace_text)
                        if include_ext and ext:
                            ext = ext.replace(find_text, replace_text)
                    else:
                        stem = self._caseInsensitiveReplace(stem, find_text, replace_text)
                        if include_ext and ext:
                            ext = self._caseInsensitiveReplace(ext, find_text, replace_text)
            except re.error:
                pass

        if prefix:
            stem = prefix + stem
        if suffix:
            stem = stem + suffix

        return stem + ext

    # --------------------------------------------------------
    # Method: _renameTarget
    # Purpose: Folder and basename to rename. In subfolders mode
    #          entry["name"] is a relative path, so the new name
    #          is computed from the basename and applied in the
    #          file's own directory.
    # --------------------------------------------------------
    def _renameTarget(self, entry):
        raw_name = entry.get("name") or ""
        full_path = entry.get("full_path") or ""
        original = os.path.basename(raw_name) or os.path.basename(full_path)
        if full_path:
            directory = os.path.dirname(full_path)
        else:
            directory = self._current_dir
        return directory, original

    # --------------------------------------------------------
    # Method: _invalidRegexMessage
    # Purpose: Return the regex error text when Find is not a
    #          valid pattern, otherwise an empty string.
    # --------------------------------------------------------
    def _invalidRegexMessage(self):
        if not self._chk_regex.isChecked():
            return ""
        find_text = self._find_edit.text()
        if not find_text:
            return ""
        try:
            re.compile(find_text)
        except re.error as exc:
            return str(exc)
        return ""

    # --------------------------------------------------------
    # Method: _caseInsensitiveReplace
    # Purpose: Plain-text case-insensitive replace that
    #          preserves the rest of the string.
    # --------------------------------------------------------
    def _caseInsensitiveReplace(self, text, find, replace):
        pattern = re.escape(find)
        return re.sub(pattern, replace, text, flags=re.IGNORECASE)

    # --------------------------------------------------------
    # Method: _updatePreview
    # Purpose: Rebuilds the preview table showing original
    #          and new names for every file, highlighting changes.
    # --------------------------------------------------------
    def _updatePreview(self):
        self._preview_table.setRowCount(len(self._entries))
        changed_count = 0
        pattern_error = self._invalidRegexMessage()
        plan = self._planRenames(apply_pattern=not pattern_error)

        for row, item in enumerate(plan):
            original = item["original"]
            new_name = item["new_name"]

            orig_item = QTableWidgetItem(original)
            new_item = QTableWidgetItem(new_name)

            is_changed = (new_name != original)
            if is_changed:
                changed_count += 1
                new_item.setForeground(QColor(themeColor("green", "#a6e3a1")))
            else:
                new_item.setForeground(QColor(themeColor("overlay0", "#6c7086")))

            self._preview_table.setItem(row, 0, orig_item)
            self._preview_table.setItem(row, 1, new_item)

        self._renamed_count = changed_count
        if pattern_error:
            self._summary_label.setText(f"Invalid regex: {pattern_error}")
            self._btn_apply.setEnabled(False)
        else:
            self._summary_label.setText(
                f"{changed_count} of {len(self._entries)} file(s) will be renamed"
            )
            self._btn_apply.setEnabled(changed_count > 0)

    # --------------------------------------------------------
    # Method: _onApply
    # Purpose: Applies all renames to the filesystem. Handles
    #          name conflicts with auto-incrementing.
    # --------------------------------------------------------
    def _onApply(self):
        if self._invalidRegexMessage():
            self._updatePreview()
            return

        successes = 0
        errors = []

        for item in self._planRenames():
            if item["new_name"] == item["original"]:
                continue
            try:
                os.rename(item["old_path"], item["new_path"])
                successes += 1
            except OSError as e:
                errors.append(f"{item['original']}: {e}")

        if errors:
            error_text = "\n".join(errors[:15])
            if len(errors) > 15:
                error_text += f"\n... and {len(errors) - 15} more"
            QMessageBox.warning(
                self, "Rename Errors",
                f"Renamed {successes} file(s) but {len(errors)} failed:\n\n{error_text}"
            )
        else:
            QMessageBox.information(
                self, "Batch Rename",
                f"Successfully renamed {successes} file(s)."
            )

        self.accept()

    # --------------------------------------------------------
    # Method: _planRenames
    # Purpose: Final name for every entry, in order, with name
    #          collisions already resolved (against files on disk
    #          and against names claimed earlier in the batch).
    #          Preview and apply both use this, so what the user
    #          sees is exactly what gets written.
    # Input:  apply_pattern (bool) - False keeps every original name.
    # Output: list of dicts: original, new_name, old_path, new_path.
    # --------------------------------------------------------
    def _planRenames(self, apply_pattern=True):
        plan = []
        claimed = set()
        for entry in self._entries:
            directory, original = self._renameTarget(entry)
            old_path = os.path.join(directory, original)
            new_name = original
            if apply_pattern:
                candidate = self._computeNewName(original, entry["is_dir"])
                if candidate.strip():
                    new_name = candidate
            if new_name != original:
                new_name = self._resolveConflict(directory, new_name, old_path, claimed)
            new_path = os.path.join(directory, new_name)
            if new_name != original:
                claimed.add(os.path.normcase(new_path))
            plan.append({
                "original": original,
                "new_name": new_name,
                "old_path": old_path,
                "new_path": new_path,
            })
        return plan

    # --------------------------------------------------------
    # Method: _resolveConflict
    # Purpose: Auto-increments a filename until it is free on disk
    #          and not already claimed in this batch. A case-only
    #          change of the file's own name is not a conflict.
    # --------------------------------------------------------
    def _resolveConflict(self, directory, name, old_path, claimed):
        def taken(candidate):
            path = os.path.join(directory, candidate)
            key = os.path.normcase(path)
            if key in claimed:
                return True
            return os.path.exists(path) and key != os.path.normcase(old_path)

        base, ext = os.path.splitext(name)
        counter = 1
        candidate = name
        while taken(candidate):
            candidate = f"{base} ({counter}){ext}"
            counter += 1
        return candidate

    # --------------------------------------------------------
    # Public: how many files were renamed (after dialog closes)
    # --------------------------------------------------------
    def renamedCount(self):
        return self._renamed_count
