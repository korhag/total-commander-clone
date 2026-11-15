"""Transfer route review, conflict choices and queue presentation."""
import os
import tempfile
import unittest
from unittest import mock

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit

from file_operations import (ConflictDialog, FileOperationWorker, CONFLICT_KEEP_BOTH,
                             CONFLICT_OVERWRITE, CONFLICT_SKIP, CONFLICT_CANCEL)
from file_manager_app import FileManagerApp
from file_operation_queue import FileOperationQueue, FileOperationTask, STATUS_PENDING, STATUS_RUNNING
from transfer_review_dialog import TransferReviewDialog
from transfers_bar import TransfersDetailsDialog

_APP = QApplication.instance() or QApplication([])


class TransferUiTests(unittest.TestCase):
    def test_review_shows_captured_route_and_structure_example(self):
        dialog = TransferReviewDialog('Copy', ['/source/sub/a'], '/source', '/target', 'Left', ['sub/a'])
        texts = [field.text() for field in dialog.findChildren(QLineEdit)]
        self.assertEqual(texts, ['/source', '/target', '/source/sub/a', '/target/sub/a'])
        self.assertTrue(all(field.isReadOnly() for field in dialog.findChildren(QLineEdit)))
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.Rejected)

    def test_conflict_plain_paths_and_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, '<incoming>')
            dest = os.path.join(directory, '<existing>')
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
        window = mock.Mock()
        window._activePanelReady.return_value = True
        window._active_panel.isInArchive.return_value = False
        window._active_panel.selectedPaths.return_value = ['/source/a']
        destination = window._getInactivePanel.return_value
        destination.currentPath.return_value = '/destination'
        def accept_and_change_panes(*args):
            window._active_panel.selectedPaths.return_value = ['/different/b']
            destination.currentPath.return_value = '/elsewhere'
            return True
        window._reviewTransfer.side_effect = accept_and_change_panes
        FileManagerApp._onCopyToOther(window)
        window._transfer_queue.enqueueCopy.assert_called_once_with(['/source/a'], '/destination')
        window._transfer_queue.reset_mock()
        window._reviewTransfer.side_effect = None
        window._reviewTransfer.return_value = False
        FileManagerApp._onCopyToOther(window)
        window._transfer_queue.enqueueCopy.assert_not_called()

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
