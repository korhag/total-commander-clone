"""
Total Commander Clone - Bookmarks Panel
Resizable sidebar with bookmarks and groups: drag-drop reorder,
create group on drop, context menu (edit/update/rename/delete), tooltips with full path.

Drag feedback uses one drop decision for the indicator, the hint line, and the move,
so the marker on a row is the action that happens when the item is released.
"""

import os
from collections import namedtuple

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QLabel,
    QMenu, QInputDialog, QMessageBox, QApplication,
    QHBoxLayout, QPushButton, QDialog, QFileDialog, QStyle,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer, QRect, QPoint
from PyQt5.QtGui import QDesktopServices, QPainter, QPen, QColor, QPalette

from bookmark_dialogs import BookmarkEditDialog


# Data roles for tree items
ROLE_TYPE = Qt.UserRole
ROLE_PATH = Qt.UserRole + 1
TYPE_BOOKMARK = "bookmark"
TYPE_GROUP = "group"

# Share of a row (from the top) that means "insert before" rather than "on the row".
_BOOKMARK_EDGE = 0.30
_GROUP_EDGE = 0.25

# ------------------------------------------------------------
# DropAction
# Purpose: The single decision for a drag position. The painted
#          indicator, the hint under the tree, and the drop all
#          read this, so the marker matches the result.
# kind: before, after, into, group, end, invalid
# ------------------------------------------------------------
DropAction = namedtuple(
    "DropAction",
    ["kind", "target", "parent", "index", "hint", "rect"],
)


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


def _captureExpanded(item):
    """Remember each group's open or closed state before it is reparented."""
    state = []

    def walk(node):
        if node.data(0, ROLE_TYPE) == TYPE_GROUP:
            state.append((node, node.isExpanded()))
        for index in range(node.childCount()):
            walk(node.child(index))

    walk(item)
    return state


def _restoreExpanded(state):
    """Put captured group open or closed states back after the item is in the tree."""
    for node, expanded in state:
        node.setExpanded(expanded)


def _isDescendant(ancestor, item):
    """True when item sits inside ancestor (not when they are the same row)."""
    parent = item.parent()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.parent()
    return False


def _isNoOp(moving, parent, index):
    """True when inserting at index would leave the item where it already is."""
    source_parent = moving.parent()
    if source_parent is None:
        source_parent = moving.treeWidget().invisibleRootItem() if moving.treeWidget() else None
    if source_parent is not parent:
        return False
    source_index = source_parent.indexOfChild(moving)
    return index == source_index or index == source_index + 1


def _invalidAction(target, hint):
    return DropAction("invalid", target, None, -1, hint, QRect())


def _lastVisibleItem(root):
    """The last row a user can see, walking into groups that are open."""
    found = None

    def walk(parent):
        nonlocal found
        for index in range(parent.childCount()):
            child = parent.child(index)
            found = child
            if child.isExpanded():
                walk(child)

    walk(root)
    return found


def _quoted(name):
    return f'"{name}"'


# ------------------------------------------------------------
# Class: BookmarksTreeWidget
# Purpose: Tree with drag-drop. One DropAction decides reorder,
#          move-into-group, and create-group, and that same action
#          is what the indicator and the hint describe.
# ------------------------------------------------------------
class BookmarksTreeWidget(QTreeWidget):

    structureChanged = pyqtSignal()
    dropHintChanged = pyqtSignal(str)

    _DRAG_TOOLTIP = (
        "Drag to rearrange bookmarks.\n"
        "Near the top or bottom of a row: reorder.\n"
        "Middle of a bookmark: create a group.\n"
        "Middle of a group: move into that group."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Bookmarks"])
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setAutoExpandDelay(700)
        self.setAnimated(True)
        self.setIndentation(14)
        self.setRootIsDecorated(True)
        self.setObjectName("bookmarksTree")
        self.setToolTip(self._DRAG_TOOLTIP)
        self._drop_action = None
        self._shown_hint = ""

    # --------------------------------------------------------
    # Method: dragEnterEvent
    # Purpose: Accept only drags that started in this tree.
    # --------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        super().dragEnterEvent(event)
        event.acceptProposedAction()

    # --------------------------------------------------------
    # Method: dragMoveEvent
    # Purpose: Decide the drop, then accept or refuse it so the
    #          cursor matches the indicator about to be painted.
    # --------------------------------------------------------
    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        action = self._computeDropAction(event.pos(), self.currentItem())
        self._setDropAction(action)
        if action is None or action.kind == "invalid":
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()

    # --------------------------------------------------------
    # Method: dragLeaveEvent
    # Purpose: Clear the indicator and the hint when the drag exits.
    # --------------------------------------------------------
    def dragLeaveEvent(self, event):
        self._setDropAction(None)
        super().dragLeaveEvent(event)

    # --------------------------------------------------------
    # Method: dropEvent
    # Purpose: Apply the action chosen while dragging. IgnoreAction
    #          stops Qt from deleting the source row a second time.
    # --------------------------------------------------------
    def dropEvent(self, event):
        moving = self.currentItem()
        action = self._drop_action
        self._setDropAction(None)
        if moving is not None and action is not None and action.kind != "invalid":
            self._applyDropAction(moving, action)
        event.setDropAction(Qt.IgnoreAction)
        event.accept()

    # --------------------------------------------------------
    # Method: paintEvent
    # Purpose: Draw the drop marker for the current action after
    #          the rows, using the highlight color of the theme.
    # --------------------------------------------------------
    def paintEvent(self, event):
        super().paintEvent(event)
        self._paintDropIndicator()

    def _setDropAction(self, action):
        self._drop_action = action
        hint = action.hint if action is not None else ""
        if hint != self._shown_hint:
            self._shown_hint = hint
            self.dropHintChanged.emit(hint)
        self.viewport().update()

    # --------------------------------------------------------
    # Method: _computeDropAction
    # Purpose: Map a cursor position to the drop that will happen.
    #          Bookmark rows: top and bottom reorder, middle groups.
    #          Group rows: top reorders, middle moves inside, bottom
    #          reorders or (when the group is open) inserts as the
    #          first child. Empty space moves the item to the end.
    # --------------------------------------------------------
    def _computeDropAction(self, pos, moving):
        if moving is None:
            return _invalidAction(None, "Nothing to move")

        drop_item = self.itemAt(pos)
        if drop_item is None:
            return self._endAction(moving)

        if _isDescendant(moving, drop_item):
            if moving.data(0, ROLE_TYPE) == TYPE_GROUP:
                hint = "A group can't be moved inside itself"
            else:
                hint = "This item can't be moved inside itself"
            return _invalidAction(drop_item, hint)

        rect = self.visualItemRect(drop_item)
        if not rect.isValid() or rect.height() <= 0:
            return _invalidAction(drop_item, "Drop on a bookmark or group")

        ratio = (pos.y() - rect.top()) / float(rect.height())
        ratio = max(0.0, min(0.999, ratio))
        name = drop_item.text(0)
        drop_type = drop_item.data(0, ROLE_TYPE)

        if drop_item is moving:
            return self._actionOnSelf(drop_item, drop_type, ratio)

        if drop_type == TYPE_GROUP:
            if ratio < _GROUP_EDGE:
                return self._siblingAction("before", drop_item, moving, name)
            if ratio > 1.0 - _GROUP_EDGE:
                if drop_item.isExpanded() and drop_item.childCount() > 0:
                    return self._firstChildAction(drop_item, moving, name)
                return self._siblingAction("after", drop_item, moving, name)
            return self._intoAction(drop_item, moving, name)

        if ratio < _BOOKMARK_EDGE:
            return self._siblingAction("before", drop_item, moving, name)
        if ratio > 1.0 - _BOOKMARK_EDGE:
            return self._siblingAction("after", drop_item, moving, name)
        return self._groupAction(drop_item, moving, name)

    def _actionOnSelf(self, drop_item, drop_type, ratio):
        """Edges of the dragged row are a no-op; the middle is refused."""
        edge = _GROUP_EDGE if drop_type == TYPE_GROUP else _BOOKMARK_EDGE
        if ratio < edge or ratio > 1.0 - edge:
            return _invalidAction(drop_item, "Already in this position")
        if drop_type == TYPE_GROUP:
            return _invalidAction(drop_item, "A group can't be moved inside itself")
        return _invalidAction(drop_item, "A bookmark can't be grouped with itself")

    def _siblingAction(self, kind, drop_item, moving, name):
        parent = drop_item.parent() or self.invisibleRootItem()
        index = parent.indexOfChild(drop_item)
        if kind == "after":
            index += 1
        if _isNoOp(moving, parent, index):
            return _invalidAction(drop_item, "Already in this position")
        place = "above" if kind == "before" else "below"
        hint = f"Place {place} {_quoted(name)}"
        edge = "top" if kind == "before" else "bottom"
        rect = self._lineRect(self.visualItemRect(drop_item), edge, self.visualItemRect(drop_item).left())
        return DropAction(kind, drop_item, parent, index, hint, rect)

    def _firstChildAction(self, group_item, moving, name):
        """Bottom of an open group: insert as that group's first child."""
        index = 0
        if _isNoOp(moving, group_item, index):
            return _invalidAction(group_item, "Already in this position")
        hint = f"Place at the start of {_quoted(name)}"
        row = self.visualItemRect(group_item)
        left = row.left() + self.indentation()
        rect = self._lineRect(row, "bottom", left)
        return DropAction("before", group_item, group_item, index, hint, rect)

    def _intoAction(self, group_item, moving, name):
        index = group_item.childCount()
        if _isNoOp(moving, group_item, index):
            return _invalidAction(group_item, "Already in this position")
        hint = f"Move into group {_quoted(name)}"
        return DropAction("into", group_item, group_item, index, hint, self._rowRect(group_item))

    def _groupAction(self, drop_item, moving, name):
        parent = drop_item.parent() or self.invisibleRootItem()
        index = parent.indexOfChild(drop_item)
        hint = f"Create a new group with {_quoted(name)}"
        return DropAction("group", drop_item, parent, index, hint, self._rowRect(drop_item))

    def _endAction(self, moving):
        root = self.invisibleRootItem()
        index = root.childCount()
        if _isNoOp(moving, root, index):
            return _invalidAction(None, "Already in this position")
        last = _lastVisibleItem(root)
        if last is None:
            row = QRect(0, 0, self.viewport().width(), 4)
            left = self.indentation()
        else:
            row = self.visualItemRect(last)
            left = self._rootIndent()
        rect = self._lineRect(row, "bottom", left)
        return DropAction("end", None, root, index, "Place at the end", rect)

    def _rootIndent(self):
        root = self.invisibleRootItem()
        if root.childCount() <= 0:
            return self.indentation()
        return self.visualItemRect(root.child(0)).left()

    def _rowRect(self, item):
        rect = self.visualItemRect(item)
        return QRect(0, rect.top(), max(1, self.viewport().width()), max(1, rect.height()))

    def _lineRect(self, row, edge, left):
        y = row.top() if edge == "top" else row.bottom()
        width = max(1, self.viewport().width() - left)
        return QRect(left, max(0, y - 1), width, 2)

    def _paintDropIndicator(self):
        action = self._drop_action
        if action is None or action.kind == "invalid":
            return
        if action.rect is None or action.rect.isNull():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = self.palette().color(QPalette.Highlight)
        rect = action.rect
        if action.kind in ("before", "after", "end"):
            self._paintInsertLine(painter, color, rect)
        elif action.kind == "into":
            self._paintIntoGroup(painter, color, rect)
        elif action.kind == "group":
            self._paintCreateGroup(painter, color, rect)
        painter.end()

    def _paintInsertLine(self, painter, color, rect):
        y = rect.center().y()
        painter.setPen(QPen(color, 2))
        painter.drawLine(rect.left() + 8, y, rect.right() - 2, y)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPoint(rect.left() + 3, y), 3, 3)

    def _paintIntoGroup(self, painter, color, rect):
        fill = QColor(color)
        fill.setAlpha(70)
        painter.fillRect(rect.adjusted(1, 1, -1, -1), fill)
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(1, 1, -2, -2))

    def _paintCreateGroup(self, painter, color, rect):
        painter.setPen(QPen(color, 2, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(2, 2, -3, -3), 4, 4)
        self._paintGroupBadge(painter, color, rect)

    def _paintGroupBadge(self, painter, color, rect):
        text = "+ Group"
        metrics = painter.fontMetrics()
        text_width = metrics.width(text)
        text_height = metrics.height()
        badge_width = text_width + 8
        badge_height = text_height + 2
        badge = QRect(
            rect.right() - badge_width - 6,
            rect.center().y() - badge_height // 2,
            badge_width,
            badge_height,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(self.palette().color(QPalette.HighlightedText))
        painter.drawText(badge, Qt.AlignCenter, text)

    # --------------------------------------------------------
    # Method: _applyDropAction
    # Purpose: Perform the drop that _computeDropAction described,
    #          then select the moved row so its new place is visible.
    # --------------------------------------------------------
    def _applyDropAction(self, moving, action):
        if moving is None or action is None or action.kind == "invalid":
            return None
        if action.kind == "group":
            name, ok = QInputDialog.getText(
                self,
                "Create Group",
                "Create a new group containing these items. Group name:",
                text="New Group",
            )
            if not ok or not name.strip():
                return None
            placed = self._createGroupWith(action.target, moving, name.strip())
        else:
            placed = self._moveItem(moving, action.parent, action.index)
            if placed is not None and action.kind == "into" and action.target is not None:
                action.target.setExpanded(True)
        if placed is None:
            return None
        self.setCurrentItem(placed)
        self.scrollToItem(placed)
        self.structureChanged.emit()
        return placed

    def _moveItem(self, item, parent, index):
        """Move the real item so nested groups keep their open or closed state."""
        parent = parent or self.invisibleRootItem()
        source_parent = item.parent() or self.invisibleRootItem()
        source_index = source_parent.indexOfChild(item)
        if source_index < 0:
            return None
        expanded = _captureExpanded(item)
        taken = source_parent.takeChild(source_index)
        if source_parent is parent and source_index < index:
            index -= 1
        index = max(0, min(index, parent.childCount()))
        parent.insertChild(index, taken)
        _restoreExpanded(expanded)
        return taken

    def _createGroupWith(self, target_item, source_item, group_name):
        """Wrap the target and the dropped item in a new group, in that order."""
        root = self.invisibleRootItem()
        target_parent = target_item.parent() or root
        source_parent = source_item.parent() or root
        target_index = target_parent.indexOfChild(target_item)
        source_index = source_parent.indexOfChild(source_item)
        expanded = _captureExpanded(target_item) + _captureExpanded(source_item)

        taken_target = self._detachItem(target_item)
        taken_source = self._detachItem(source_item)
        if taken_target is None or taken_source is None:
            return None

        group_item = QTreeWidgetItem([group_name])
        group_item.setData(0, ROLE_TYPE, TYPE_GROUP)
        group_item.setFlags(group_item.flags() | Qt.ItemIsDropEnabled)
        group_item.setToolTip(0, f"Group: {group_name}")
        group_item.setIcon(
            0, QApplication.instance().style().standardIcon(QStyle.SP_DirLinkIcon)
        )
        group_item.addChild(taken_target)
        group_item.addChild(taken_source)

        if target_parent is source_parent:
            insert_at = min(target_index, source_index)
        else:
            insert_at = target_index
        insert_at = max(0, min(insert_at, target_parent.childCount()))
        target_parent.insertChild(insert_at, group_item)
        _restoreExpanded(expanded)
        group_item.setExpanded(True)
        return group_item

    def _detachItem(self, item):
        parent = item.parent() or self.invisibleRootItem()
        index = parent.indexOfChild(item)
        if index < 0:
            return None
        return parent.takeChild(index)

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
        title.setToolTip(BookmarksTreeWidget._DRAG_TOOLTIP)
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
        self._tree.dropHintChanged.connect(self._onDropHintChanged)
        layout.addWidget(self._tree, 1)
        self._drop_hint = QLabel("")
        self._drop_hint.setObjectName("bookmarksDropHint")
        self._drop_hint.setWordWrap(True)
        # Keep a fixed strip so showing the hint does not resize the tree
        # and move the row under the cursor.
        hint_height = self._drop_hint.fontMetrics().lineSpacing() * 2 + 6
        self._drop_hint.setMinimumHeight(hint_height)
        self._drop_hint.setMaximumHeight(hint_height)
        layout.addWidget(self._drop_hint)
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

    # --------------------------------------------------------
    # Method: _onDropHintChanged
    # Purpose: Show the sentence for the current drop, and hide
    #          the line again when the drag leaves the tree.
    # --------------------------------------------------------
    def _onDropHintChanged(self, text):
        self._drop_hint.setText(text or "")

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
