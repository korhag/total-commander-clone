"""
Libraries, fields, folder values, and moving a library file.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from library_manager import (
    LibraryManager,
    buildFolderKey,
    foldText,
    normalizePath,
    storeRelativePath,
)


# ------------------------------------------------------------
# Class: _MemorySettings
# Purpose: In-memory stand-in for the settings store.
# ------------------------------------------------------------
class _MemorySettings:

    def __init__(self):
        self.state = {
            "libraries": [],
            "folder_tags": {},
            "saved_library_filters": [],
        }

    def getLibraries(self):
        return self.state["libraries"]

    def setLibraries(self, libraries):
        self.state["libraries"] = libraries or []

    def getFolderTags(self):
        return self.state["folder_tags"]

    def setFolderTags(self, folder_tags):
        self.state["folder_tags"] = folder_tags or {}

    def getSavedLibraryFilters(self):
        return self.state["saved_library_filters"]

    def saveState(self):
        self.state["saves"] = self.state.get("saves", 0) + 1


# ------------------------------------------------------------
# Class: TestLibraryManager
# Purpose: Fields, Turkish matching, filters, and library files.
# ------------------------------------------------------------
class TestLibraryManager(unittest.TestCase):

    def test_fold_text_matches_turkish_spellings(self):
        self.assertEqual(foldText("IŞIK"), foldText("ışık"))
        self.assertEqual(foldText("Işık"), foldText("ışık"))
        self.assertEqual(foldText("İstanbul"), foldText("istanbul"))
        self.assertNotEqual(foldText("ışık"), foldText("isik"))
        self.assertEqual(storeRelativePath("02-Areas\\Workshop"), "02-Areas/Workshop")

    def test_legacy_tags_become_fields(self):
        settings = _MemorySettings()
        settings.state["libraries"] = [{
            "id": "lib-1",
            "name": "Personal",
            "roots": [{
                "id": "root-1",
                "name": "PARA",
                "path": "/missing",
                "is_available": False,
            }],
        }]
        settings.state["folder_tags"] = {
            "old": {
                "library_id": "lib-1",
                "root_id": "root-1",
                "relative_path": "02-Areas\\Workshop",
                "tags": ["customer:Acme", "plain", "Müşteri:Işık"],
                "note": "keep me",
            }
        }

        manager = LibraryManager(settings)
        names = {foldText(field["name"]): field for field in manager.getFields("lib-1")}
        self.assertEqual(set(names), {foldText("customer"), foldText("Tag"), foldText("Müşteri")})

        key = buildFolderKey("lib-1", "root-1", "02-Areas/Workshop")
        record = manager.getFolderTags()[key]
        self.assertNotIn("tags", record)
        self.assertEqual(record["relative_path"], "02-Areas/Workshop")
        self.assertEqual(record["note"], "keep me")
        self.assertEqual(record["fields"][names[foldText("customer")]["id"]], ["Acme"])
        self.assertEqual(record["fields"][names[foldText("Tag")]["id"]], ["plain"])
        self.assertEqual(record["fields"][names[foldText("Müşteri")]["id"]], ["Işık"])

        LibraryManager(settings)
        self.assertEqual(len(manager.getFields("lib-1")), 3)

    def test_field_values_keep_spaces_commas_and_reject_a_duplicate_name(self):
        manager = LibraryManager(_MemorySettings())
        library = manager.createLibrary("Work")
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "PARA")
            folder = os.path.join(root, "Workshop")
            os.makedirs(folder)
            manager.addRoot(library["id"], root, "PARA")
            customer = manager.createField(library["id"], "Customer")
            status = manager.createField(library["id"], "Status")
            again = manager.createField(library["id"], "customer")
            self.assertEqual(again["id"], customer["id"])

            saved = manager.setFolderFields(folder, library["id"], {
                customer["id"]: ["Ahmet Yılmaz", "Acme, Inc", "  ahmet yılmaz  "],
                status["id"]: ["Open"],
            })
            self.assertEqual(
                saved["fields"][customer["id"]],
                ["Ahmet Yılmaz", "Acme, Inc"],
            )
            self.assertEqual(saved["relative_path"], "Workshop")

            renamed = manager.renameField(library["id"], status["id"], "CUSTOMER")
            self.assertIsNone(renamed)
            self.assertEqual(
                [field["name"] for field in manager.getFields(library["id"])],
                ["Customer", "Status"],
            )
            self.assertIsNotNone(manager.renameField(library["id"], status["id"], "Durum"))
            self.assertTrue(manager.deleteField(library["id"], customer["id"]))
            record = manager.getFolderRecordForPath(folder, library["id"])
            self.assertNotIn(customer["id"], record["fields"])
            self.assertEqual(list(record["fields"].values()), [["Open"]])

    def test_filters_are_any_inside_a_field_and_all_across_fields(self):
        manager = LibraryManager(_MemorySettings())
        library = manager.createLibrary("Work")
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "PARA")
            workshop = os.path.join(root, "Workshop")
            other = os.path.join(root, "Other")
            os.makedirs(workshop)
            os.makedirs(other)
            manager.addRoot(library["id"], root, "PARA")
            customer = manager.createField(library["id"], "Customer")
            status = manager.createField(library["id"], "Status")
            manager.setFolderFields(workshop, library["id"], {
                customer["id"]: ["Acme Ltd"],
                status["id"]: ["Open"],
            })
            manager.setFolderFields(other, library["id"], {
                customer["id"]: ["Beta"],
                status["id"]: ["Closed"],
            })

            acme = manager.findFolders(library["id"], {customer["id"]: ["acm"]})
            self.assertEqual([item["display_name"] for item in acme], ["Workshop"])

            either = manager.findFolders(library["id"], {customer["id"]: ["zzz", "beta"]})
            self.assertEqual([item["display_name"] for item in either], ["Other"])

            both = manager.findFolders(library["id"], {
                customer["id"]: ["acm"],
                status["id"]: ["open"],
            })
            self.assertEqual([item["display_name"] for item in both], ["Workshop"])

            neither = manager.findFolders(library["id"], {
                customer["id"]: ["acm"],
                status["id"]: ["closed"],
            })
            self.assertEqual(neither, [])

            istanbul = manager.createField(library["id"], "Şehir")
            manager.setFolderFields(workshop, library["id"], {
                customer["id"]: ["Acme Ltd"],
                status["id"]: ["Open"],
                istanbul["id"]: ["İstanbul"],
            })
            matched = manager.findFolders(library["id"], {istanbul["id"]: ["ist"]})
            self.assertEqual([item["display_name"] for item in matched], ["Workshop"])

    def test_active_library_wins_when_roots_overlap(self):
        manager = LibraryManager(_MemorySettings())
        first = manager.createLibrary("First")
        second = manager.createLibrary("Second")
        with tempfile.TemporaryDirectory() as base:
            manager.addRoot(first["id"], base, "One")
            manager.addRoot(second["id"], base, "Two")
            context = manager.resolveFolderContext(base, second["id"])
            self.assertEqual(context["library"]["id"], second["id"])
            self.assertIsNone(manager.resolveFolderContext(base, "missing"))

    def test_export_import_finds_the_root_by_its_marker(self):
        settings = _MemorySettings()
        manager = LibraryManager(settings)
        library = manager.createLibrary("Work")
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            root = os.path.join(left, "PARA")
            folder = os.path.join(root, "02-Areas", "Workshop")
            os.makedirs(folder)
            added = manager.addRoot(library["id"], root, "PARA")
            field = manager.createField(library["id"], "Müşteri")
            manager.setFolderFields(folder, library["id"], {
                field["id"]: ["Ahmet Yılmaz", "Acme, Inc"],
            })
            export_path = os.path.join(left, "work.tcclib.json")
            self.assertTrue(manager.exportLibrary(library["id"], export_path))
            with open(export_path, encoding="utf-8") as handle:
                raw = handle.read()
            self.assertIn("Ahmet Yılmaz", raw)
            self.assertIn("Müşteri", raw)

            shutil.move(root, os.path.join(right, "PARA"))
            other = LibraryManager(_MemorySettings())
            with patch.object(other, "_candidateScanBases", return_value=[right]):
                blocked = other.importLibrary(export_path, replace=False)
                self.assertFalse(blocked["conflict"])
                again = other.importLibrary(export_path, replace=False)
            self.assertTrue(again["conflict"])
            self.assertEqual(len(other.getLibraries()), 1)

            restored_root = blocked["library"]["roots"][0]
            moved = os.path.join(right, "PARA")
            self.assertTrue(restored_root["is_available"])
            self.assertEqual(normalizePath(restored_root["path"]), normalizePath(moved))
            record = other.getFolderRecordForPath(
                os.path.join(moved, "02-Areas", "Workshop"),
                blocked["library"]["id"],
            )
            self.assertEqual(record["relative_path"], "02-Areas/Workshop")
            self.assertEqual(
                list(record["fields"].values()),
                [["Ahmet Yılmaz", "Acme, Inc"]],
            )
            self.assertEqual(added["root"]["id"], restored_root["id"])

    def test_locate_root_points_at_the_new_folder(self):
        manager = LibraryManager(_MemorySettings())
        library = manager.createLibrary("Work")
        with tempfile.TemporaryDirectory() as base:
            first = os.path.join(base, "first")
            second = os.path.join(base, "second")
            os.makedirs(os.path.join(first, "Workshop"))
            os.makedirs(second)
            added = manager.addRoot(library["id"], first, "PARA")
            field = manager.createField(library["id"], "Status")
            manager.setFolderFields(os.path.join(first, "Workshop"), library["id"], {
                field["id"]: ["Open"],
            })
            located = manager.locateRoot(library["id"], added["root"]["id"], second)
            self.assertEqual(normalizePath(located["path"]), normalizePath(second))
            self.assertFalse(os.path.isfile(os.path.join(first, ".tcc_library_root.json")))
            self.assertTrue(os.path.isfile(os.path.join(second, ".tcc_library_root.json")))

    def test_scan_bases_include_the_home_folder(self):
        manager = LibraryManager(_MemorySettings())
        self.assertIn(os.path.expanduser("~"), manager._candidateScanBases())


if __name__ == "__main__":
    unittest.main()
