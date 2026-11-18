"""Transfer route review, conflict choices and queue presentation."""
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFileDialog, QDialog, QLabel, QLineEdit

from file_operations import (ConflictDialog, FileOperationWorker, CONFLICT_KEEP_BOTH,
                             CONFLICT_OVERWRITE, CONFLICT_SKIP, CONFLICT_CANCEL)
from file_manager_app import FileManagerApp
from file_operation_queue import FileOperationQueue, FileOperationTask, STATUS_PENDING, STATUS_RUNNING
from settings_manager import SettingsManager
from transfer_review_dialog import TransferReviewDialog
from transfers_bar import TransfersDetailsDialog

_APP = QApplication.instance() or QApplication([])


class TransferUiTests(unittest.TestCase):
    def _window(self, layout):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = SettingsManager(temporary.name, enable_backup=False)
        settings.setSetting("cache_recursive_scans", False)
        settings.setPaneLayout(layout)
        window = FileManagerApp(settings)
        self.addCleanup(self._closeWindow, window)
        return window, temporary.name

    @staticmethod
    def _closeWindow(window):
        window.close()
        window.deleteLater()
        QTest.qWait(0)

    def test_review_shows_captured_route_and_structure_example(self):
        dialog = TransferReviewDialog('Copy', ['/source/sub/a'], '/source', '/target', 'Left', ['sub/a'])
        texts = [field.text() for field in dialog.findChildren(QLineEdit)]
        self.assertEqual(texts, ['/source', '/target', '/source/sub/a', os.path.normpath('/target/sub/a')])
        self.assertTrue(all(field.isReadOnly() for field in dialog.findChildren(QLineEdit)))
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.Rejected)

    def test_conflict_plain_paths_and_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'incoming & draft.txt')
            dest = os.path.join(directory, 'existing & draft.txt')
            for path in (source, dest):
                with open(path, 'w') as stream:
                    stream.write('same')
            dialog = ConflictDialog(source, dest, 'Copy')
            self.assertEqual(dialog._src_labels['path'].text(), source)
            self.assertEqual(dialog._src_labels['path'].textFormat(), Qt.PlainText)
            self.assertTrue(dialog._btn_overwrite_if_same.isEnabled())
            dialog._btn_keep_both.click()
            self.assertEqual(dialog.getChoice(), (CONFLICT_KEEP_BOTH, False))

    def test_waiting_conflict_does_not_answer_replacement_worker(self):
        queue = FileOperationQueue()
        old_worker = mock.Mock()
        new_worker = mock.Mock()
        old_task = FileOperationTask('old', 'copy', ['/a'], '/b', status=STATUS_RUNNING)
        new_task = FileOperationTask('new', 'copy', ['/c'], '/d', status=STATUS_RUNNING)
        queue._worker = old_worker
        queue._current_task = old_task
        with mock.patch('file_operation_queue.ConflictDialog') as cls:
            dialog = cls.return_value
            def switch():
                self.assertTrue(old_task.waiting_for_decision)
                queue._worker = new_worker
                queue._current_task = new_task
                return QDialog.Accepted
            dialog.exec_.side_effect = switch
            queue._onConflictDetected('/a', '/b/a', 'a')
        new_worker.setConflictResponse.assert_not_called()
        old_worker.setConflictResponse.assert_not_called()
        self.assertFalse(old_task.waiting_for_decision)

    def test_copy_review_captures_request_and_cancel_does_not_enqueue(self):
        window, destination = self._window("both")
        self.assertTrue(window._right_panel.navigateTo(destination))
        with mock.patch.object(window._left_panel, "selectedPaths", return_value=["/source/a"]) as selected, \
                mock.patch.object(window._transfer_queue, "enqueueCopy") as enqueue, \
                mock.patch.object(window, "_reviewTransfer", return_value=False) as review:
            window._onCopyToOther()
            enqueue.assert_not_called()

            def accept_and_change_panes(*args, **kwargs):
                selected.return_value = ["/different/b"]
                window._right_panel.navigateTo(os.path.dirname(destination))
                return True

            review.side_effect = accept_and_change_panes
            window._onCopyToOther()
            enqueue.assert_called_once_with(["/source/a"], destination, relative_paths=None)

    def test_single_pane_picker_and_review_use_the_original_selection(self):
        window, destination = self._window("left")
        source = os.path.join(destination, "source")
        os.makedirs(source)
        self.assertTrue(window._left_panel.navigateTo(source))
        original = os.path.join(source, "original.txt")
        review = mock.Mock()

        with mock.patch.object(window._left_panel, "selectedPaths", return_value=[original]) as selection, \
                mock.patch.object(window._transfer_queue, "enqueueMove") as enqueue, \
                mock.patch.object(QFileDialog, "getExistingDirectory", return_value="") as picker, \
                mock.patch.object(TransferReviewDialog, "exec_", lambda dialog: review(dialog)):
            window._onMoveToOther()
            review.assert_not_called()
            enqueue.assert_not_called()

            def pick_folder(*args):
                selection.return_value = [os.path.join(source, "new.txt")]
                return destination

            picker.side_effect = pick_folder

            def show_review(dialog):
                self.assertIn("To · Chosen folder", [item.text() for item in dialog.findChildren(QLabel)])
                self.assertEqual([item.text() for item in dialog.findChildren(QLineEdit)], [source, destination])
                return QDialog.Rejected

            review.side_effect = show_review
            window._onMoveToOther()
            enqueue.assert_not_called()

            selection.return_value = [original]
            review.side_effect = None
            review.return_value = QDialog.Accepted
            window._onMoveToOther()
            enqueue.assert_called_once_with([original], destination, relative_paths=None)

            # The same picker serves the keep-structure entry point.
            with mock.patch.object(window._left_panel, "selectedTransferSpecs") as specs, \
                    mock.patch.object(window._transfer_queue, "enqueueCopy") as copy:
                specs.return_value = ([{"full_path": original, "relative_path": "sub/original.txt"}], "")
                window._onSpecialCopyKeepStructure()
                copy.assert_called_once_with([original], destination, relative_paths=["sub/original.txt"])

    def test_archive_selection_uses_the_same_single_pane_picker(self):
        window, destination = self._window("left")
        archive = os.path.join(destination, "sample.zip")
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("notes.txt", "example")
        member = os.path.join(archive, "notes.txt")
        pane = window._left_panel
        with mock.patch.object(pane, "isInArchive", return_value=True), \
                mock.patch.object(pane, "currentPath", return_value=archive), \
                mock.patch.object(pane, "selectedPaths", return_value=[member]), \
                mock.patch.object(window, "_chooseTransferFolder", return_value=destination) as picker, \
                mock.patch.object(window, "_reviewTransfer", return_value=True) as review, \
                mock.patch.object(window, "_queueExtract") as extract:
            window._onCopyToOther()
            picker.assert_called_once_with("Extract", destination)
            self.assertTrue(review.call_args.kwargs["chosen_folder"])
            extract.assert_called_once_with(archive, destination, ["notes.txt"])

    def test_conflict_choices_affect_real_files(self):
        for choice in (CONFLICT_OVERWRITE, CONFLICT_KEEP_BOTH, CONFLICT_SKIP, CONFLICT_CANCEL):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as root:
                srcdir, destdir = os.path.join(root, 'src'), os.path.join(root, 'dest')
                os.mkdir(srcdir)
                os.mkdir(destdir)
                source, dest = os.path.join(srcdir, 'a'), os.path.join(destdir, 'a')
                with open(source, 'w') as stream:
                    stream.write('incoming')
                with open(dest, 'w') as stream:
                    stream.write('existing')
                worker = FileOperationWorker('copy', [source], destdir)
                def answer(*args):
                    new = os.path.join(destdir, 'a (1)') if choice == CONFLICT_KEEP_BOTH else None
                    worker.setConflictResponse(choice, new, False)
                worker.conflictDetected.connect(answer, Qt.DirectConnection)
                worker.run()
                with open(dest) as stream:
                    self.assertEqual(stream.read(), 'incoming' if choice == CONFLICT_OVERWRITE else 'existing')
                if choice == CONFLICT_KEEP_BOTH:
                    with open(os.path.join(destdir, 'a (1)')) as stream:
                        self.assertEqual(stream.read(), 'incoming')

    def test_details_order_running_then_pending_then_finished(self):
        queue = FileOperationQueue()
        queue._tasks = [FileOperationTask('done', 'copy', ['/a'], '/b', status='completed'),
                        FileOperationTask('wait', 'copy', ['/c'], '/d', status=STATUS_PENDING),
                        FileOperationTask('run', 'copy', ['/e'], '/f', status=STATUS_RUNNING)]
        dialog = TransfersDetailsDialog(queue)
        self.assertEqual([t.id for t in dialog._orderedTasks()], ['run', 'wait', 'done'])
        self.assertIn('/ → /f', queue._tasks[-1].summaryLabel())
        dialog.close()


if __name__ == '__main__':
    unittest.main()
