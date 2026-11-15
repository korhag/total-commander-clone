"""Search and execute commands from the main window."""
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout)


class CommandDialog(QDialog):
    def __init__(self, commands, availability, parent=None):
        super().__init__(parent)
        self.commands = commands
        self.availability = availability
        self.chosen = None
        self.setWindowTitle('Commands and shortcuts')
        self.resize(600, 480)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search commands or shortcuts…')
        self.search.setAccessibleName('Search commands and shortcuts')
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(['Command', 'Shortcut', 'Applies to'])
        self.results.setRootIsDecorated(False)
        self.results.setColumnWidth(0, 240)
        self.results.setColumnWidth(1, 135)
        layout.addWidget(self.results)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        layout.addWidget(self.reason)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.run_button = QPushButton('Run')
        self.run_button.setAutoDefault(False)
        self.run_button.clicked.connect(self.runSelected)
        buttons.addWidget(self.run_button)
        close = QPushButton('Close')
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.runSelected)
        self.results.itemSelectionChanged.connect(self.updateReason)
        self.results.itemDoubleClicked.connect(self.runSelected)
        self.results.itemActivated.connect(self.runSelected)
        self.refresh()
        self.search.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.search and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            count = self.results.topLevelItemCount()
            if count:
                current = self.results.indexOfTopLevelItem(self.results.currentItem())
                step = 1 if event.key() == Qt.Key_Down else -1
                index = max(0, min(count - 1, current + step if current >= 0 else 0))
                self.results.setCurrentItem(self.results.topLevelItem(index))
            return True
        return super().eventFilter(obj, event)

    def refresh(self):
        query = self.search.text().strip().casefold()
        matches = []
        for command in self.commands:
            name = command['name']()
            keys = command['keys']
            native = ', '.join(key.toString(QKeySequence.NativeText) for key in keys)
            portable = ' '.join(key.toString(QKeySequence.PortableText) for key in keys)
            fields = ' '.join([name, command['scope'], portable, native] + command['aliases']).casefold()
            if not all(term in fields for term in query.split()):
                continue
            rank = 0 if query and (query == name.casefold() or query in [key.toString(QKeySequence.PortableText).casefold() for key in keys]) else 1 if query and name.casefold().startswith(query) else 2
            matches.append((rank, name.casefold(), name, native, command))
        self.results.clear()
        for _, _, name, native, command in sorted(matches, key=lambda row: (row[0], row[1])):
            item = QTreeWidgetItem([name, native or 'No shortcut', command['scope']])
            item.setData(0, Qt.UserRole, command['id'])
            if command.get('checked'):
                item.setCheckState(0, Qt.Checked if command['checked']() else Qt.Unchecked)
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            self.results.addTopLevelItem(item)
        if query and matches:
            self.results.setCurrentItem(self.results.topLevelItem(0))
        self.reason.setText('No commands match' if not matches else '')
        self.updateReason()

    def selectedCommand(self):
        item = self.results.currentItem()
        if item is None:
            return None
        command_id = item.data(0, Qt.UserRole)
        return next((command for command in self.commands if command['id'] == command_id), None)

    def updateReason(self):
        command = self.selectedCommand()
        reason = self.availability(command) if command else ''
        if command:
            self.reason.setText(reason)
        elif self.results.topLevelItemCount():
            self.reason.clear()
        self.run_button.setEnabled(bool(command) and not reason)

    def runSelected(self, *_args):
        command = self.selectedCommand()
        if command is None:
            return
        reason = self.availability(command)
        if reason:
            self.reason.setText(reason)
            self.run_button.setEnabled(False)
            return
        self.chosen = command
        self.accept()
