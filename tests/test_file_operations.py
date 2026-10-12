"""
Copy and move guards: same-folder paste, folder-into-itself, and cancel cleanup.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PyQt5.QtWidgets import QApplication

from file_operations import FileOperationWorker


_APP = QApplication.instance() or QApplication([])


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _run(operation, sources, destination):
    worker = FileOperationWorker(operation, sources, destination)
    messages = []
    worker.operationFinished.connect(lambda ok, msg: messages.append((ok, msg)))
    worker.run()
    return worker, messages


# ------------------------------------------------------------
# Class: TestFileOperationGuards
# Purpose: Prove copy/move cannot destroy the source by writing
#          it onto itself or into its own subtree.
# ------------------------------------------------------------
class TestFileOperationGuards(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_copy_into_same_folder_keeps_original(self):
        folder = os.path.join(self.root, "docs")
        source = os.path.join(folder, "note.txt")
        _write(source, "hello")

        _worker, messages = _run(
            FileOperationWorker.OPERATION_COPY, [source], folder
        )

        copy_path = os.path.join(folder, "note (1).txt")
        self.assertTrue(messages[0][0], messages)
        self.assertEqual(open(source, encoding="utf-8").read(), "hello")
        self.assertEqual(open(copy_path, encoding="utf-8").read(), "hello")

    def test_move_into_same_folder_is_a_noop(self):
        folder = os.path.join(self.root, "docs")
        source = os.path.join(folder, "note.txt")
        _write(source, "hello")

        _worker, messages = _run(
            FileOperationWorker.OPERATION_MOVE, [source], folder
        )

        self.assertTrue(messages[0][0], messages)
        self.assertEqual(open(source, encoding="utf-8").read(), "hello")
        self.assertFalse(os.path.exists(os.path.join(folder, "note (1).txt")))

    def test_copy_folder_into_itself_leaves_source(self):
        box = os.path.join(self.root, "box")
        _write(os.path.join(box, "keep.txt"), "safe")
        os.makedirs(os.path.join(box, "nested"))

        _worker, messages = _run(FileOperationWorker.OPERATION_COPY, [box], box)

        self.assertFalse(messages[0][0], messages)
        self.assertIn("into itself", messages[0][1])
        self.assertEqual(open(os.path.join(box, "keep.txt"), encoding="utf-8").read(), "safe")
        self.assertFalse(os.path.isdir(os.path.join(box, "box")))

    def test_move_folder_into_itself_leaves_source(self):
        box = os.path.join(self.root, "box")
        _write(os.path.join(box, "keep.txt"), "safe")
        os.makedirs(os.path.join(box, "nested"))

        _worker, messages = _run(FileOperationWorker.OPERATION_MOVE, [box], box)

        self.assertFalse(messages[0][0], messages)
        self.assertIn("into itself", messages[0][1])
        self.assertTrue(os.path.isfile(os.path.join(box, "keep.txt")))
        self.assertFalse(os.path.isdir(os.path.join(box, "box")))

    def test_cancelled_folder_copy_removes_partial_destination(self):
        source = os.path.join(self.root, "srcbox")
        _write(os.path.join(source, "a.txt"), "aaa")
        _write(os.path.join(source, "b.txt"), "bbb")
        dest_parent = os.path.join(self.root, "out")
        os.makedirs(dest_parent)

        worker = FileOperationWorker(
            FileOperationWorker.OPERATION_COPY, [source], dest_parent
        )
        real_copy = worker._copyFileWithProgress

        def _cancel_on_first_file(*args, **kwargs):
            worker._cancelled = True
            return real_copy(*args, **kwargs)

        worker._copyFileWithProgress = _cancel_on_first_file
        messages = []
        worker.operationFinished.connect(lambda ok, msg: messages.append((ok, msg)))
        worker.run()

        self.assertFalse(messages[0][0], messages)
        self.assertIn("cancelled", messages[0][1].lower())
        self.assertFalse(os.path.exists(os.path.join(dest_parent, "srcbox")))
        self.assertEqual(open(os.path.join(source, "a.txt"), encoding="utf-8").read(), "aaa")
        self.assertEqual(open(os.path.join(source, "b.txt"), encoding="utf-8").read(), "bbb")


if __name__ == "__main__":
    unittest.main()
