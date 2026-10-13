"""
Total Commander Clone - File Operation Queue
Non-blocking FIFO queue for copy, move, and delete operations.
Runs one FileOperationWorker at a time and emits signals for UI updates.
"""

import os
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QDialog

from file_operations import (
    FileOperationWorker,
    ConflictDialog,
    CONFLICT_CANCEL,
    CONFLICT_KEEP_BOTH,
    _resolveConflictPath,
)


# ------------------------------------------------------------
# Task status constants
# ------------------------------------------------------------
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


# ============================================================
# Class: FileOperationTask
# Purpose: Represents a single queued file operation.
# ============================================================
@dataclass
class FileOperationTask:
    id: str
    operation: str
    source_paths: List[str]
    destination: str = ""
    status: str = STATUS_PENDING
    progress: int = 0
    current_file: str = ""
    detail: str = ""
    message: str = ""
    clear_clipboard_on_success: bool = False
    relative_paths: Optional[List[str]] = None
    on_success: Optional[Callable[[], None]] = field(default=None, repr=False)

    def summaryLabel(self):
        """Short label for list rows and the transfers bar."""
        count = len(self.source_paths)
        op_names = {
            FileOperationWorker.OPERATION_COPY: "Copy",
            FileOperationWorker.OPERATION_MOVE: "Move",
            FileOperationWorker.OPERATION_DELETE: "Delete",
        }
        op = op_names.get(self.operation, self.operation.capitalize())
        if self.relative_paths:
            op = f"{op} (structure)"
        if self.operation == FileOperationWorker.OPERATION_DELETE:
            return f"{op} {count} item(s)"
        dest = self.destination or ""
        if len(dest) > 40:
            dest = "…" + dest[-37:]
        return f"{op} {count} item(s) → {dest}"


# ============================================================
# Class: FileOperationQueue
# Purpose: FIFO queue manager; runs one worker at a time.
# ============================================================
class FileOperationQueue(QObject):

    taskAdded = pyqtSignal(object)
    taskUpdated = pyqtSignal(object)
    taskFinished = pyqtSignal(object, bool, str)
    queueIdle = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: List[FileOperationTask] = []
        self._worker: Optional[FileOperationWorker] = None
        self._current_task: Optional[FileOperationTask] = None
        self._parent_window = parent

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------
    def setParentWindow(self, window):
        """Main window used as parent for conflict dialogs."""
        self._parent_window = window

    def tasks(self):
        """Return a shallow copy of all tasks (including finished)."""
        return list(self._tasks)

    def activeTask(self):
        """Currently running task, or None."""
        return self._current_task

    def pendingCount(self):
        return sum(1 for t in self._tasks if t.status == STATUS_PENDING)

    def hasActiveWork(self):
        return any(
            t.status in (STATUS_PENDING, STATUS_RUNNING)
            for t in self._tasks
        )

    def enqueueCopy(self, file_paths, destination, on_success=None, relative_paths=None):
        return self._enqueue(
            FileOperationWorker.OPERATION_COPY,
            file_paths,
            destination,
            on_success,
            relative_paths=relative_paths,
        )

    def enqueueMove(
        self,
        file_paths,
        destination,
        on_success=None,
        clear_clipboard_on_success=False,
        relative_paths=None,
    ):
        return self._enqueue(
            FileOperationWorker.OPERATION_MOVE,
            file_paths,
            destination,
            on_success,
            clear_clipboard_on_success=clear_clipboard_on_success,
            relative_paths=relative_paths,
        )

    def enqueueDelete(self, file_paths):
        return self._enqueue(
            FileOperationWorker.OPERATION_DELETE, file_paths, ""
        )

    def cancelActive(self):
        """Cancel the currently running task."""
        if self._current_task and self._worker:
            self._worker.cancel()

    def cancelTask(self, task_id):
        """Cancel a pending task or the running task."""
        task = self._taskById(task_id)
        if not task:
            return
        if task.status == STATUS_PENDING:
            task.status = STATUS_CANCELLED
            task.message = "Cancelled."
            self.taskUpdated.emit(task)
            self.taskFinished.emit(task, False, task.message)
            self._tryStartNext()
            return
        if task.status == STATUS_RUNNING and self._worker:
            self._worker.cancel()

    def shutdown(self, timeout_ms):
        """Cancel pending and running work before the app exits.

        Returns True when no worker is left running after timeout_ms.
        """
        for task in self._tasks:
            if task.status == STATUS_PENDING:
                task.status = STATUS_CANCELLED
                task.message = "Cancelled."
        worker = self._worker
        if worker is None:
            return True
        worker.cancel()
        return worker.wait(timeout_ms)

    def clearCompleted(self):
        """Remove finished tasks from the list."""
        self._tasks = [
            t for t in self._tasks
            if t.status not in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)
        ]
        self._checkIdle()

    # --------------------------------------------------------
    # Internal enqueue / worker lifecycle
    # --------------------------------------------------------
    def _enqueue(
        self,
        operation,
        file_paths,
        destination,
        on_success=None,
        clear_clipboard_on_success=False,
        relative_paths=None,
    ):
        if not file_paths:
            return None
        rels = None
        if relative_paths is not None:
            rels = list(relative_paths)
            if len(rels) != len(file_paths):
                rels = None
        task = FileOperationTask(
            id=str(uuid.uuid4()),
            operation=operation,
            source_paths=list(file_paths),
            destination=destination or "",
            on_success=on_success,
            clear_clipboard_on_success=clear_clipboard_on_success,
            relative_paths=rels,
        )
        self._tasks.append(task)
        self.taskAdded.emit(task)
        self._tryStartNext()
        return task.id

    def _tryStartNext(self):
        if self._worker is not None:
            return
        for task in self._tasks:
            if task.status == STATUS_PENDING:
                self._startTask(task)
                return
        self._checkIdle()

    def _startTask(self, task):
        self._current_task = task
        task.status = STATUS_RUNNING
        task.progress = 0
        task.current_file = ""
        task.detail = "Preparing..."
        self.taskUpdated.emit(task)

        self._worker = FileOperationWorker(
            task.operation,
            task.source_paths,
            task.destination,
            self,
            relative_paths=task.relative_paths,
        )
        self._worker.progressChanged.connect(self._onProgress)
        self._worker.operationFinished.connect(self._onFinished)
        self._worker.errorOccurred.connect(self._onError)
        if task.operation in (
            FileOperationWorker.OPERATION_COPY,
            FileOperationWorker.OPERATION_MOVE,
        ):
            self._worker.conflictDetected.connect(self._onConflictDetected)
        self._worker.start()

    def _onProgress(self, percent, file_name, detail):
        task = self._current_task
        if not task:
            return
        task.progress = percent
        task.current_file = file_name or ""
        task.detail = detail or ""
        self.taskUpdated.emit(task)

    def _onError(self, file_name, error_msg):
        task = self._current_task
        if not task:
            return
        task.current_file = f"Error: {file_name} - {error_msg}"

    def _onConflictDetected(self, source_path, dest_path, file_name):
        task = self._current_task
        if not task or not self._worker:
            return
        op_name = "Copy" if task.operation == FileOperationWorker.OPERATION_COPY else "Move"
        parent = self._parent_window
        dialog = ConflictDialog(source_path, dest_path, op_name, parent)
        if dialog.exec_() != QDialog.Accepted:
            self._worker.setConflictResponse(CONFLICT_CANCEL, apply_to_all=False)
            return
        choice, apply_to_all = dialog.getChoice()
        if not choice or choice == CONFLICT_CANCEL:
            self._worker.setConflictResponse(CONFLICT_CANCEL, apply_to_all=False)
            return
        new_dest = None
        if choice == CONFLICT_KEEP_BOTH:
            new_dest = _resolveConflictPath(dest_path)
        self._worker.setConflictResponse(choice, new_dest, apply_to_all)

    def _onFinished(self, success, message):
        task = self._current_task
        worker = self._worker
        self._worker = None
        self._current_task = None

        if worker:
            worker.progressChanged.disconnect(self._onProgress)
            worker.operationFinished.disconnect(self._onFinished)
            worker.errorOccurred.disconnect(self._onError)
            try:
                worker.conflictDetected.disconnect(self._onConflictDetected)
            except TypeError:
                pass
            worker.wait(3000)

        if not task:
            self._tryStartNext()
            return

        task.message = message
        task.progress = 100 if success else task.progress
        if not success and "cancel" in message.lower():
            task.status = STATUS_CANCELLED
        elif success:
            task.status = STATUS_COMPLETED
            if task.on_success:
                task.on_success()
        else:
            task.status = STATUS_FAILED

        self.taskUpdated.emit(task)
        self.taskFinished.emit(task, success, message)
        self._tryStartNext()

    def _taskById(self, task_id):
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def _checkIdle(self):
        if not self.hasActiveWork():
            self.queueIdle.emit()
