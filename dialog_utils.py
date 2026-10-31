"""
Total Commander Clone - Shared dialog helpers
Small prompts used by more than one panel.
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDialog, QInputDialog, QLineEdit


# ------------------------------------------------------------
# Function: askText
# Purpose: Ask for a short name on the main window. The line edit
#          is focused on the next turn, after any drag or menu
#          has released the keyboard.
# ------------------------------------------------------------
def askText(parent, title, label, text):
    window = parent.window() if parent is not None else None
    dialog = QInputDialog(window or parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextValue(text or "")
    dialog.setInputMode(QInputDialog.TextInput)
    dialog.setWindowModality(Qt.ApplicationModal)
    line = dialog.findChild(QLineEdit)

    def _focusLine():
        dialog.activateWindow()
        if line is None:
            return
        line.setFocus()
        line.selectAll()

    QTimer.singleShot(0, _focusLine)
    if dialog.exec_() != QDialog.Accepted:
        return ""
    return dialog.textValue().strip()
