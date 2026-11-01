"""
Total Commander Clone - Library Dialogs
Dialogs for adding a root and editing fields on one or more folders.
"""

import os
import uuid

from PyQt5.QtCore import Qt, QStringListModel, QTimer
from PyQt5.QtWidgets import (
    QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from dialog_utils import askText
from library_manager import foldText


# ------------------------------------------------------------
# Class: FoldingCompleter
# Purpose: Suggest text using Turkish-aware matching. The popup
#          shows only the rows foldText keeps, because Qt's own
#          filter does not treat İ, I, and ı as the same letter.
# ------------------------------------------------------------
class FoldingCompleter(QCompleter):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._options = []
        self._model = QStringListModel(self)
        self.setModel(self._model)
        self.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.setCaseSensitivity(Qt.CaseInsensitive)

    # --------------------------------------------------------
    # Method: setOptions
    # Purpose: Replace the full suggestion list.
    # --------------------------------------------------------
    def setOptions(self, options):
        self._options = [option for option in (options or []) if str(option).strip()]
        self.setPrefix("")

    # --------------------------------------------------------
    # Method: setPrefix
    # Purpose: Keep suggestions that contain the typed text.
    # --------------------------------------------------------
    def setPrefix(self, text):
        needle = foldText(text)
        if not needle:
            shown = list(self._options)
        else:
            shown = [option for option in self._options if needle in foldText(option)]
        self._model.setStringList(shown)
        popup = self.popup()
        if not text or not shown:
            if popup is not None:
                popup.hide()
            return
        widget = self.widget()
        if widget is not None and widget.isVisible():
            self.complete()


# ------------------------------------------------------------
# Class: LibraryRootDialog
# Purpose: Add a folder as a root of an existing library.
# ------------------------------------------------------------
class LibraryRootDialog(QDialog):

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, libraries, initial_root_path="", initial_library_id="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Root")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._library = QComboBox()
        self._library.setObjectName("libraryPicker")
        for library in libraries or []:
            self._library.addItem(library.get("name", "Library"), library.get("id", ""))
        if initial_library_id:
            index = self._library.findData(initial_library_id)
            if index >= 0:
                self._library.setCurrentIndex(index)
        form.addRow("Library:", self._library)

        self._root_name = QLineEdit()
        self._root_name.setPlaceholderText("Optional. Defaults to the folder name.")
        form.addRow("Root name:", self._root_name)

        root_row = QHBoxLayout()
        self._root_path = QLineEdit(initial_root_path)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browseForRoot)
        root_row.addWidget(self._root_path, 1)
        root_row.addWidget(browse_btn)
        form.addRow("Root folder:", root_row)

        hint = QLabel(
            "This folder becomes a root of the library. "
            "Folders inside it can have fields."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    # --------------------------------------------------------
    # Method: values
    # --------------------------------------------------------
    def values(self):
        return {
            "library_id": self._library.currentData() or "",
            "root_name": self._root_name.text().strip(),
            "root_path": self._root_path.text().strip(),
        }

    # --------------------------------------------------------
    # Method: _browseForRoot
    # --------------------------------------------------------
    def _browseForRoot(self):
        start_dir = self._root_path.text().strip() or ""
        chosen = QFileDialog.getExistingDirectory(self, "Select library root", start_dir)
        if chosen:
            self._root_path.setText(chosen)


# ------------------------------------------------------------
# Class: _ValueRow
# Purpose: One value on a folder, with remove and double-click edit.
# ------------------------------------------------------------
class _ValueRow(QWidget):

    def __init__(self, value, on_click, on_edit, on_remove, parent=None):
        super().__init__(parent)
        self._value = value
        self._on_click = on_click
        self._on_edit = on_edit
        self.setFocusPolicy(Qt.ClickFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(value)
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        remove_btn = QPushButton("×")
        remove_btn.setObjectName("removeFieldValue")
        remove_btn.setFixedWidth(28)
        remove_btn.setToolTip("Remove this value")
        remove_btn.clicked.connect(lambda: on_remove(value))
        layout.addWidget(self._label, 1)
        layout.addWidget(remove_btn)

    def mousePressEvent(self, event):
        self._on_click(self._value)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_edit(self._value)
            return
        super().mouseDoubleClickEvent(event)

    def setChosen(self, chosen):
        if chosen:
            self.setStyleSheet(
                "background-color: palette(highlight); color: palette(highlighted-text);"
            )
        else:
            self.setStyleSheet("")


# ------------------------------------------------------------
# Function: _folderHeaderText
# Purpose: One path, or a count plus each folder name.
# ------------------------------------------------------------
def _folderHeaderText(folder_paths):
    if len(folder_paths) == 1:
        return folder_paths[0]
    names = []
    for path in folder_paths:
        name = os.path.basename(str(path).rstrip("/\\")) or str(path)
        names.append(name)
    count = len(folder_paths)
    noun = "folder" if count == 1 else "folders"
    return f"{count} {noun} selected\n" + "\n".join(names)


# ------------------------------------------------------------
# Class: FolderFieldsDialog
# Purpose: Pick existing fields or create one, then edit the
#          values stored on the selected folders.
# ------------------------------------------------------------
class FolderFieldsDialog(QDialog):

    # --------------------------------------------------------
    # Method: __init__
    # Input: folder_paths (str or list), fields (list of {id, name}),
    #        current ({id: [values]}), suggestions ({id: [values]})
    # --------------------------------------------------------
    def __init__(self, folder_paths, fields=None, current=None, suggestions=None, parent=None):
        super().__init__(parent)
        if isinstance(folder_paths, str):
            folder_paths = [folder_paths]
        folder_paths = [path for path in (folder_paths or []) if path]
        count = len(folder_paths)
        if count > 1:
            self.setWindowTitle(f"Edit Fields ({count} folders)")
        else:
            self.setWindowTitle("Edit Fields")
        self.setMinimumSize(760, 480)
        self._fields = [dict(field) for field in (fields or [])]
        self._current = {
            field_id: list(values)
            for field_id, values in (current or {}).items()
        }
        self._suggestions = suggestions or {}
        self._created = []
        self._selected = None
        self._value_edits = {}

        layout = QVBoxLayout(self)
        path_label = QLabel(_folderHeaderText(folder_paths))
        path_label.setObjectName("folderHeader")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Fields"))
        self._search = QLineEdit()
        self._search.setObjectName("fieldSearch")
        self._search.setPlaceholderText("Search or create a field")
        self._search.textChanged.connect(self._rebuildFieldList)
        self._search.returnPressed.connect(self._onSearchReturn)
        left_layout.addWidget(self._search)
        self._field_list = QListWidget()
        self._field_list.setObjectName("knownFields")
        self._field_list.itemClicked.connect(self._onFieldClicked)
        left_layout.addWidget(self._field_list, 1)
        self._create_btn = QPushButton("Create field")
        self._create_btn.setObjectName("createFieldButton")
        self._create_btn.clicked.connect(self._onCreateField)
        left_layout.addWidget(self._create_btn)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("This folder"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._assigned_host = QWidget()
        self._assigned_layout = QVBoxLayout(self._assigned_host)
        self._assigned_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._assigned_host)
        right_layout.addWidget(scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([280, 460])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuildFieldList()
        self._rebuildAssigned()
        QTimer.singleShot(0, self._focusSearch)

    # --------------------------------------------------------
    # Method: values
    # Purpose: Fields on this folder, plus any fields created here.
    # --------------------------------------------------------
    def values(self):
        return {
            "fields": {
                field_id: list(values)
                for field_id, values in self._current.items()
            },
            "created": [dict(item) for item in self._created],
        }

    # --------------------------------------------------------
    # Method: valueEditFor
    # Purpose: The value box for a field name. Tests and focus use it.
    # --------------------------------------------------------
    def valueEditFor(self, field_name):
        field = self._fieldByFoldedName(field_name)
        if field is None:
            return None
        return self._value_edits.get(field["id"])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self._selected:
            field_id, value = self._selected
            self._removeValue(field_id, value)
            return
        super().keyPressEvent(event)

    def _focusSearch(self):
        self.activateWindow()
        self._search.setFocus()

    def _fieldById(self, field_id):
        for field in self._fields:
            if field.get("id") == field_id:
                return field
        return None

    def _fieldByFoldedName(self, name):
        folded = foldText(name)
        for field in self._fields:
            if foldText(field.get("name", "")) == folded:
                return field
        return None

    # --------------------------------------------------------
    # Method: _rebuildFieldList
    # Purpose: Show library fields that match the search box.
    # --------------------------------------------------------
    def _rebuildFieldList(self):
        query = foldText(self._search.text())
        self._field_list.clear()
        for field in sorted(self._fields, key=lambda item: foldText(item.get("name", ""))):
            name = field.get("name", "")
            if query and query not in foldText(name):
                continue
            label = name
            if field.get("id") in self._current:
                label = f"{name}  ✓"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, field.get("id", ""))
            self._field_list.addItem(item)

        typed = self._search.text().strip()
        can_create = bool(typed) and self._fieldByFoldedName(typed) is None
        self._create_btn.setEnabled(can_create)
        if can_create:
            self._create_btn.setText(f'Create field "{typed}"')
        else:
            self._create_btn.setText("Create field")

    def _onFieldClicked(self, item):
        field_id = item.data(Qt.UserRole) or ""
        if field_id:
            self._addField(field_id)

    def _onSearchReturn(self):
        name = self._search.text().strip()
        if not name:
            return
        existing = self._fieldByFoldedName(name)
        if existing is not None:
            self._search.clear()
            self._addField(existing["id"])
            return
        self._onCreateField()

    def _onCreateField(self):
        name = self._search.text().strip()
        if not name:
            return
        existing = self._fieldByFoldedName(name)
        if existing is not None:
            self._search.clear()
            self._addField(existing["id"])
            return
        temp_id = "new:" + str(uuid.uuid4())
        self._fields.append({"id": temp_id, "name": name})
        self._created.append({"temp_id": temp_id, "name": name})
        self._search.clear()
        self._addField(temp_id)

    def _addField(self, field_id):
        self._current.setdefault(field_id, [])
        self._rebuildFieldList()
        self._rebuildAssigned(field_id)

    # --------------------------------------------------------
    # Method: _rebuildAssigned
    # Purpose: Draw the fields currently on this folder.
    # --------------------------------------------------------
    def _rebuildAssigned(self, focus_field_id=""):
        self._clearLayout(self._assigned_layout)
        self._value_edits = {}
        if not self._current:
            hint = QLabel("Click a field to add it to this folder.")
            hint.setWordWrap(True)
            self._assigned_layout.addWidget(hint)
        for field_id in list(self._current.keys()):
            field = self._fieldById(field_id)
            if field is None:
                continue
            self._assigned_layout.addWidget(self._buildFieldBlock(field))
        self._assigned_layout.addStretch(1)
        edit = self._value_edits.get(focus_field_id)
        if edit is not None:
            edit.setFocus()

    def _buildFieldBlock(self, field):
        field_id = field["id"]
        block = QWidget()
        block.setObjectName(f"assignedField:{field_id}")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 6, 0, 6)

        header = QHBoxLayout()
        title = QLabel(field.get("name", ""))
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title, 1)
        remove_btn = QPushButton("Remove")
        remove_btn.setToolTip("Remove this field from the folder")
        remove_btn.clicked.connect(lambda: self._removeField(field_id))
        header.addWidget(remove_btn)
        layout.addLayout(header)

        for value in self._current.get(field_id, []):
            row = _ValueRow(
                value,
                lambda text, fid=field_id: self._chooseValue(fid, text),
                lambda text, fid=field_id: self._editValue(fid, text),
                lambda text, fid=field_id: self._removeValue(fid, text),
            )
            row.setChosen(self._selected == (field_id, value))
            layout.addWidget(row)

        add_row = QHBoxLayout()
        edit = QLineEdit()
        edit.setObjectName(f"fieldValueEdit:{field_id}")
        edit.setPlaceholderText("Add a value")
        completer = FoldingCompleter(edit)
        edit.setCompleter(completer)
        completer.setOptions(self._suggestions.get(field_id, []))
        edit.textEdited.connect(lambda text, box=completer: box.setPrefix(text))
        edit.returnPressed.connect(lambda: self._commitValue(field_id))
        completer.activated[str].connect(
            lambda text, fid=field_id: self._commitSuggestion(fid, text)
        )
        self._value_edits[field_id] = edit
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(lambda checked: self._commitValue(field_id))
        add_row.addWidget(edit, 1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        return block

    def _chooseValue(self, field_id, value):
        self._selected = (field_id, value)
        self._rebuildAssigned(field_id)

    def _editValue(self, field_id, value):
        updated = askText(self, "Edit value", "Value:", value)
        if not updated:
            return
        values = self._current.get(field_id, [])
        if foldText(updated) != foldText(value) and any(
            foldText(item) == foldText(updated) for item in values
        ):
            values = [item for item in values if foldText(item) != foldText(value)]
        else:
            values = [updated if foldText(item) == foldText(value) else item for item in values]
        self._current[field_id] = values
        self._selected = (field_id, updated)
        self._rebuildAssigned(field_id)

    def _removeValue(self, field_id, value):
        values = self._current.get(field_id, [])
        self._current[field_id] = [
            item for item in values if foldText(item) != foldText(value)
        ]
        if self._selected == (field_id, value):
            self._selected = None
        self._rebuildAssigned(field_id)

    def _removeField(self, field_id):
        self._current.pop(field_id, None)
        if self._selected and self._selected[0] == field_id:
            self._selected = None
        self._rebuildFieldList()
        self._rebuildAssigned()

    def _commitSuggestion(self, field_id, text):
        edit = self._value_edits.get(field_id)
        if edit is not None:
            edit.setText(text)
        self._commitValue(field_id)

    def _commitValue(self, field_id):
        edit = self._value_edits.get(field_id)
        if edit is None:
            return
        text = edit.text().strip()
        if not text:
            return
        values = self._current.setdefault(field_id, [])
        if foldText(text) not in {foldText(item) for item in values}:
            values.append(text)
        self._rebuildAssigned(field_id)

    def _clearLayout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                self._clearLayout(child)
