"""
Total Commander Clone - Transfers Bar
Compact bottom row for active file transfers and a modeless details popup.
Closing the popup does not cancel operations.
"""

from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar,
    QPushButton, QDialog, QScrollArea, QWidget, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from file_operation_queue import (
    FileOperationQueue,
    FileOperationTask,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)
from file_operations import FileOperationWorker


# ------------------------------------------------------------
# Helper: status display text
# ------------------------------------------------------------
def _statusText(status):
    return {
        STATUS_PENDING: "Queued",
        STATUS_RUNNING: "Running",
        STATUS_COMPLETED: "Done",
        STATUS_FAILED: "Failed",
        STATUS_CANCELLED: "Cancelled",
    }.get(status, status)


def _operationVerb(task):
    if not task:
        return "Transferring"
    names = {
        FileOperationWorker.OPERATION_COPY: "Copying",
        FileOperationWorker.OPERATION_MOVE: "Moving",
        FileOperationWorker.OPERATION_DELETE: "Deleting",
        "extract": "Extracting",
        "compress": "Compressing",
    }
    return names.get(task.operation, "Processing")


# ============================================================
# Class: TransfersBar
# Purpose: Single-line row above the F-key bar showing active
#          transfer progress. Click opens details popup.
# ============================================================
class TransfersBar(QFrame):

    detailsRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transfersBar")
        self.setVisible(False)
        self._initUI()

    def _initUI(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._summary_label = QLabel("Transferring...")
        self._summary_label.setObjectName("transfersSummary")
        self._summary_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self._summary_label, 1)

        self._progress = QProgressBar()
        self._progress.setObjectName("transfersProgress")
        self._progress.setRange(0, 100)
        self._progress.setFixedWidth(160)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("transfersCancel")
        self._cancel_btn.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self._cancel_btn)

        self.setCursor(Qt.PointingHandCursor)

    def cancelButton(self):
        return self._cancel_btn

    def updateFromQueue(self, queue: FileOperationQueue):
        active = queue.activeTask()
        pending = queue.pendingCount()
        if not active and pending == 0:
            self.setVisible(False)
            return

        self.setVisible(True)
        if active:
            verb = _operationVerb(active)
            name = active.current_file or "…"
            detail = active.detail or ""
            extra = f"  ·  +{pending} waiting" if pending else ""
            text = f"{verb}  {detail}  ·  {name}{extra}" if detail else f"{verb}  {name}{extra}"
            self._summary_label.setText(text.strip())
            self._progress.setValue(active.progress)
            self._cancel_btn.setEnabled(active.status == STATUS_RUNNING)
        else:
            self._summary_label.setText(f"{pending} transfer(s) queued")
            self._progress.setValue(0)
            self._cancel_btn.setEnabled(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._cancel_btn.geometry().contains(event.pos()):
                self.detailsRequested.emit()
                event.accept()
                return
        super().mousePressEvent(event)


# ============================================================
# Class: _TaskRowWidget
# Purpose: One row in the transfers details dialog.
# ============================================================
class _TaskRowWidget(QFrame):

    cancelRequested = pyqtSignal(str)

    def __init__(self, task: FileOperationTask, parent=None):
        super().__init__(parent)
        self._task_id = task.id
        self.setObjectName("transferTaskRow")
        self._build(task)

    def _build(self, task):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self._summary = QLabel(task.summaryLabel())
        self._summary.setWordWrap(True)
        top.addWidget(self._summary, 1)

        self._status = QLabel(_statusText(task.status))
        self._status.setObjectName("transferTaskStatus")
        top.addWidget(self._status)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFocusPolicy(Qt.NoFocus)
        self._cancel_btn.clicked.connect(lambda: self.cancelRequested.emit(self._task_id))
        top.addWidget(self._cancel_btn)
        layout.addLayout(top)

        self._file_label = QLabel("")
        self._file_label.setObjectName("transferTaskFile")
        layout.addWidget(self._file_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        layout.addWidget(self._progress)

        self.updateTask(task)

    def updateTask(self, task: FileOperationTask):
        self._summary.setText(task.summaryLabel())
        self._status.setText(_statusText(task.status))
        can_cancel = task.status in (STATUS_PENDING, STATUS_RUNNING)
        self._cancel_btn.setVisible(can_cancel)
        self._cancel_btn.setEnabled(can_cancel)

        if task.status == STATUS_RUNNING:
            self._file_label.setText(
                f"{task.current_file}" if task.current_file else task.detail
            )
            self._progress.setVisible(True)
            self._progress.setValue(task.progress)
        elif task.status == STATUS_PENDING:
            self._file_label.setText("Waiting in queue…")
            self._progress.setVisible(False)
        else:
            self._file_label.setText(task.message or "")
            self._progress.setVisible(task.status == STATUS_COMPLETED)
            self._progress.setValue(100 if task.status == STATUS_COMPLETED else task.progress)


# ============================================================
# Class: TransfersDetailsDialog
# Purpose: Modeless popup listing all transfer tasks.
#          Safe to close — operations continue in background.
# ============================================================
class TransfersDetailsDialog(QDialog):

    def __init__(self, queue: FileOperationQueue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self._rows = {}
        self.setWindowTitle("File Transfers")
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(520)
        self.setMinimumHeight(280)
        self._initUI()
        self._rebuildRows()

    def _initUI(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch(1)
        scroll.setWidget(self._list_container)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._clear_btn = QPushButton("Clear completed")
        self._clear_btn.clicked.connect(self._onClearCompleted)
        btn_row.addWidget(self._clear_btn)
        layout.addLayout(btn_row)

    def _rebuildRows(self):
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for task in self._queue.tasks():
            row = _TaskRowWidget(task, self._list_container)
            row.cancelRequested.connect(self._queue.cancelTask)
            self._rows[task.id] = row
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

        self._clear_btn.setEnabled(
            any(
                t.status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)
                for t in self._queue.tasks()
            )
        )

    def onTaskAdded(self, task):
        row = _TaskRowWidget(task, self._list_container)
        row.cancelRequested.connect(self._queue.cancelTask)
        self._rows[task.id] = row
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._clear_btn.setEnabled(True)

    def onTaskUpdated(self, task):
        row = self._rows.get(task.id)
        if row:
            row.updateTask(task)

    def onTaskFinished(self, task, success, message):
        row = self._rows.get(task.id)
        if row:
            row.updateTask(task)

    def _onClearCompleted(self):
        self._queue.clearCompleted()
        self._rebuildRows()
        if not self._queue.tasks():
            self._clear_btn.setEnabled(False)

    def closeEvent(self, event):
        """Closing is safe — queue keeps running."""
        event.accept()
