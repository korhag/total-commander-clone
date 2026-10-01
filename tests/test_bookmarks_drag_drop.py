"""
Bookmark drag-and-drop: the zone under the cursor, refused drops,
and the tree after a reorder or a move into a group.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication

from bookmarks_panel import (
    TYPE_BOOKMARK,
    TYPE_GROUP,
    BookmarksTreeWidget,
    DropAction,
    _nodeToItem,
)


def _sample_nodes():
    return [
        {"type": TYPE_BOOKMARK, "name": "Docs", "path": "C:/docs"},
        {
            "type": TYPE_GROUP,
            "name": "Work",
            "expanded": True,
            "children": [
                {"type": TYPE_BOOKMARK, "name": "Notes", "path": "C:/notes"},
            ],
        },
        {"type": TYPE_BOOKMARK, "name": "Later", "path": "C:/later"},
        {
            "type": TYPE_GROUP,
            "name": "Archive",
            "expanded": False,
            "children": [
                {"type": TYPE_BOOKMARK, "name": "Old", "path": "C:/old"},
            ],
        },
    ]


def _find(tree, name):
    def walk(parent):
        for index in range(parent.childCount()):
            child = parent.child(index)
            if child.text(0) == name:
                return child
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(tree.invisibleRootItem())


# ------------------------------------------------------------
# Class: TestBookmarkDragDrop
# Purpose: The drop decision, the hint, and the resulting tree
#          stay in agreement for reorder, grouping, and refusal.
# ------------------------------------------------------------
class TestBookmarkDragDrop(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _tree(self):
        tree = BookmarksTreeWidget()
        tree.resize(260, 420)
        for node in _sample_nodes():
            _nodeToItem(node, tree.invisibleRootItem())
        return tree

    def _shown(self):
        tree = self._tree()
        tree.show()
        self._app.processEvents()
        return tree

    def _point(self, tree, item, fraction):
        rect = tree.visualItemRect(item)
        self.assertGreater(rect.height(), 0, item.text(0))
        y = rect.top() + int(round((rect.height() - 1) * fraction))
        return QPoint(rect.left() + 8, y)

    def test_bookmark_row_zones(self):
        tree = self._shown()
        docs = _find(tree, "Docs")
        later = _find(tree, "Later")
        zones = (
            (0.05, "before", 'Place above "Docs"'),
            (0.50, "group", 'Create a new group with "Docs"'),
            (0.95, "after", 'Place below "Docs"'),
        )
        for fraction, kind, hint in zones:
            action = tree._computeDropAction(self._point(tree, docs, fraction), later)
            self.assertEqual(action.kind, kind, fraction)
            self.assertEqual(action.hint, hint)
            self.assertIs(action.target, docs)
        tree.close()

    def test_group_row_zones(self):
        tree = self._shown()
        work = _find(tree, "Work")
        archive = _find(tree, "Archive")
        docs = _find(tree, "Docs")
        later = _find(tree, "Later")

        above = tree._computeDropAction(self._point(tree, work, 0.05), later)
        self.assertEqual(above.kind, "before")
        self.assertEqual(above.hint, 'Place above "Work"')
        self.assertIs(above.parent, tree.invisibleRootItem())

        into = tree._computeDropAction(self._point(tree, work, 0.50), docs)
        self.assertEqual(into.kind, "into")
        self.assertEqual(into.hint, 'Move into group "Work"')
        self.assertIs(into.parent, work)
        self.assertEqual(into.index, work.childCount())

        start = tree._computeDropAction(self._point(tree, work, 0.95), docs)
        self.assertEqual(start.kind, "before")
        self.assertEqual(start.hint, 'Place at the start of "Work"')
        self.assertIs(start.parent, work)
        self.assertEqual(start.index, 0)

        below = tree._computeDropAction(self._point(tree, archive, 0.95), docs)
        self.assertEqual(below.kind, "after")
        self.assertEqual(below.hint, 'Place below "Archive"')
        self.assertIs(below.parent, tree.invisibleRootItem())
        tree.close()

    def test_empty_area_moves_to_end(self):
        tree = self._shown()
        docs = _find(tree, "Docs")
        archive = _find(tree, "Archive")
        below = tree.visualItemRect(archive).bottom() + 16
        pos = QPoint(20, below)
        self.assertIsNone(tree.itemAt(pos))
        action = tree._computeDropAction(pos, docs)
        self.assertEqual(action.kind, "end")
        self.assertEqual(action.hint, "Place at the end")
        self.assertIs(action.parent, tree.invisibleRootItem())
        self.assertEqual(action.index, tree.invisibleRootItem().childCount())
        tree.close()

    def test_group_cannot_drop_inside_itself(self):
        tree = self._shown()
        work = _find(tree, "Work")
        notes = _find(tree, "Notes")
        action = tree._computeDropAction(self._point(tree, notes, 0.50), work)
        self.assertEqual(action.kind, "invalid")
        self.assertEqual(action.hint, "A group can't be moved inside itself")
        tree.close()

    def test_reorder_and_into_keep_expanded_state(self):
        tree = self._tree()
        root = tree.invisibleRootItem()
        docs = _find(tree, "Docs")
        work = _find(tree, "Work")
        later = _find(tree, "Later")
        archive = _find(tree, "Archive")

        tree._applyDropAction(
            later,
            DropAction("before", docs, root, 0, 'Place above "Docs"', None),
        )
        names = [node["name"] for node in tree.getStructure()]
        self.assertEqual(names, ["Later", "Docs", "Work", "Archive"])
        self.assertTrue(tree.getStructure()[2]["expanded"])
        self.assertFalse(tree.getStructure()[3]["expanded"])

        tree._applyDropAction(
            archive,
            DropAction("before", later, root, 0, 'Place above "Later"', None),
        )
        moved = tree.getStructure()[0]
        self.assertEqual(moved["name"], "Archive")
        self.assertFalse(moved["expanded"])
        self.assertEqual(moved["children"][0]["name"], "Old")

        docs = _find(tree, "Docs")
        work = _find(tree, "Work")
        tree._applyDropAction(
            docs,
            DropAction("into", work, work, work.childCount(), 'Move into group "Work"', None),
        )
        structure = tree.getStructure()
        work_node = next(node for node in structure if node["name"] == "Work")
        self.assertEqual([child["name"] for child in work_node["children"]], ["Notes", "Docs"])
        self.assertTrue(work_node["expanded"])
        self.assertNotIn("Docs", [node["name"] for node in structure])

    def test_create_group_keeps_nested_expanded_state(self):
        tree = self._tree()
        docs = _find(tree, "Docs")
        work = _find(tree, "Work")
        group = tree._createGroupWith(docs, work, "Bundled")
        self.assertIsNotNone(group)
        bundled = tree.getStructure()[0]
        self.assertEqual(bundled["name"], "Bundled")
        self.assertTrue(bundled["expanded"])
        self.assertEqual([child["name"] for child in bundled["children"]], ["Docs", "Work"])
        self.assertTrue(bundled["children"][1]["expanded"])
        self.assertEqual(bundled["children"][1]["children"][0]["name"], "Notes")

    def test_indicators_paint(self):
        tree = self._shown()
        docs = _find(tree, "Docs")
        later = _find(tree, "Later")
        work = _find(tree, "Work")
        actions = [
            tree._computeDropAction(self._point(tree, docs, 0.05), later),
            tree._computeDropAction(self._point(tree, docs, 0.50), later),
            tree._computeDropAction(self._point(tree, work, 0.50), later),
        ]
        for action in actions:
            self.assertNotEqual(action.kind, "invalid")
            tree._setDropAction(action)
            tree.viewport().repaint()
        tree._setDropAction(None)
        self.assertEqual(tree._shown_hint, "")
        tree.close()


if __name__ == "__main__":
    unittest.main()
