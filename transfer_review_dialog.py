"""Confirmation of the captured route for a pane-to-pane transfer."""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


class TransferReviewDialog(QDialog):
    def __init__(self, operation, paths, source, destination, source_side,
                 relative_paths=None, parent=None, search_root=False):
        super().__init__(parent)
        self.setWindowTitle(f"Review {operation.lower()}")
        self.resize(600, 300)
        layout = QVBoxLayout(self)
        count = len(paths)
        heading = QLabel(f"{operation} {count} {'item' if count == 1 else 'items'}")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        recursive = any(os.path.normcase(os.path.dirname(p)) != os.path.normcase(source)
                        for p in paths)
        destination_side = 'Right' if source_side == 'Left' else 'Left'
        for title, path in ((f"From · {source_side} pane" + (' · Search root' if recursive or search_root else ''), source),
                            (f"To · {destination_side} pane", destination)):
            layout.addWidget(QLabel(title))
            field = QLineEdit(path)
            field.setReadOnly(True)
            field.setToolTip(path)
            layout.addWidget(field)
        if recursive or relative_paths:
            index = next((i for i, p in enumerate(paths)
                          if os.path.normcase(os.path.dirname(p)) != os.path.normcase(source)), 0)
            name = relative_paths[index] if relative_paths else os.path.basename(paths[index])
            layout.addWidget(QLabel('Intended route example:'))
            for path in (paths[index], os.path.join(destination, name)):
                field = QLineEdit(path)
                field.setReadOnly(True)
                field.setToolTip(path)
                layout.addWidget(field)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        confirm = buttons.addButton(operation, QDialogButtonBox.AcceptRole)
        confirm.setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
