"""
Total Commander Clone - Compress dialog

Asks for the archive name, format, compression level, an optional
password, and which panel receives the new file. RAR is not offered:
there is no free way to create RAR archives.
"""

import os

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from archive_backend import COMPRESS_FORMATS, COMPRESSION_LEVELS


# ------------------------------------------------------------
# Function: defaultArchiveBaseName
# Purpose: Name without a suffix. One selected item uses its own
#          name. Several items use the folder they sit in.
# ------------------------------------------------------------
def defaultArchiveBaseName(paths, folder):
    if len(paths) == 1:
        name = os.path.basename(str(paths[0]).rstrip("/\\"))
        if os.path.isfile(paths[0]):
            stem, _ext = os.path.splitext(name)
            return stem or name or "archive"
        return name or "archive"
    base = os.path.basename(os.path.normpath(folder or ""))
    return base or "archive"


# ------------------------------------------------------------
# Class: CompressDialog
# Purpose: Collect compress options. accept() asks before
#          replacing an archive that is already there.
# ------------------------------------------------------------
class CompressDialog(QDialog):

    def __init__(self, paths, this_folder, other_folder="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compress")
        self.setMinimumWidth(460)
        self._paths = list(paths or [])
        self._this_folder = this_folder or ""
        self._other_folder = other_folder or ""
        self._base_name = defaultArchiveBaseName(self._paths, self._this_folder)
        self._replace = False

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(self)
        form.addRow("Archive name:", self._name)

        self._format = QComboBox(self)
        for key, spec in COMPRESS_FORMATS.items():
            self._format.addItem(spec["label"], key)
        self._format.currentIndexChanged.connect(self._onFormatChanged)
        form.addRow("Format:", self._format)

        self._level = QComboBox(self)
        for key, spec in COMPRESSION_LEVELS.items():
            self._level.addItem(spec["label"], key)
        normal = self._level.findData("normal")
        if normal >= 0:
            self._level.setCurrentIndex(normal)
        form.addRow("Level:", self._level)

        self._password = QLineEdit(self)
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setPlaceholderText("Optional")
        form.addRow("Password:", self._password)

        self._destination = QComboBox(self)
        self._destination.addItem(self._folderLabel("This panel", self._this_folder), self._this_folder)
        if self._other_folder:
            self._destination.addItem(
                self._folderLabel("Other panel", self._other_folder),
                self._other_folder,
            )
        form.addRow("Save in:", self._destination)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._onFormatChanged()

    # --------------------------------------------------------
    # Method: values
    # Purpose: Options after the dialog was accepted.
    #          archive_path is the full file to create.
    #          replace is True when the user agreed to overwrite.
    # --------------------------------------------------------
    def values(self):
        folder = self._destination.currentData() or self._this_folder
        fmt = self._format.currentData() or "zip"
        spec = COMPRESS_FORMATS.get(fmt) or COMPRESS_FORMATS["zip"]
        name = self._fileName(spec["ext"])
        return {
            "archive_path": os.path.join(folder, name) if folder else name,
            "format": fmt,
            "level": self._level.currentData() or "normal",
            "password": self._password.text() if spec.get("password") else "",
            "base_dir": self._this_folder,
            "replace": self._replace,
        }

    def accept(self):
        chosen = self.values()
        target = chosen["archive_path"]
        if not chosen["format"] or not os.path.basename(target):
            QMessageBox.warning(self, "Compress", "Enter a name for the archive.")
            return
        if os.path.lexists(target):
            reply = QMessageBox.question(
                self,
                "Compress",
                f"Replace this file?\n\n{target}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._replace = True
        super().accept()

    def _onFormatChanged(self):
        fmt = self._format.currentData() or "zip"
        spec = COMPRESS_FORMATS.get(fmt) or COMPRESS_FORMATS["zip"]
        self._name.setText(self._base_name + spec["ext"])
        self._password.setEnabled(bool(spec.get("password")))
        if not spec.get("password"):
            self._password.clear()

    def _fileName(self, ext):
        name = self._name.text().strip()
        if not name:
            name = self._base_name
        lower = name.lower()
        if not lower.endswith(ext.lower()):
            # Drop a suffix left over from another format, then add this one.
            for spec in COMPRESS_FORMATS.values():
                if lower.endswith(spec["ext"].lower()):
                    name = name[: -len(spec["ext"])]
                    break
            name = name + ext
        return name

    def _folderLabel(self, title, folder):
        shown = folder or ""
        if len(shown) > 48:
            shown = "…" + shown[-45:]
        return f"{title}  ({shown})" if shown else title
