"""
Built-in viewer: text, images, and a hex dump, plus F3 stepping
and the Ctrl+Q quick-view pane.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from unittest import mock

from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from file_manager_app import FileManagerApp
from file_panel import FilePanel
from file_viewer import (
    HEX_PREVIEW_LIMIT,
    TEXT_PREVIEW_LIMIT,
    FileViewerWidget,
    FileViewerWindow,
    buildPreview,
    formatHexDump,
    openInSystemEditor,
)
from settings_manager import SettingsManager


_APP = QApplication.instance() or QApplication([])


def _write(path, data):
    mode = "wb" if isinstance(data, bytes) else "w"
    encoding = None if isinstance(data, bytes) else "utf-8"
    with open(path, mode, encoding=encoding) as handle:
        handle.write(data)


def _select_name(panel, name):
    source = panel._source_model
    proxy = panel._proxy_model
    for row in range(source.rowCount()):
        entry = source.entryAt(row)
        if not entry or entry["name"] != name:
            continue
        proxy_index = proxy.mapFromSource(source.index(row, 0))
        panel.tableView().selectRow(proxy_index.row())
        return
    raise AssertionError(name)


def _wait_until(predicate):
    for _ in range(150):
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Preview did not finish")


def _preview_text(viewer, expected):
    return viewer._stack.currentWidget() is viewer._text and viewer._text.toPlainText() == expected


# ------------------------------------------------------------
# Class: TestBuildPreview
# Purpose: The viewer chooses image, text, or hex without
#          reading a whole huge file into the window.
# ------------------------------------------------------------
class TestBuildPreview(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_text_and_truncation(self):
        path = os.path.join(self.root, "notes.txt")
        _write(path, "a" * (TEXT_PREVIEW_LIMIT + 20))
        preview = buildPreview(path)
        self.assertEqual(preview["kind"], "text")
        self.assertTrue(preview["truncated"])
        self.assertEqual(len(preview["text"]), TEXT_PREVIEW_LIMIT)

    def test_utf8_text(self):
        path = os.path.join(self.root, "hello.txt")
        _write(path, "café\n")
        preview = buildPreview(path)
        self.assertEqual(preview["kind"], "text")
        self.assertIn("café", preview["text"])

    def test_binary_is_hex(self):
        path = os.path.join(self.root, "data.bin")
        _write(path, b"\x00\x01\x02hello")
        preview = buildPreview(path)
        self.assertEqual(preview["kind"], "hex")
        self.assertIn("00 01 02", preview["text"])
        self.assertFalse(preview["truncated"])

    def test_hex_is_capped(self):
        path = os.path.join(self.root, "big.bin")
        _write(path, b"\x00" * (HEX_PREVIEW_LIMIT + 32))
        preview = buildPreview(path)
        self.assertEqual(preview["kind"], "hex")
        self.assertTrue(preview["truncated"])
        self.assertLessEqual(preview["text"].count("\n") + 1, (HEX_PREVIEW_LIMIT // 16) + 1)

    def test_missing_and_folder(self):
        self.assertEqual(buildPreview(os.path.join(self.root, "nope.txt"))["kind"], "missing")
        self.assertEqual(buildPreview(self.root)["kind"], "folder")

    def test_image(self):
        path = os.path.join(self.root, "dot.png")
        image = QImage(2, 2, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(path, "PNG"))
        preview = buildPreview(path)
        self.assertEqual(preview["kind"], "image")

    def test_hex_dump_layout(self):
        dump = formatHexDump(b"A" * 16)
        self.assertTrue(dump.startswith("00000000  "))
        self.assertTrue(dump.endswith("A" * 16))

    def test_editor_refuses_a_missing_file(self):
        ok, message = openInSystemEditor(os.path.join(self.root, "missing.txt"))
        self.assertFalse(ok)
        self.assertIn("Select a file", message)

    def test_editor_starts_notepad_on_windows(self):
        path = os.path.join(self.root, "edit.txt")
        _write(path, "hi")
        with mock.patch("file_viewer.subprocess.Popen") as popen:
            with mock.patch("file_viewer.os.name", "nt"):
                ok, message = openInSystemEditor(path)
        self.assertTrue(ok)
        self.assertEqual(message, "")
        popen.assert_called_once_with(["notepad.exe", path])


# ------------------------------------------------------------
# Class: TestViewerWindow
# Purpose: The widget shows file text, and N moves to the
#          next file in the panel.
# ------------------------------------------------------------
class TestViewerWindow(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write(os.path.join(self.root, "a.txt"), "alpha")
        os.makedirs(os.path.join(self.root, "folder"))
        _write(os.path.join(self.root, "b.txt"), "bravo")
        self.panel = FilePanel("left")
        self.assertTrue(self.panel.navigateTo(self.root))
        QTest.qWait(0)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(0)
        self._tmp.cleanup()

    def test_widget_shows_text(self):
        widget = FileViewerWidget()
        widget.showPath(os.path.join(self.root, "a.txt"))
        _wait_until(lambda: _preview_text(widget, "alpha"))
        widget.deleteLater()

    def test_latest_selection_wins_without_queuing_intermediate_previews(self):
        widget = FileViewerWidget()
        first = os.path.join(self.root, "a.txt")
        last = os.path.join(self.root, "b.txt")
        started = threading.Event()
        release = threading.Event()

        def delayed(path):
            if path == first:
                started.set()
                release.wait(2)
            return buildPreview(path)

        with mock.patch("file_viewer.buildPreview", side_effect=delayed) as read:
            try:
                widget.showPath(first)
                _wait_until(started.is_set)
                widget.showPath(os.path.join(self.root, "middle.txt"))
                widget.showPath(last)
                self.assertEqual(widget._title.text(), "b.txt")
                self.assertIn("Loading", widget._message.text())
                release.set()
                _wait_until(lambda: _preview_text(widget, "bravo"))
                self.assertEqual([call.args[0] for call in read.call_args_list], [first, last])
            finally:
                release.set()
                widget.deleteLater()

    def test_hiding_invalidates_an_in_progress_preview(self):
        widget = FileViewerWidget()
        widget.show()
        started = threading.Event()
        release = threading.Event()

        def delayed(path):
            started.set()
            release.wait(2)
            return buildPreview(path)

        with mock.patch("file_viewer.buildPreview", side_effect=delayed):
            try:
                widget.showPath(os.path.join(self.root, "a.txt"))
                _wait_until(started.is_set)
                widget.hide()
                release.set()
                _wait_until(lambda: widget._thread is None)
                self.assertEqual(widget.currentPath(), "")
                self.assertIs(widget._stack.currentWidget(), widget._message)
            finally:
                release.set()
                widget.deleteLater()

    def test_step_skips_folders(self):
        _select_name(self.panel, "a.txt")
        window = FileViewerWindow()
        window.viewPanelFile(self.panel)
        self.assertTrue(window.viewerWidget().currentPath().endswith("a.txt"))
        window._step(1)
        self.assertTrue(window.viewerWidget().currentPath().endswith("b.txt"))
        _wait_until(lambda: _preview_text(window.viewerWidget(), "bravo"))
        window.close()
        window.deleteLater()


# ------------------------------------------------------------
# Class: TestQuickView
# Purpose: Ctrl+Q shows the other panel's preview and follows
#          the selection.
# ------------------------------------------------------------
class TestQuickView(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write(os.path.join(self.root, "one.txt"), "one")
        _write(os.path.join(self.root, "two.txt"), "two")
        self.settings = SettingsManager(self.root, enable_backup=False)
        self.window = FileManagerApp(self.settings)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(0)
        self._tmp.cleanup()

    def test_quick_view_follows_the_other_panel(self):
        left = self.window._left_panel
        self.assertTrue(left.navigateTo(self.root))
        QTest.qWait(0)
        self.window._setActivePanel(left)
        _select_name(left, "one.txt")
        self.window._onToggleQuickView()
        self.assertIs(
            self.window._right_stack.currentWidget(),
            self.window._right_quick_view,
        )
        self.assertTrue(self.window._right_quick_view.currentPath().endswith("one.txt"))
        _wait_until(lambda: _preview_text(self.window._right_quick_view, "one"))

        _select_name(left, "two.txt")
        self.assertTrue(self.window._right_quick_view.currentPath().endswith("two.txt"))
        _wait_until(lambda: _preview_text(self.window._right_quick_view, "two"))

        self.window._onToggleQuickView()
        self.assertIs(self.window._right_stack.currentWidget(), self.window._right_panel)
