"""
Total Commander Clone - Bookmarks Panel
Resizable sidebar with bookmarks and groups: drag-drop reorder,
create group on drop, context menu (edit/update/rename/delete), tooltips with full path.
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QLabel,
    QMenu, QInputDialog, QMessageBox, QApplication, QHeaderView,
    QHBoxLayout, QPushButton, QDialog, QFileDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PyQt5.QtWidgets import QStyle
from PyQt5.QtGui import QDesktopServices

from bookmark_dialogs import BookmarkEditDialog


# Data roles for tree items
ROLE_TYPE = Qt.UserRole
ROLE_PATH = Qt.UserRole + 1
TYPE_BOOKMARK = "bookmark"
TYPE_GROUP = "group"


def _nodeToItem(node, parent_item=None):
    """Create a QTreeWidgetItem from a structure node. parent_item=None for top-level."""
    if node.get("type") == TYPE_BOOKMARK:
        item = QTreeWidgetItem(parent_item, [node.get("name", "")])
        item.setData(0, ROLE_TYPE, TYPE_BOOKMARK)
        path = node.get("path", "")
        item.setData(0, ROLE_PATH, path)
        item.setToolTip(0, path)
        is_file = node.get("kind") == "file" or (path and os.path.isfile(path))
        icon = QApplication.instance().style().standardIcon(
            QStyle.SP_FileIcon if is_file else QStyle.SP_DirIcon
        )
        item.setIcon(0, icon)
        return item
    if node.get("type") == TYPE_GROUP:
        item = QTreeWidgetItem(parent_item, [node.get("name", "")])
        item.setData(0, ROLE_TYPE, TYPE_GROUP)
        item.setFlags(item.flags() | Qt.ItemIsDropEnabled)
        item.setToolTip(0, f"Group: {node.get('name', '')}")
        icon = QApplication.instance().style().standardIcon(QStyle.SP_DirLinkIcon)
        item.setIcon(0, icon)
        item.setExpanded(node.get("expanded", True))
        for child in node.get("children", []):
            _nodeToItem(child, item)
        return item
    return None


def _itemToNode(item):
    """Build a structure node from a QTreeWidgetItem."""
    t = item.data(0, ROLE_TYPE)
    if t == TYPE_BOOKMARK:
        path = item.data(0, ROLE_PATH) or ""
        kind = "file" if path and os.path.isfile(path) else "folder"
        return {
            "type": TYPE_BOOKMARK,
            "name": item.text(0),
            "path": path,
            "kind": kind,
        }
    if t == TYPE_GROUP:
        children = []
        for i in range(item.childCount()):
            children.append(_itemToNode(item.child(i)))
        return {
            "type": TYPE_GROUP,
            "name": item.text(0),
            "expanded": item.isExpanded(),
            "children": children,
        }
    return None


# ------------------------------------------------------------
# Class: BookmarksTreeWidget
# Purpose: Tree with drag-drop; drop on bookmark => create group,
#          drop on group => add as child.
# ------------------------------------------------------------
class BookmarksTreeWidget(QTreeWidget):

    structureChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Bookmarks"])
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setAnimated(True)
        self.setIndentation(14)
        self.setRootIsDecorated(True)
        self.setObjectName("bookmarksTree")
        self._drop_target_item = None
        self._drop_position = None  # "above", "below", or "on"

    def dragMoveEvent(self, event):
        drop_item = self.itemAt(event.pos())
        if drop_item:
            rect = self.visualItemRect(drop_item)
            y = event.pos().y()
            thresh = max(8, rect.height() // 4)
            if y < rect.top() + thresh:
                self._drop_position = "above"
            elif y > rect.bottom() - thresh:
                self._drop_position = "below"
            else:
                self._drop_position = "on"
            self._drop_target_item = drop_item
        else:
            self._drop_target_item = None
            self._drop_position = None
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        drop_item = self._drop_target_item
        moving = self.currentItem()
        drop_pos = self._drop_position
        self._drop_target_item = None
        self._drop_position = None

        if not moving or not drop_item:
            super().dropEvent(event)
            self.structureChanged.emit()
            return

        move_type = moving.data(0, ROLE_TYPE)
        drop_type = drop_item.data(0, ROLE_TYPE)

        if drop_pos in ("above", "below"):
            self._reorderItem(moving, drop_item, drop_pos)
            self.structureChanged.emit()
            return

        if drop_pos == "on":
            if drop_type == TYPE_GROUP:
                if move_type in (TYPE_BOOKMARK, TYPE_GROUP):
                    self._moveUnder(moving, drop_item)
                self.structureChanged.emit()
                return

            if drop_type == TYPE_BOOKMARK and move_type in (TYPE_BOOKMARK, TYPE_GROUP):
                name, ok = QInputDialog.getText(
                    self, "Create Group",
                    "Create a new group containing these items. Group name:",
                    text="New Group"
                )
                if ok and name.strip():
                    self._createGroupWith(drop_item, moving, name.strip())
                event.ignore()
                return

        super().dropEvent(event)
        self.structureChanged.emit()

    def _reorderItem(self, moving, drop_item, position):
        """Move item above or below the drop target (reorder, same or different parent)."""
        src_parent = moving.parent() or self.invisibleRootItem()
        tgt_parent = drop_item.parent() or self.invisibleRootItem()
        clone = self._cloneItem(moving)
        src_parent.removeChild(moving)
        tgt_idx = tgt_parent.indexOfChild(drop_item)
        if tgt_idx < 0:
            tgt_parent.addChild(clone)
            return
        insert_idx = tgt_idx + 1 if position == "below" else tgt_idx
        insert_idx = max(0, min(insert_idx, tgt_parent.childCount()))
        tgt_parent.insertChild(insert_idx, clone)

    def _moveUnder(self, child_item, group_item):
        clone = self._cloneItem(child_item)
        group_item.addChild(clone)
        group_item.setExpanded(True)
        root = child_item.parent() or self.invisibleRootItem()
        root.removeChild(child_item)

    def _createGroupWith(self, target_item, source_item, group_name):
        root = self.invisibleRootItem()
        target_parent = target_item.parent() or root
        source_parent = source_item.parent() or root
        target_idx = target_parent.indexOfChild(target_item)
        source_idx = source_parent.indexOfChild(source_item)

        group_item = QTreeWidgetItem([group_name])
        group_item.setData(0, ROLE_TYPE, TYPE_GROUP)
        group_item.setIcon(0, QApplication.instance().style().standardIcon(QStyle.SP_DirLinkIcon))
        group_item.setExpanded(True)

        for it in (target_item, source_item):
            clone = self._cloneItem(it)
            if clone:
                group_item.addChild(clone)
        if target_parent == source_parent:
            lo, hi = min(target_idx, source_idx), max(target_idx, source_idx)
            target_parent.removeChild(target_parent.child(hi))
            target_parent.removeChild(target_parent.child(lo))
            target_parent.insertChild(lo, group_item)
        else:
            target_parent.removeChild(target_item)
            source_parent.removeChild(source_item)
            target_parent.insertChild(target_idx, group_item)
        self.structureChanged.emit()

    def _cloneItem(self, item):
        n = QTreeWidgetItem()
        n.setText(0, item.text(0))
        n.setData(0, ROLE_TYPE, item.data(0, ROLE_TYPE))
        n.setData(0, ROLE_PATH, item.data(0, ROLE_PATH) or "")
        n.setIcon(0, item.icon(0))
        n.setToolTip(0, item.toolTip(0))
        if item.data(0, ROLE_TYPE) == TYPE_GROUP:
            for i in range(item.childCount()):
                n.addChild(self._cloneItem(item.child(i)))
        return n

    def getStructure(self):
        structure = []
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            node = _itemToNode(root.child(i))
            if node:
                structure.append(node)
        return structure


# ------------------------------------------------------------
# Class: BookmarksPanel
# Purpose: Left sidebar with title and tree; loads/saves structure,
#          emits bookmarkActivated(path) on click; context menu for edit/update/rename/delete.
# ------------------------------------------------------------
class BookmarksPanel(QWidget):

    bookmarkActivated = pyqtSignal(str)
    structureChanged = pyqtSignal(list)
    addCurrentFolderRequested = pyqtSignal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self._settings = settings_manager
        self._current_path_provider = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        title = QLabel("Bookmarks")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_collapse_all = QPushButton("Collapse")
        self._btn_collapse_all.setObjectName("bookmarksToolButton")
        self._btn_collapse_all.setToolTip(
            "Collapse all\n\nClose every group in the bookmark tree."
        )
        self._btn_collapse_all.clicked.connect(self._collapseAll)
        self._btn_expand_all = QPushButton("Expand")
        self._btn_expand_all.setObjectName("bookmarksToolButton")
        self._btn_expand_all.setToolTip(
            "Expand all\n\nOpen every group in the bookmark tree."
        )
        self._btn_expand_all.clicked.connect(self._expandAll)
        btn_row.addWidget(self._btn_collapse_all)
        btn_row.addWidget(self._btn_expand_all)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._tree = BookmarksTreeWidget(self)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._onContextMenu)
        self._tree.itemClicked.connect(self._onItemClicked)
        self._tree.structureChanged.connect(self._emitStructureChanged)
        layout.addWidget(self._tree, 1)
        self.loadStructure()

    def loadStructure(self):
        self._tree.clear()
        for node in self._settings.getBookmarksStructure():
            _nodeToItem(node, self._tree.invisibleRootItem())

    def _collapseAll(self):
        self._tree.collapseAll()

    def _expandAll(self):
        self._tree.expandAll()

    def _emitStructureChanged(self):
        self.structureChanged.emit(self._tree.getStructure())

    def saveStructure(self, structure=None):
        if structure is None:
            structure = self._tree.getStructure()
        self._settings.setBookmarksStructure(structure)

    def _onItemClicked(self, item, column):
        if item.data(0, ROLE_TYPE) != TYPE_BOOKMARK:
            return
        path = item.data(0, ROLE_PATH)
        if not path:
            return
        if os.path.isdir(path):
            self.bookmarkActivated.emit(path)
        elif os.path.isfile(path):
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                QMessageBox.warning(
                    self, "Open failed",
                    f"Could not open: {path}"
                )

    def _onContextMenu(self, pos):
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            if item.data(0, ROLE_TYPE) == TYPE_GROUP:
                rename_act = menu.addAction("Rename group")
                rename_act.triggered.connect(lambda: self._renameGroup(item))
                menu.addSeparator()
                del_act = menu.addAction("Delete group")
                del_act.triggered.connect(lambda: self._deleteGroup(item))
            else:
                edit_act = menu.addAction("Edit bookmark...")
                edit_act.triggered.connect(lambda: self._editBookmark(item))
                update_act = menu.addAction("Update with current panel")
                update_act.triggered.connect(lambda: self._updateBookmarkWithCurrentPanel(item))
                menu.addSeparator()
                rename_act = menu.addAction("Rename bookmark")
                rename_act.triggered.connect(lambda: self._renameBookmark(item))
                menu.addSeparator()
                del_act = menu.addAction("Delete bookmark")
                del_act.triggered.connect(lambda: self._deleteBookmark(item))
        else:
            add_act = menu.addAction("Add current folder...")
            add_act.triggered.connect(self.addCurrentFolderRequested.emit)
        menu.addSeparator()
        export_act = menu.addAction("Export bookmarks...")
        export_act.triggered.connect(self.exportBookmarksInteractive)
        import_act = menu.addAction("Import bookmarks...")
        import_act.triggered.connect(self.importBookmarksInteractive)
        if menu.actions():
            menu.exec_(self._tree.mapToGlobal(pos))

    def setCurrentPathProvider(self, provider):
        """Set a callable that returns the active panel path (for update-with-panel)."""
        self._current_path_provider = provider

    def _applyBookmarkData(self, item, name, path):
        item.setText(0, name)
        item.setData(0, ROLE_PATH, path)
        item.setToolTip(0, path)
        is_file = path and os.path.isfile(path)
        icon = QApplication.instance().style().standardIcon(
            QStyle.SP_FileIcon if is_file else QStyle.SP_DirIcon
        )
        item.setIcon(0, icon)

    def _editBookmark(self, item):
        path = item.data(0, ROLE_PATH) or ""
        dialog = BookmarkEditDialog(item.text(0), path, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values["name"] or not values["path"]:
            QMessageBox.warning(self, "Edit Bookmark", "Name and path are required.")
            return
        self._applyBookmarkData(item, values["name"], values["path"])
        self._emitStructureChanged()

    def _updateBookmarkWithCurrentPanel(self, item):
        if not self._current_path_provider:
            QMessageBox.warning(
                self, "Update Bookmark",
                "No active panel is available."
            )
            return
        path = self._current_path_provider()
        if not path:
            QMessageBox.warning(
                self, "Update Bookmark",
                "The active panel does not have a current path."
            )
            return
        self._applyBookmarkData(item, item.text(0), path)
        self._emitStructureChanged()

    def _renameGroup(self, item):
        name, ok = QInputDialog.getText(self, "Rename Group", "Group name:", text=item.text(0))
        if ok and name.strip():
            item.setText(0, name.strip())
            self._emitStructureChanged()

    def _renameBookmark(self, item):
        name, ok = QInputDialog.getText(self, "Rename Bookmark", "Bookmark name:", text=item.text(0))
        if ok and name.strip():
            item.setText(0, name.strip())
            self._emitStructureChanged()

    def _deleteGroup(self, item):
        if QMessageBox.question(
            self, "Delete Group",
            f"Delete group \"{item.text(0)}\"? Its bookmarks will be moved to the root.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        root = self._tree.invisibleRootItem()
        parent = item.parent() or root
        idx = parent.indexOfChild(item)
        children = [item.takeChild(0) for _ in range(item.childCount())]
        parent.removeChild(item)
        for c in reversed(children):
            parent.insertChild(idx, c)
            idx += 1
        self._emitStructureChanged()

    def _deleteBookmark(self, item):
        parent = item.parent() or self._tree.invisibleRootItem()
        parent.removeChild(item)
        self._emitStructureChanged()

    def addBookmarkAtRoot(self, name, path):
        node = {"type": TYPE_BOOKMARK, "name": name, "path": path}
        _nodeToItem(node, self._tree.invisibleRootItem())
        self._emitStructureChanged()

    def getStructure(self):
        return self._tree.getStructure()

    # --------------------------------------------------------
    # Method: exportBookmarksInteractive
    # Purpose: Ask for a path and write the current bookmark tree.
    # --------------------------------------------------------
    def exportBookmarksInteractive(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export bookmarks",
            "bookmarks.json",
            "Bookmark JSON (*.json);;All files (*.*)",
        )
        if not path:
            return False
        try:
            self._settings.exportBookmarks(path)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return False
        QMessageBox.information(
            self,
            "Export complete",
            f"Bookmarks saved to:\n{path}",
        )
        return True

    # --------------------------------------------------------
    # Method: importBookmarksInteractive
    # Purpose: Load a bookmark file, replacing or merging the list.
    # --------------------------------------------------------
    def importBookmarksInteractive(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import bookmarks",
            "",
            "Bookmark JSON (*.json);;All files (*.*)",
        )
        if not path:
            return False
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Import bookmarks")
        box.setText("How should these bookmarks be imported?")
        box.setInformativeText(
            "Replace list removes the current bookmarks first. "
            "Merge into list keeps current bookmarks and adds imported ones "
            "whose path is not already present."
        )
        replace_btn = box.addButton("Replace list", QMessageBox.AcceptRole)
        merge_btn = box.addButton("Merge into list", QMessageBox.ActionRole)
        cancel_btn = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == replace_btn:
            mode = "replace"
        elif clicked == merge_btn:
            mode = "merge"
        else:
            return False
        try:
            summary = self._settings.importBookmarks(path, mode)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return False
        self.loadStructure()
        window = self.window()
        if window is not None and hasattr(window, "_rebuildBookmarksMenu"):
            # Defer so we don't clear the Bookmarks menu while its Import action is running.
            QTimer.singleShot(0, window._rebuildBookmarksMenu)
        count = summary.get("count", 0)
        QMessageBox.information(
            self,
            "Import complete",
            f"The bookmark list now has {count} bookmark(s).\n\nLoaded from:\n{path}",
        )
        return True
