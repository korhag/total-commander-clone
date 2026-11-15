"""
Waypane - File Operation Queue
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
    archive_path: str = ""
    members: Optional[List[str]] = None
    archive_format: str = ""
    password: str = ""
    compression_level: str = ""
    base_dir: str = ""
    waiting_for_decision: bool = False

    def summaryLabel(self):
        """Short label for list rows and the transfers bar."""
        count = len(self.source_paths)
        op_names = {
            FileOperationWorker.OPERATION_COPY: "Copy",
            FileOperationWorker.OPERATION_MOVE: "Move",
            FileOperationWorker.OPERATION_DELETE: "Delete",
            "extract": "Extract",
            "compress": "Compress",
        }
        op = op_names.get(self.operation, self.operation.capitalize())
        if self.relative_paths:
            op = f"{op} (structure)"
        if self.operation == FileOperationWorker.OPERATION_DELETE:
            return f"{op} {count} item(s)"
        if self.operation in (FileOperationWorker.OPERATION_COPY, FileOperationWorker.OPERATION_MOVE):
            parents = list(dict.fromkeys(os.path.dirname(path) for path in self.source_paths))
            source = parents[0] if len(parents) == 1 else "Multiple source folders"
            return f"{op} {count} {'item' if count == 1 else 'items'} · {source} → {self.destination}"
        return f"{op} {count} item(s) → {self.destination}"



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
        self._conflict_dialog = None

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

    def enqueueExtract(
        self,
        archive_path,
        destination,
        members=None,
        password="",
        on_success=None,
    ):
        """Extract a whole archive (members is None) or those members."""
        sources = list(members) if members else [archive_path]
        return self._enqueue(
            "extract",
            sources,
            destination,
            on_success,
            archive_path=archive_path,
            members=list(members) if members else None,
            password=password or "",
        )

    def enqueueCompress(
        self,
        sources,
        archive_out,
        fmt,
        level,
        password="",
        base_dir="",
        on_success=None,
    ):
        """Create one archive. archive_out is the new file, not a folder."""
        return self._enqueue(
            "compress",
            sources,
            archive_out,
            on_success,
            archive_format=fmt or "zip",
            password=password or "",
            compression_level=level or "normal",
            base_dir=base_dir or "",
        )

    def cancelActive(self):
        """Cancel the currently running task."""
        if self._current_task and self._worker:
            self._worker.cancel()
            if self._conflict_dialog is not None:
                self._conflict_dialog.reject()

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
            self.cancelActive()

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
        if self._conflict_dialog is not None:
            self._conflict_dialog.reject()
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
        archive_path="",
        members=None,
        archive_format="",
        password="",
        compression_level="",
        base_dir="",
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
            archive_path=archive_path or "",
            members=list(members) if members else None,
            archive_format=archive_format or "",
            password=password or "",
            compression_level=compression_level or "",
            base_dir=base_dir or "",
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

        self._worker = self._createWorker(task)
        self._worker.progressChanged.connect(self._onProgress)
        self._worker.operationFinished.connect(self._onFinished)
        self._worker.errorOccurred.connect(self._onError)
        if task.operation in (
            FileOperationWorker.OPERATION_COPY,
            FileOperationWorker.OPERATION_MOVE,
            "extract",
        ):
            self._worker.conflictDetected.connect(self._onConflictDetected)
        self._worker.start()

    def _createWorker(self, task):
        """Pick the thread class for this operation."""
        if task.operation == "extract":
            from archive_operations import ArchiveExtractWorker

            return ArchiveExtractWorker(
                task.archive_path,
                task.members,
                task.destination,
                password=task.password,
                parent=self,
            )
        if task.operation == "compress":
            from archive_operations import ArchiveCompressWorker

            return ArchiveCompressWorker(
                task.source_paths,
                task.destination,
                task.archive_format,
                task.compression_level,
                password=task.password,
                base_dir=task.base_dir,
                parent=self,
            )
        return FileOperationWorker(
            task.operation,
            task.source_paths,
            task.destination,
            self,
            relative_paths=task.relative_paths,
        )

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
        worker = self._worker
        op_name = {FileOperationWorker.OPERATION_COPY: "Copy", "extract": "Extract"}.get(task.operation, "Move")
        dialog = ConflictDialog(source_path, dest_path, op_name, self._parent_window)
        self._conflict_dialog = dialog
        task.waiting_for_decision = True
        self.taskUpdated.emit(task)
        try:
            accepted = dialog.exec_() == QDialog.Accepted
        finally:
            if self._conflict_dialog is dialog:
                self._conflict_dialog = None
            task.waiting_for_decision = False
            self.taskUpdated.emit(task)
        if self._current_task is not task or self._worker is not worker:
            return
        choice, apply_to_all = dialog.getChoice() if accepted else (CONFLICT_CANCEL, False)
        if not choice or choice == CONFLICT_CANCEL:
            worker.setConflictResponse(CONFLICT_CANCEL, apply_to_all=False)
            return
        new_dest = _resolveConflictPath(dest_path) if choice == CONFLICT_KEEP_BOTH else None
        worker.setConflictResponse(choice, new_dest, apply_to_all)

    def _onFinished(self, success, message):
        task = self._current_task
        worker = self._worker
        if self._conflict_dialog is not None:
            self._conflict_dialog.reject()
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
