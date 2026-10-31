"""
Total Commander Clone - Small theme list with a live preview.

Five names are visible. A click applies that theme. Holding the
original-theme button shows it again until the button is released.
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


# Two names above the highlight, the highlight, and two below.
VISIBLE_ROWS = 5


# ------------------------------------------------------------
# Class: ThemePreviewDialog
# Purpose: Pick a theme while the app updates on each click.
#          Accept keeps the highlight. Cancel restores the
#          theme that was active when the window opened.
# ------------------------------------------------------------
class ThemePreviewDialog(QDialog):

    def __init__(self, choices, current_id, on_preview, parent=None):
        super().__init__(parent)
        self._choices = list(choices)
        self._original_id = current_id
        self._on_preview = on_preview
        self._chosen = None
        self._sized = False
        self._pending_id = None
        self._preview_scheduled = False
        self.setWindowTitle("Theme")
        self.setWindowModality(Qt.WindowModal)
        self.setModal(True)

        layout = QVBoxLayout(self)
        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._labels = {}
        selected = None
        for theme_id, label in self._choices:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, theme_id)
            self._list.addItem(item)
            self._labels[theme_id] = label
            if theme_id == current_id:
                selected = item
        if selected is None and self._list.count():
            selected = self._list.item(0)
            self._original_id = selected.data(Qt.UserRole)
        if selected is not None:
            self._list.setCurrentItem(selected)
        self._list.itemClicked.connect(self._onItemClicked)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        self._accept = QPushButton("Accept", self)
        self._accept.clicked.connect(self._onAccept)
        self._compare = QPushButton(self._labelFor(self._original_id), self)
        self._compare.setToolTip(
            "Hold to see the theme that was active when this window opened.\n"
            "Release to return to the highlighted theme."
        )
        self._compare.pressed.connect(self._showOriginal)
        self._compare.released.connect(self._showHighlighted)
        self._cancel = QPushButton("Cancel", self)
        self._cancel.clicked.connect(self._onCancel)
        buttons.addWidget(self._accept)
        buttons.addWidget(self._compare)
        buttons.addWidget(self._cancel)
        layout.addLayout(buttons)

        metrics = self.fontMetrics()
        widest = 0
        for _theme_id, label in self._choices:
            widest = max(widest, metrics.horizontalAdvance(label))
        self._list.setMinimumWidth(widest + 48)

    # --------------------------------------------------------
    # Method: chosenTheme
    # Purpose: The theme Accept kept, or None when the window
    #          was cancelled.
    # --------------------------------------------------------
    def chosenTheme(self):
        return self._chosen

    # --------------------------------------------------------
    # Method: visibleRowCount
    # Purpose: How many theme names the list is built to show.
    # --------------------------------------------------------
    def visibleRowCount(self):
        return VISIBLE_ROWS

    # --------------------------------------------------------
    # Method: showEvent
    # Purpose: Size the list to five rows and keep the current
    #          name in the middle when that is possible.
    # --------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if self._sized:
            return
        row = max(1, self._list.sizeHintForRow(0))
        frame = self._list.frameWidth() * 2
        self._list.setFixedHeight(row * VISIBLE_ROWS + frame)
        self._sized = True
        self._centerOnCurrent()
        self.adjustSize()

    # --------------------------------------------------------
    # Method: closeEvent
    # Purpose: The window's close button is the same as Cancel.
    # --------------------------------------------------------
    def closeEvent(self, event):
        if self.result() != QDialog.Accepted:
            self._preview(self._original_id)
            self._applyPending()
        super().closeEvent(event)

    def _labelFor(self, theme_id):
        return self._labels.get(theme_id, str(theme_id or ""))

    def _highlightedId(self):
        item = self._list.currentItem()
        if item is None:
            return self._original_id
        return item.data(Qt.UserRole)

    def _centerOnCurrent(self):
        item = self._list.currentItem()
        if item is not None:
            self._list.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _preview(self, theme_id):
        """Remember the theme and apply it once the click has painted."""
        if not theme_id or self._on_preview is None:
            return
        self._pending_id = theme_id
        if self._preview_scheduled:
            return
        self._preview_scheduled = True
        QTimer.singleShot(0, self._flushPreview)

    def _flushPreview(self):
        self._preview_scheduled = False
        self._applyPending()

    def _applyPending(self):
        theme_id = self._pending_id
        self._pending_id = None
        if theme_id and self._on_preview is not None:
            self._on_preview(theme_id)

    def _onItemClicked(self, item):
        self._list.setCurrentItem(item)
        self._centerOnCurrent()
        self._preview(item.data(Qt.UserRole))

    def _showOriginal(self):
        self._preview(self._original_id)

    def _showHighlighted(self):
        self._preview(self._highlightedId())

    def _onAccept(self):
        chosen = self._highlightedId()
        self._preview(chosen)
        self._applyPending()
        self._chosen = chosen
        self.accept()

    def _onCancel(self):
        self._preview(self._original_id)
        self._applyPending()
        self._chosen = None
        self.reject()
