"""
Archive paths, 7-Zip listing text, and extract/compress when 7-Zip is installed.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile

from PyQt5.QtWidgets import QApplication

from archive_backend import (
    ARCHIVE_EXTENSIONS,
    COMPRESS_FORMATS,
    archiveDisplayStem,
    archiveExtension,
    buildArchiveTree,
    clearArchiveCache,
    clearListingCache,
    find7zExecutable,
    listArchive,
    parseProgressPercent,
    parseSltRecords,
    splitArchivePath,
)
from archive_operations import ArchiveCompressWorker, ArchiveExtractWorker


_APP = QApplication.instance() or QApplication([])

_SLT_SAMPLE = """
Path = sample.zip
Type = zip

Path = docs
Folder = +
Modified = 2020-01-02 03:04:05

Path = docs/readme.txt
Folder = -
Size = 5
Modified = 2020-01-02 03:04:06
Encrypted = +

Path = photos/img.jpg
Folder = -
Size = 9
Modified = 2020-05-01 00:00:00
Encrypted = -
"""


def _run(worker):
    messages = []
    worker.operationFinished.connect(lambda ok, msg: messages.append((ok, msg)))
    worker.run()
    return messages


# ------------------------------------------------------------
# Class: TestArchivePaths
# Purpose: The panel path string is the only place an archive
#          location is stored.
# ------------------------------------------------------------
class TestArchivePaths(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _touch(self, name):
        path = os.path.join(self.root, name)
        with open(path, "wb"):
            pass
        return path

    def test_compound_extension_beats_final_suffix(self):
        self.assertEqual(archiveExtension("notes.tar.gz"), ".tar.gz")
        self.assertEqual(archiveExtension("notes.tgz"), ".tgz")
        self.assertEqual(archiveExtension("plain.txt"), "")

    def test_tar_gz_member_path(self):
        archive = self._touch("bundle.tar.gz")
        found, inner = splitArchivePath(os.path.join(archive, "dir", "file.txt"))
        self.assertEqual(found, archive)
        self.assertEqual(inner, "dir/file.txt")
        self.assertEqual(archiveDisplayStem(archive), "bundle")

    def test_directory_named_like_an_archive_is_not_one(self):
        folder = os.path.join(self.root, "notes.zip")
        os.makedirs(os.path.join(folder, "inner"))
        self.assertIsNone(splitArchivePath(os.path.join(folder, "inner", "a.txt")))
        self.assertIsNone(splitArchivePath(folder))

    def test_windows_separators(self):
        archive = self._touch("pack.zip")
        mixed = archive + "\\docs\\note.txt"
        found, inner = splitArchivePath(mixed)
        self.assertEqual(os.path.normcase(found), os.path.normcase(archive))
        self.assertEqual(inner, "docs/note.txt")

    def test_archive_file_itself_has_empty_member(self):
        archive = self._touch("pack.zip")
        found, inner = splitArchivePath(archive)
        self.assertEqual(found, archive)
        self.assertEqual(inner, "")


# ------------------------------------------------------------
# Class: TestSltParser
# Purpose: Tree building from a captured `7z l -slt` sample.
# ------------------------------------------------------------
class TestSltParser(unittest.TestCase):

    def test_implicit_folders_and_encrypted_flag(self):
        tree = buildArchiveTree(parseSltRecords(_SLT_SAMPLE))
        docs = tree.children["docs"]
        self.assertTrue(docs.is_dir)
        readme = docs.children["readme.txt"]
        self.assertFalse(readme.is_dir)
        self.assertEqual(readme.size, 5)
        self.assertTrue(readme.encrypted)
        self.assertEqual(readme.member, "docs/readme.txt")
        photos = tree.children["photos"]
        self.assertTrue(photos.is_dir)
        self.assertFalse(photos.children["img.jpg"].encrypted)
        self.assertNotIn("sample.zip", tree.children)

    def test_sevenzip_listing_without_folder_field(self):
        text = """
Path = packed.7z
Type = 7z
Physical Size = 130

Path = docs
Size = 0
Attributes = D drwxr-xr-x
Encrypted = -

Path = docs/n.txt
Size = 4
Attributes = A -rw-r--r--
Encrypted = -
"""
        tree = buildArchiveTree(parseSltRecords(text))
        self.assertTrue(tree.children["docs"].is_dir)
        note = tree.children["docs"].children["n.txt"]
        self.assertFalse(note.is_dir)
        self.assertEqual(note.size, 4)

    def test_progress_percent(self):
        self.assertEqual(parseProgressPercent(" 12% 3 - a.txt"), 12)
        self.assertEqual(parseProgressPercent("100%"), 100)
        self.assertIsNone(parseProgressPercent("Scanning the drive"))

    def test_compress_formats_exclude_rar(self):
        self.assertIn("zip", COMPRESS_FORMATS)
        self.assertIn("tar.gz", COMPRESS_FORMATS)
        self.assertNotIn("rar", COMPRESS_FORMATS)
        self.assertIn(".rar", ARCHIVE_EXTENSIONS)
        self.assertTrue(COMPRESS_FORMATS["7z"]["password"])
        self.assertFalse(COMPRESS_FORMATS["tar"]["password"])


# ------------------------------------------------------------
# Class: TestArchiveRoundTrip
# Purpose: List, extract, and compress with the real 7-Zip tool.
#          Skipped on machines that do not have it installed.
# ------------------------------------------------------------
@unittest.skipUnless(find7zExecutable(), "7-Zip is not installed")
class TestArchiveRoundTrip(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        clearListingCache()

    def tearDown(self):
        clearListingCache()
        clearArchiveCache()
        self._tmp.cleanup()

    def _sampleZip(self):
        path = os.path.join(self.root, "sample.zip")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("a.txt", "hello")
            archive.writestr("sub/b.txt", "nested")
        return path

    def test_list_and_extract_whole_archive(self):
        archive = self._sampleZip()
        tree, error = listArchive(archive)
        self.assertEqual(error, "")
        self.assertIn("a.txt", tree.children)
        self.assertTrue(tree.children["sub"].is_dir)

        dest = os.path.join(self.root, "out")
        messages = _run(ArchiveExtractWorker(archive, None, dest))
        self.assertTrue(messages[0][0], messages)
        self.assertEqual(open(os.path.join(dest, "a.txt"), encoding="utf-8").read(), "hello")
        self.assertEqual(
            open(os.path.join(dest, "sub", "b.txt"), encoding="utf-8").read(),
            "nested",
        )

    def test_extract_one_member_uses_its_name(self):
        archive = self._sampleZip()
        dest = os.path.join(self.root, "picked")
        messages = _run(ArchiveExtractWorker(archive, ["sub/b.txt"], dest))
        self.assertTrue(messages[0][0], messages)
        self.assertEqual(open(os.path.join(dest, "b.txt"), encoding="utf-8").read(), "nested")
        self.assertFalse(os.path.exists(os.path.join(dest, "a.txt")))

    def test_compress_zip_and_7z(self):
        folder = os.path.join(self.root, "src")
        os.makedirs(folder)
        with open(os.path.join(folder, "note.txt"), "w", encoding="utf-8") as handle:
            handle.write("note")

        zip_out = os.path.join(self.root, "packed.zip")
        messages = _run(
            ArchiveCompressWorker(
                [os.path.join(folder, "note.txt")],
                zip_out,
                "zip",
                "fast",
                base_dir=folder,
            )
        )
        self.assertTrue(messages[0][0], messages)
        with zipfile.ZipFile(zip_out) as archive:
            self.assertEqual(archive.read("note.txt"), b"note")

        seven_out = os.path.join(self.root, "packed.7z")
        messages = _run(
            ArchiveCompressWorker(
                [os.path.join(folder, "note.txt")],
                seven_out,
                "7z",
                "normal",
                base_dir=folder,
            )
        )
        self.assertTrue(messages[0][0], messages)
        clearListingCache()
        tree, error = listArchive(seven_out)
        self.assertEqual(error, "", error)
        self.assertIn("note.txt", tree.children)
        self.assertEqual(tree.children["note.txt"].size, 4)

    def test_compress_tar_gz(self):
        folder = os.path.join(self.root, "src")
        os.makedirs(folder)
        with open(os.path.join(folder, "note.txt"), "w", encoding="utf-8") as handle:
            handle.write("note")
        out = os.path.join(self.root, "packed.tar.gz")
        messages = _run(
            ArchiveCompressWorker(
                [os.path.join(folder, "note.txt")],
                out,
                "tar.gz",
                "fast",
                base_dir=folder,
            )
        )
        self.assertTrue(messages[0][0], messages)
        clearListingCache()
        tree, error = listArchive(out)
        self.assertEqual(error, "", error)
        self.assertIn("note.txt", tree.children)
        self.assertEqual(tree.children["note.txt"].size, 4)
