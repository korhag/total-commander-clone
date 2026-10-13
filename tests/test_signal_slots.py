"""
Signal/slot wiring: Qt passes signal arguments (for example the
``checked`` flag of ``QAction.triggered``) into a lambda's default
parameters, which silently replaced context-menu entries with ``False``.
"""

from __future__ import annotations

import ast
import glob
import os
import unittest

from PyQt5.QtWidgets import QAction, QApplication


_APP = QApplication.instance() or QApplication([])
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------
# Function: _findDefaultParamLambdaSlots
# Purpose: Return "file:line" for every ``.connect(lambda x=...)``
#          whose first parameter has a default, so a signal argument
#          would overwrite it. ``lambda checked, x=...`` is fine.
#          Scans the app sources (tests excluded).
# ------------------------------------------------------------
def _findDefaultParamLambdaSlots():
    offenders = []
    for path in glob.glob(os.path.join(_PROJECT_ROOT, "*.py")):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and node.args
                and isinstance(node.args[0], ast.Lambda)
            ):
                continue
            lambda_args = node.args[0].args
            if lambda_args.args and len(lambda_args.defaults) == len(lambda_args.args):
                offenders.append(f"{os.path.basename(path)}:{node.lineno}")
    return offenders


# ------------------------------------------------------------
# Class: TestSignalSlots
# Purpose: Guard against slots that receive signal arguments in
#          place of the values they captured.
# ------------------------------------------------------------
class TestSignalSlots(unittest.TestCase):
    def test_triggered_overrides_lambda_default(self):
        received = []
        action = QAction("x")
        action.triggered.connect(lambda entry={"full_path": "C:/x"}: received.append(entry))
        action.trigger()
        self.assertEqual(received, [False])

    def test_no_default_param_lambda_slots(self):
        self.assertEqual(_findDefaultParamLambdaSlots(), [])


if __name__ == "__main__":
    unittest.main()
