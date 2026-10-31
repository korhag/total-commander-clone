"""
The libraries sidebar filters the active library as you type.
"""

import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLineEdit

from libraries_panel import LibrariesPanel


_APP = QApplication.instance() or QApplication([])


def _folder(name, relative, values):
    return {
        "display_name": name,
        "library_id": "lib",
        "library_name": "Work",
        "root_id": "root",
        "root_name": "PARA",
        "relative_path": relative,
        "resolved_path": "/tmp/" + name,
        "is_available": True,
        "fields": [
            {"id": field_id, "name": label, "values": field_values}
            for field_id, label, field_values in (
                ("c", "Customer", values.get("c", [])),
                ("s", "Status", values.get("s", [])),
            )
            if field_values
        ],
        "field_map": values,
        "note": "",
    }


# ------------------------------------------------------------
# Class: TestLibrariesPanel
# Purpose: A typed value narrows the matching folders immediately.
# ------------------------------------------------------------
class TestLibrariesPanel(unittest.TestCase):

    def test_typing_filters_matching_folders(self):
        panel = LibrariesPanel()
        panel.resize(360, 720)
        panel.show()
        QTest.qWait(0)
        panel.setData(
            [{
                "id": "lib",
                "name": "Work",
                "roots": [{
                    "id": "root",
                    "name": "PARA",
                    "path": "/tmp/PARA",
                    "is_available": True,
                }],
            }],
            [
                _folder("Workshop", "02-Areas/Workshop", {"c": ["Acme Ltd"], "s": ["Open"]}),
                _folder("Other", "Other", {"c": ["Beta"], "s": ["Closed"]}),
            ],
            [{"id": "c", "name": "Customer"}, {"id": "s", "name": "Status"}],
            {},
            "lib",
        )
        QTest.qWait(0)
        self.assertEqual(panel._results_list.count(), 2)

        customer = panel.findChild(QLineEdit, "fieldFilterEdit:c")
        customer.setFocus()
        QTest.keyClicks(customer, "acm")
        QTest.qWait(0)
        self.assertEqual(panel._results_list.count(), 1)
        self.assertIn("Workshop", panel._results_list.item(0).text())
        self.assertIn("PARA / 02-Areas/Workshop", panel._results_list.item(0).text())

        status = panel.findChild(QLineEdit, "fieldFilterEdit:s")
        status.setFocus()
        QTest.keyClicks(status, "closed")
        QTest.qWait(0)
        self.assertEqual(panel._results_list.count(), 0)

        customer.setText("")
        customer.textEdited.emit("")
        QTest.qWait(0)
        self.assertEqual(panel._results_list.count(), 1)
        self.assertIn("Other", panel._results_list.item(0).text())

        panel.close()
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
