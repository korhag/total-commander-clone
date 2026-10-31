"""
File-type icons from the sheet, and folders tinted by the theme.
"""

from __future__ import annotations

import unittest

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication

import file_icons


_APP = QApplication.instance() or QApplication([])


def _bodyColor(icon):
    """A pixel in the folder body, ignoring the transparent margin."""
    image = icon.pixmap(64, 64).toImage()
    return QColor(image.pixel(32, 40))


# ------------------------------------------------------------
# Class: TestIconKind
# Purpose: Extensions land on the right picture.
# ------------------------------------------------------------
class TestIconKind(unittest.TestCase):

    def test_folders_and_known_extensions(self):
        self.assertEqual(file_icons.iconKind("Photos", is_dir=True), "folder")
        self.assertEqual(file_icons.iconKind("pack.zip"), "archive")
        self.assertEqual(file_icons.iconKind("pack.TAR.GZ"), "archive")
        self.assertEqual(file_icons.iconKind("shot.JPEG"), "image")
        self.assertEqual(file_icons.iconKind("clip.mp4"), "video")
        self.assertEqual(file_icons.iconKind("song.flac"), "audio")
        self.assertEqual(file_icons.iconKind("plan.dwg"), "cad")
        self.assertEqual(file_icons.iconKind("book.xlsx"), "sheet")
        self.assertEqual(file_icons.iconKind("letter.docx"), "document")
        self.assertEqual(file_icons.iconKind("spec.pdf"), "pdf")
        self.assertEqual(file_icons.iconKind("notes.txt"), "file")

    def test_icons_come_from_the_sheet(self):
        file_icons._resetForTests()
        icon = file_icons.iconFor("pack.zip")
        self.assertFalse(icon.isNull())
        self.assertIn("archive", file_icons._pixmaps)
        self.assertFalse(file_icons._pixmaps["archive"].isNull())

    def test_folder_color_follows_the_accent(self):
        file_icons._resetForTests()
        file_icons.setAccent("#ff0000")
        red = _bodyColor(file_icons.iconFor("Dir", is_dir=True))
        file_icons.setAccent("#0000ff")
        blue = _bodyColor(file_icons.iconFor("Dir", is_dir=True))
        self.assertGreater(red.red(), red.blue())
        self.assertGreater(blue.blue(), blue.red())

    def test_missing_strip_does_not_raise(self):
        file_icons._resetForTests()
        file_icons._strip_override = "/no/such/icon-strip.png"
        icon = file_icons.iconFor("notes.txt")
        folder = file_icons.iconFor("Dir", is_dir=True)
        self.assertFalse(icon.isNull())
        self.assertFalse(folder.isNull())
        file_icons._resetForTests()


if __name__ == "__main__":
    unittest.main()
