"""
Copy and move guards: same-folder paste, folder-into-itself, and cancel cleanup.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from file_operations import (
    CONFLICT_OVERWRITE,
    FileOperationWorker,
    explainFileError,
    renameFile,
    _pathByteSize,
)


_APP = QApplication.instance() or QApplication([])


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


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

    def test_copy_keeps_file_when_timestamps_fail(self):
        source = os.path.join(self.root, "note.txt")
        dest_dir = os.path.join(self.root, "out")
        os.makedirs(dest_dir)
        _write(source, "hello")

        with mock.patch(
            "file_operations.shutil.copystat",
            side_effect=OSError(1, "Incorrect function"),
        ):
            _worker, messages = _run(
                FileOperationWorker.OPERATION_COPY, [source], dest_dir
            )

        dest = os.path.join(dest_dir, "note.txt")
        self.assertTrue(messages[0][0], messages)
        self.assertEqual(_read(dest), "hello")

    def test_sizes_are_calculated_once_and_move_progress_keeps_processed_bytes(self):
        dest = os.path.join(self.root, "out")
        os.mkdir(dest)
        paths = [os.path.join(self.root, f"{index}.txt") for index in range(20)]
        for path in paths:
            _write(path, "data")
        worker = FileOperationWorker(FileOperationWorker.OPERATION_MOVE, paths, dest)
        percentages = []
        worker.progressChanged.connect(lambda percent, *_: percentages.append(percent))
        with mock.patch("file_operations._pathByteSize", wraps=_pathByteSize) as size:
            worker.run()
            self.assertEqual([call.args[0] for call in size.call_args_list], paths)
        self.assertEqual(percentages, sorted(percentages))
        self.assertIn(50, percentages)
        self.assertEqual(percentages[-1], 100)
        self.assertEqual(len(os.listdir(dest)), len(paths))

    def test_can_cancel_during_folder_sizing(self):
        source, dest = os.path.join(self.root, "src"), os.path.join(self.root, "out")
        _write(os.path.join(source, "a"), "data")
        os.mkdir(dest)
        worker = FileOperationWorker(FileOperationWorker.OPERATION_COPY, [source], dest)
        message = []
        worker.operationFinished.connect(lambda ok, detail: message.append((ok, detail)))

        def walk(path):
            worker.cancel()
            yield path, [], ["a"]
            self.fail("Sizing continued after cancellation")

        with mock.patch("file_operations.os.walk", side_effect=walk):
            worker.run()
        self.assertFalse(message[0][0])
        self.assertIn("cancelled", message[0][1].lower())
        self.assertEqual(os.listdir(dest), [])

    def test_copy_errors_stay_on_one_line(self):
        dest_dir = os.path.join(self.root, "out")
        os.makedirs(dest_dir)
        missing = [
            os.path.join(self.root, "missing-a.txt"),
            os.path.join(self.root, "missing-b.txt"),
        ]
        _worker, messages = _run(
            FileOperationWorker.OPERATION_COPY, missing, dest_dir
        )

        text = messages[0][1]
        self.assertFalse(messages[0][0], messages)
        self.assertNotIn("\n", text)
        self.assertTrue(text.startswith("Completed with errors:"))
        self.assertIn("(and 1 more)", text)

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


# ------------------------------------------------------------
# Class: TestOverwriteSafety
# Purpose: Overwrite and cross-volume moves must never lose the
#          existing destination or the source on failure/cancel.
# ------------------------------------------------------------
class TestOverwriteSafety(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.source = os.path.join(self.root, "src", "note.txt")
        self.dest_dir = os.path.join(self.root, "out")
        self.dest = os.path.join(self.dest_dir, "note.txt")
        _write(self.source, "new")
        _write(self.dest, "old")

    def tearDown(self):
        self._tmp.cleanup()

    def _worker(self, operation):
        worker = FileOperationWorker(operation, [self.source], self.dest_dir)
        worker._apply_to_all_choice = CONFLICT_OVERWRITE
        messages = []
        worker.operationFinished.connect(lambda ok, msg: messages.append((ok, msg)))
        return worker, messages

    def _leftovers(self):
        return [n for n in os.listdir(self.dest_dir) if ".tcc-old" in n]

    def test_move_overwrite_replaces_destination(self):
        worker, messages = self._worker(FileOperationWorker.OPERATION_MOVE)
        worker.run()

        self.assertTrue(messages[0][0], messages)
        self.assertEqual(_read(self.dest), "new")
        self.assertFalse(os.path.exists(self.source))
        self.assertEqual(self._leftovers(), [])

    def test_failed_move_keeps_existing_destination(self):
        worker, messages = self._worker(FileOperationWorker.OPERATION_MOVE)
        with mock.patch("file_operations._tryRename", side_effect=PermissionError("locked")):
            worker.run()

        self.assertFalse(messages[0][0], messages)
        self.assertEqual(_read(self.dest), "old")
        self.assertEqual(_read(self.source), "new")
        self.assertEqual(self._leftovers(), [])

    def test_unreadable_subfolder_restores_destination_and_preserves_source(self):
        for operation in ("copy", "move"):
            with self.subTest(operation=operation):
                bundle = os.path.join(self.root, operation)
                old_bundle = os.path.join(self.dest_dir, operation)
                _write(os.path.join(bundle, "new.txt"), "new")
                _write(os.path.join(bundle, "unreadable", "keep.txt"), "source")
                _write(os.path.join(old_bundle, "old.txt"), "previous")
                worker = FileOperationWorker(operation, [bundle], self.dest_dir)
                worker._apply_to_all_choice = CONFLICT_OVERWRITE
                completed = []
                worker.operationFinished.connect(lambda ok, detail: completed.append((ok, detail)))
                real_walk = os.walk

                def walk(path, onerror=None, **options):
                    if path != bundle:
                        yield from real_walk(path, onerror=onerror, **options)
                        return
                    yield path, ["unreadable"], ["new.txt"]
                    if onerror:
                        onerror(PermissionError("cannot read subfolder"))

                with mock.patch("file_operations._sameVolume", return_value=False), \
                        mock.patch("file_operations.os.walk", side_effect=walk):
                    worker.run()
                self.assertFalse(completed[0][0])
                self.assertIn("cannot read subfolder", completed[0][1])
                self.assertEqual(os.listdir(old_bundle), ["old.txt"])
                self.assertEqual(_read(os.path.join(old_bundle, "old.txt")), "previous")
                self.assertEqual(_read(os.path.join(bundle, "unreadable", "keep.txt")), "source")
                self.assertEqual(self._leftovers(), [])
    def test_cancelled_copy_overwrite_keeps_existing_destination(self):
        worker, messages = self._worker(FileOperationWorker.OPERATION_COPY)
        real_copy = worker._copyFileWithProgress

        def _cancel_then_copy(*args, **kwargs):
            worker._cancelled = True
            return real_copy(*args, **kwargs)

        worker._copyFileWithProgress = _cancel_then_copy
        worker.run()

        self.assertFalse(messages[0][0], messages)
        self.assertEqual(_read(self.dest), "old")
        self.assertEqual(self._leftovers(), [])

    def test_cancel_after_cross_volume_copy_keeps_source(self):
        worker, messages = self._worker(FileOperationWorker.OPERATION_MOVE)
        real_copy = worker._copyFileWithProgress

        def _copy_then_cancel(*args, **kwargs):
            result = real_copy(*args, **kwargs)
            worker._cancelled = True
            return result

        worker._copyFileWithProgress = _copy_then_cancel
        with mock.patch("file_operations._sameVolume", return_value=False):
            worker.run()

        self.assertFalse(messages[0][0], messages)
        self.assertIn("cancelled", messages[0][1].lower())
        self.assertEqual(_read(self.source), "new")
        self.assertEqual(_read(self.dest), "old")

    def test_cross_volume_move_reports_failed_source_removal(self):
        os.remove(self.dest)
        worker = FileOperationWorker(
            FileOperationWorker.OPERATION_MOVE, [self.source], self.dest_dir
        )
        messages = []
        worker.operationFinished.connect(lambda ok, msg: messages.append((ok, msg)))
        with mock.patch("file_operations._sameVolume", return_value=False), \
                mock.patch("file_operations.os.remove", side_effect=PermissionError("in use")):
            worker.run()

        self.assertFalse(messages[0][0], messages)
        self.assertIn("could not remove the original", messages[0][1])
        self.assertEqual(_read(self.dest), "new")
        self.assertEqual(_read(self.source), "new")


# ------------------------------------------------------------
# Class: TestConflictAndRename
# Purpose: Cancel must release a worker waiting on a conflict
#          answer; case-only renames must be allowed.
# ------------------------------------------------------------
class TestConflictAndRename(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_cancel_releases_conflict_wait(self):
        source = os.path.join(self.root, "src", "note.txt")
        dest_dir = os.path.join(self.root, "out")
        _write(source, "new")
        _write(os.path.join(dest_dir, "note.txt"), "old")
        worker = FileOperationWorker(FileOperationWorker.OPERATION_COPY, [source], dest_dir)
        asked = threading.Event()
        messages = []
        worker.conflictDetected.connect(lambda *_args: asked.set(), Qt.DirectConnection)
        worker.operationFinished.connect(
            lambda ok, msg: messages.append((ok, msg)), Qt.DirectConnection
        )

        runner = threading.Thread(target=worker.run, daemon=True)
        runner.start()
        self.assertTrue(asked.wait(5))
        time.sleep(0.05)
        worker.cancel()
        runner.join(5)

        self.assertFalse(runner.is_alive())
        self.assertFalse(messages[0][0], messages)
        self.assertEqual(_read(os.path.join(dest_dir, "note.txt")), "old")

    def test_case_only_rename_is_allowed(self):
        old_path = os.path.join(self.root, "File.txt")
        _write(old_path, "data")

        ok, new_path, message = renameFile(old_path, "file.txt")

        self.assertTrue(ok, message)
        self.assertIn("file.txt", os.listdir(self.root))
        self.assertEqual(_read(new_path), "data")


# ------------------------------------------------------------
# Class: TestExplainFileError
# Purpose: Known Windows and cloud failures get a plain sentence.
# ------------------------------------------------------------
class TestExplainFileError(unittest.TestCase):

    def test_known_windows_codes(self):
        self.assertIn(
            "permission",
            explainFileError("note.txt: [WinError 5] Access is denied").lower(),
        )
        self.assertIn(
            "in use",
            explainFileError("note.txt: [WinError 32] The process cannot access the file").lower(),
        )
        self.assertEqual(
            explainFileError("note.txt: [WinError 112] There is not enough space"),
            "The drive is full.",
        )
        self.assertEqual(
            explainFileError("note.txt: [WinError 206] The filename or extension is too long"),
            "The path is too long.",
        )
        self.assertIn(
            "cloud",
            explainFileError("note.txt: [WinError 395] The cloud operation was unsuccessful").lower(),
        )

    def test_unknown_error_has_no_extra_sentence(self):
        self.assertEqual(explainFileError("note.txt: [WinError 1] Incorrect function"), "")


if __name__ == "__main__":
    unittest.main()
