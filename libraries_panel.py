"""
Total Commander Clone - Libraries Panel
Sidebar for the active library: roots, field filters, and matching folders.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QScrollArea, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from library_dialogs import FoldingCompleter
from library_manager import foldText, matchesFolderFilters


ROLE_ITEM_TYPE = Qt.UserRole
ROLE_LIBRARY_ID = Qt.UserRole + 1
ROLE_ROOT_ID = Qt.UserRole + 2
ROLE_PATH = Qt.UserRole + 3


# ------------------------------------------------------------
# Class: _FieldFilterRow
# Purpose: One field in the middle panel. Typing filters live.
#          Enter, or a suggestion, keeps that text as a term.
# ------------------------------------------------------------
class _FieldFilterRow(QWidget):

    changed = pyqtSignal()
    menuRequested = pyqtSignal(str, object)

    def __init__(self, field, suggestions, terms, draft, parent=None):
        super().__init__(parent)
        self._field_id = field.get("id", "")
        self._field_name = field.get("name", "")
        self._terms = list(terms or [])
        self.setObjectName(f"fieldFilterRow:{self._field_id}")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emitMenu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        self._name = QLabel(self._field_name)
        self._name.setStyleSheet("font-weight: bold;")
        self._name.setContextMenuPolicy(Qt.CustomContextMenu)
        self._name.customContextMenuRequested.connect(self._emitMenu)
        layout.addWidget(self._name)

        self._edit = QLineEdit(draft or "")
        self._edit.setObjectName(f"fieldFilterEdit:{self._field_id}")
        self._edit.setPlaceholderText("Filter values")
        self._completer = FoldingCompleter(self._edit)
        self._edit.setCompleter(self._completer)
        self._completer.setOptions(suggestions or [])
        self._edit.textEdited.connect(self._onEdited)
        self._edit.returnPressed.connect(self._onCommit)
        self._completer.activated[str].connect(self._onPicked)
        layout.addWidget(self._edit)

        self._chips = QVBoxLayout()
        self._chips.setContentsMargins(0, 0, 0, 0)
        self._chips.setSpacing(2)
        layout.addLayout(self._chips)
        self._rebuildChips()

    def fieldId(self):
        return self._field_id

    def fieldName(self):
        return self._field_name

    def committedTerms(self):
        return list(self._terms)

    def draft(self):
        return self._edit.text()

    def termsForFilter(self):
        terms = list(self._terms)
        typed = self._edit.text().strip()
        if typed and foldText(typed) not in {foldText(term) for term in terms}:
            terms.append(typed)
        return terms

    def clearFilter(self):
        self._terms = []
        self._edit.clear()
        self._rebuildChips()
        self.changed.emit()

    def _emitMenu(self, pos):
        widget = self.sender() if self.sender() is not None else self
        self.menuRequested.emit(self._field_id, widget.mapToGlobal(pos))

    def _onEdited(self, text):
        self._completer.setPrefix(text)
        self.changed.emit()

    def _onPicked(self, text):
        self._edit.setText(text)
        self._onCommit()

    def _onCommit(self):
        text = self._edit.text().strip()
        if not text:
            return
        if foldText(text) not in {foldText(term) for term in self._terms}:
            self._terms.append(text)
        self._edit.clear()
        self._rebuildChips()
        self.changed.emit()

    def _rebuildChips(self):
        while self._chips.count():
            item = self._chips.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for term in self._terms:
            button = QPushButton(f"{term}  ×")
            button.setObjectName("bookmarksToolButton")
            button.setToolTip("Remove this filter")
            button.clicked.connect(lambda checked, value=term: self._removeTerm(value))
            self._chips.addWidget(button)

    def _removeTerm(self, term):
        self._terms = [item for item in self._terms if foldText(item) != foldText(term)]
        self._rebuildChips()
        self.changed.emit()


# ------------------------------------------------------------
# Class: LibrariesPanel
# Purpose: Active library, its roots, a field filter, and the
#          folders that match. Signals ask the main window to
#          change saved data.
# ------------------------------------------------------------
class LibrariesPanel(QWidget):

    activeLibraryChanged = pyqtSignal(str)
    navigateRequested = pyqtSignal(str)
    navigateOtherRequested = pyqtSignal(str)
    addLibraryRequested = pyqtSignal()
    addRootRequested = pyqtSignal()
    scanLibrariesRequested = pyqtSignal()
    importLibraryRequested = pyqtSignal()
    exportLibraryRequested = pyqtSignal(str)
    renameLibraryRequested = pyqtSignal(str)
    deleteLibraryRequested = pyqtSignal(str)
    renameRootRequested = pyqtSignal(str, str)
    locateRootRequested = pyqtSignal(str, str)
    removeRootRequested = pyqtSignal(str, str)
    editFieldsRequested = pyqtSignal(str)
    createFieldRequested = pyqtSignal()
    renameFieldRequested = pyqtSignal(str)
    deleteFieldRequested = pyqtSignal(str)

    # --------------------------------------------------------
    # Method: __init__
    # --------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self._libraries = []
        self._folders = []
        self._fields = []
        self._suggestions = {}
        self._rows = []
        self._selected_library_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("Libraries")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(title)

        first_row = QHBoxLayout()
        first_row.setSpacing(4)
        self._btn_add_library = self._toolButton(
            "Add library",
            "Add library\n\nCreate a library. Roots and fields belong to it.",
            self.addLibraryRequested.emit,
        )
        self._btn_add_root = self._toolButton(
            "Add root",
            "Add root\n\nAdd a folder to the active library.",
            self.addRootRequested.emit,
        )
        first_row.addWidget(self._btn_add_library)
        first_row.addWidget(self._btn_add_root)
        first_row.addStretch()
        layout.addLayout(first_row)

        second_row = QHBoxLayout()
        second_row.setSpacing(4)
        self._btn_scan = self._toolButton(
            "Scan",
            "Scan\n\nLook for library roots that moved.",
            self.scanLibrariesRequested.emit,
        )
        self._btn_import = self._toolButton(
            "Import",
            "Import\n\nLoad a library file and find its roots on this computer.",
            self.importLibraryRequested.emit,
        )
        self._btn_export = self._toolButton(
            "Export",
            "Export\n\nSave the active library to a file.",
            lambda: self.exportLibraryRequested.emit(self._selected_library_id),
        )
        second_row.addWidget(self._btn_scan)
        second_row.addWidget(self._btn_import)
        second_row.addWidget(self._btn_export)
        second_row.addStretch()
        layout.addLayout(second_row)

        self._tree = QTreeWidget()
        self._tree.setObjectName("libraryTree")
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._onTreeMenu)
        self._tree.itemClicked.connect(self._onTreeClicked)
        self._tree.itemDoubleClicked.connect(self._onTreeDoubleClicked)
        layout.addWidget(self._tree, 1)

        self._fields_label = QLabel("Fields")
        layout.addWidget(self._fields_label)

        self._field_search = QLineEdit()
        self._field_search.setObjectName("libraryFieldSearch")
        self._field_search.setPlaceholderText("Search fields")
        self._field_search.textChanged.connect(self._applyFieldSearch)
        layout.addWidget(self._field_search)

        self._fields_host = QWidget()
        self._fields_host.setContextMenuPolicy(Qt.CustomContextMenu)
        self._fields_host.customContextMenuRequested.connect(self._onFieldsBackgroundMenu)
        self._fields_layout = QVBoxLayout(self._fields_host)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(0)
        self._fields_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._fields_host)
        layout.addWidget(scroll, 1)

        self._results_label = QLabel("Matching folders (0)")
        layout.addWidget(self._results_label)

        self._results_list = QListWidget()
        self._results_list.setObjectName("libraryResults")
        self._results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._results_list.customContextMenuRequested.connect(self._onResultMenu)
        self._results_list.itemDoubleClicked.connect(self._onResultDoubleClicked)
        layout.addWidget(self._results_list, 1)

    # --------------------------------------------------------
    # Method: setData
    # Purpose: Show one library's roots, fields, and folders.
    #          Filter text the user already typed is kept.
    # --------------------------------------------------------
    def setData(self, libraries, folders, fields, suggestions=None, selected_library_id=""):
        previous_terms = {row.fieldId(): row.committedTerms() for row in self._rows}
        previous_drafts = {row.fieldId(): row.draft() for row in self._rows}
        self._libraries = libraries or []
        self._folders = folders or []
        self._fields = fields or []
        self._suggestions = suggestions or {}

        available = {library.get("id", "") for library in self._libraries}
        chosen = selected_library_id if selected_library_id in available else ""
        if not chosen and self._libraries:
            chosen = self._libraries[0].get("id", "")
        changed = chosen != self._selected_library_id
        self._selected_library_id = chosen

        self._rebuildTree()
        self._rebuildFieldRows(previous_terms, previous_drafts)
        self._rebuildResults()
        if changed:
            self.activeLibraryChanged.emit(chosen)

    def selectedLibraryId(self):
        return self._selected_library_id

    def _toolButton(self, text, tip, callback):
        button = QPushButton(text)
        button.setObjectName("bookmarksToolButton")
        button.setToolTip(tip)
        button.clicked.connect(callback)
        return button

    # --------------------------------------------------------
    # Method: _rebuildTree
    # Purpose: Libraries and their roots. The active library is bold.
    # --------------------------------------------------------
    def _rebuildTree(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        current = None
        for library in self._libraries:
            library_id = library.get("id", "")
            root_count = len(library.get("roots", []))
            library_item = QTreeWidgetItem([f"{library.get('name', 'Library')} ({root_count})"])
            library_item.setData(0, ROLE_ITEM_TYPE, "library")
            library_item.setData(0, ROLE_LIBRARY_ID, library_id)
            font = library_item.font(0)
            font.setBold(library_id == self._selected_library_id)
            library_item.setFont(0, font)
            library_item.setExpanded(True)
            self._tree.addTopLevelItem(library_item)
            if library_id == self._selected_library_id:
                current = library_item

            for root in library.get("roots", []):
                suffix = "" if root.get("is_available") else " [offline]"
                root_item = QTreeWidgetItem([f"{root.get('name', 'Root')}{suffix}"])
                root_item.setData(0, ROLE_ITEM_TYPE, "root")
                root_item.setData(0, ROLE_LIBRARY_ID, library_id)
                root_item.setData(0, ROLE_ROOT_ID, root.get("id", ""))
                root_item.setData(0, ROLE_PATH, root.get("path", ""))
                tip = root.get("path") or root.get("last_seen_path") or ""
                root_item.setToolTip(0, tip)
                library_item.addChild(root_item)

        if current is not None:
            self._tree.setCurrentItem(current)
        self._tree.blockSignals(False)

    # --------------------------------------------------------
    # Method: _rebuildFieldRows
    # --------------------------------------------------------
    def _rebuildFieldRows(self, previous_terms, previous_drafts):
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._rows = []

        library_name = self._libraryName(self._selected_library_id)
        if self._selected_library_id:
            self._fields_label.setText(f"Fields ({library_name})")
        else:
            self._fields_label.setText("Fields")

        if not self._fields:
            hint = "Create a library first." if not self._selected_library_id else "No fields yet. Right-click to add one."
            label = QLabel(hint)
            label.setWordWrap(True)
            self._fields_layout.addWidget(label)
        else:
            for field in self._fields:
                field_id = field.get("id", "")
                row = _FieldFilterRow(
                    field,
                    self._suggestions.get(field_id, []),
                    previous_terms.get(field_id, []),
                    previous_drafts.get(field_id, ""),
                    self._fields_host,
                )
                row.changed.connect(self._rebuildResults)
                row.menuRequested.connect(self._onFieldMenu)
                self._fields_layout.addWidget(row)
                self._rows.append(row)
        self._fields_layout.addStretch(1)
        self._applyFieldSearch()

    def _applyFieldSearch(self):
        query = foldText(self._field_search.text())
        for row in self._rows:
            row.setVisible(not query or query in foldText(row.fieldName()))

    # --------------------------------------------------------
    # Method: _rebuildResults
    # Purpose: Folders in the active library that match the
    #          field terms currently on screen.
    # --------------------------------------------------------
    def _rebuildResults(self):
        filters = {}
        for row in self._rows:
            terms = row.termsForFilter()
            if terms:
                filters[row.fieldId()] = terms

        self._results_list.clear()
        visible = 0
        for folder in self._folders:
            if not matchesFolderFilters(folder.get("field_map") or {}, filters):
                continue
            item = QListWidgetItem(self._resultLabel(folder))
            item.setData(Qt.UserRole, folder.get("resolved_path", ""))
            item.setToolTip(self._resultTip(folder))
            self._results_list.addItem(item)
            visible += 1
        self._results_label.setText(f"Matching folders ({visible})")

    def _resultLabel(self, folder):
        name = folder.get("display_name") or "Folder"
        root = folder.get("root_name") or ""
        relative = folder.get("relative_path") or ""
        if root and relative:
            place = f"{root} / {relative}"
        else:
            place = root or relative
        label = f"{name} — {place}" if place else name
        if not folder.get("is_available"):
            label += " [offline]"
        return label

    def _resultTip(self, folder):
        lines = []
        path = folder.get("resolved_path") or ""
        if path:
            lines.append(path)
        for field in folder.get("fields") or []:
            values = ", ".join(field.get("values") or [])
            lines.append(f"{field.get('name', '')}: {values}")
        note = (folder.get("note") or "").strip()
        if note:
            lines.append(note)
        if not folder.get("is_available"):
            lines.append("Offline")
        return "\n".join(lines)

    def _libraryName(self, library_id):
        for library in self._libraries:
            if library.get("id") == library_id:
                return library.get("name", "Library")
        return "Library"

    def _onTreeClicked(self, item, column):
        del column
        item_type = item.data(0, ROLE_ITEM_TYPE)
        library_id = item.data(0, ROLE_LIBRARY_ID) or ""
        if item_type in ("library", "root") and library_id:
            self._setActiveLibrary(library_id)

    def _setActiveLibrary(self, library_id):
        if not library_id or library_id == self._selected_library_id:
            return
        self._selected_library_id = library_id
        self._rebuildTree()
        self.activeLibraryChanged.emit(library_id)

    def _onTreeDoubleClicked(self, item, column):
        del column
        if item.data(0, ROLE_ITEM_TYPE) != "root":
            return
        path = item.data(0, ROLE_PATH) or ""
        if path:
            self.navigateRequested.emit(path)

    def _onResultDoubleClicked(self, item):
        path = item.data(Qt.UserRole) or ""
        if path:
            self.navigateRequested.emit(path)

    # --------------------------------------------------------
    # Menus
    # --------------------------------------------------------
    def _onTreeMenu(self, pos):
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            menu.addAction("New library", self.addLibraryRequested.emit)
            menu.addAction("Import library", self.importLibraryRequested.emit)
            menu.exec_(self._tree.viewport().mapToGlobal(pos))
            return

        item_type = item.data(0, ROLE_ITEM_TYPE)
        library_id = item.data(0, ROLE_LIBRARY_ID) or ""
        if item_type == "library":
            menu.addAction("Rename", lambda: self.renameLibraryRequested.emit(library_id))
            menu.addAction("Export", lambda: self.exportLibraryRequested.emit(library_id))
            menu.addAction("Delete", lambda: self.deleteLibraryRequested.emit(library_id))
        elif item_type == "root":
            root_id = item.data(0, ROLE_ROOT_ID) or ""
            path = item.data(0, ROLE_PATH) or ""
            open_action = menu.addAction("Open", lambda: self.navigateRequested.emit(path))
            open_action.setEnabled(bool(path))
            menu.addAction("Rename", lambda: self.renameRootRequested.emit(library_id, root_id))
            menu.addAction("Locate root...", lambda: self.locateRootRequested.emit(library_id, root_id))
            menu.addAction(
                "Remove from library",
                lambda: self.removeRootRequested.emit(library_id, root_id),
            )
        menu.exec_(self._tree.viewport().mapToGlobal(pos))

    def _onFieldMenu(self, field_id, global_pos):
        menu = QMenu(self)
        menu.addAction("Rename", lambda: self.renameFieldRequested.emit(field_id))
        menu.addAction("Delete", lambda: self.deleteFieldRequested.emit(field_id))
        menu.addAction("Clear filter", lambda: self._clearFieldFilter(field_id))
        menu.addSeparator()
        menu.addAction("New field", self.createFieldRequested.emit)
        menu.exec_(global_pos)

    def _onFieldsBackgroundMenu(self, pos):
        menu = QMenu(self)
        menu.addAction("New field", self.createFieldRequested.emit)
        menu.exec_(self._fields_host.mapToGlobal(pos))

    def _clearFieldFilter(self, field_id):
        for row in self._rows:
            if row.fieldId() == field_id:
                row.clearFilter()
                return

    def _onResultMenu(self, pos):
        item = self._results_list.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.UserRole) or ""
        menu = QMenu(self)
        menu.addAction("Open here", lambda: self.navigateRequested.emit(path))
        menu.addAction("Open in the other panel", lambda: self.navigateOtherRequested.emit(path))
        menu.addAction("Edit Fields...", lambda: self.editFieldsRequested.emit(path))
        menu.exec_(self._results_list.viewport().mapToGlobal(pos))
