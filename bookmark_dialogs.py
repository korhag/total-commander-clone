"""
Waypane - Bookmark Dialogs
Small dialogs for editing bookmark name and path.
"""

import os

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QPushButton, QVBoxLayout,
)


# ------------------------------------------------------------
# Class: BookmarkEditDialog
# Purpose: Edit a bookmark's display name and target path.
# ------------------------------------------------------------
class BookmarkEditDialog(QDialog):

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, name="", path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Bookmark")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(name)
        form.addRow("Name:", self._name)

        path_row = QHBoxLayout()
        self._path = QLineEdit(path)
        browse_folder_btn = QPushButton("Browse folder...")
        browse_folder_btn.clicked.connect(self._browseForFolder)
        browse_file_btn = QPushButton("Browse file...")
        browse_file_btn.clicked.connect(self._browseForFile)
        path_row.addWidget(self._path, 1)
        path_row.addWidget(browse_folder_btn)
        path_row.addWidget(browse_file_btn)
        form.addRow("Path:", path_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)

    # --------------------------------------------------------
    # Method: values
    # --------------------------------------------------------
    def values(self):
        return {
            "name": self._name.text().strip(),
            "path": self._path.text().strip(),
        }

    # --------------------------------------------------------
    # Method: _browseForFolder
    # --------------------------------------------------------
    def _browseForFolder(self):
        start_dir = self._path.text().strip()
        if start_dir and os.path.isfile(start_dir):
            start_dir = os.path.dirname(start_dir)
        chosen = QFileDialog.getExistingDirectory(self, "Select folder", start_dir or "")
        if chosen:
            self._path.setText(chosen)

    # --------------------------------------------------------
    # Method: _browseForFile
    # --------------------------------------------------------
    def _browseForFile(self):
        start_dir = self._path.text().strip()
        if start_dir and os.path.isdir(start_dir):
            start_dir = os.path.join(start_dir, "")
        chosen, _ = QFileDialog.getOpenFileName(self, "Select file", start_dir or "")
        if chosen:
            self._path.setText(chosen)
