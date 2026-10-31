"""
The update check reads this fork, and a missing shell script
does not start a process.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from app_updater import (
    PUBLIC_REPO_NAME,
    PUBLIC_REPO_OWNER,
    fetchPublicAppVersionViaHttps,
    launchUpdateAndRebuild,
)


# ------------------------------------------------------------
# Class: TestAppUpdater
# Purpose: The version URL is the fork, and Linux does not
#          quit into a script that is not there.
# ------------------------------------------------------------
class TestAppUpdater(unittest.TestCase):

    def test_version_url_is_the_fork(self):
        seen = []

        def fake_urlopen(request, timeout=0):
            seen.append(request.full_url)
            raise OSError("offline")

        with mock.patch("app_updater.urllib.request.urlopen", fake_urlopen):
            fetchPublicAppVersionViaHttps("main")
        self.assertEqual(PUBLIC_REPO_OWNER, "korhag")
        self.assertEqual(PUBLIC_REPO_NAME, "total-commander-clone")
        self.assertIn(
            "https://raw.githubusercontent.com/korhag/"
            "total-commander-clone/main/app_version.py",
            seen,
        )

    def test_missing_shell_script_does_not_start_a_process(self):
        if os.name == "nt":
            self.skipTest("Windows starts the batch file")
        with tempfile.TemporaryDirectory() as root:
            scripts = os.path.join(root, "scripts")
            os.makedirs(scripts)
            with open(os.path.join(scripts, "update-and-rebuild.bat"), "w", encoding="utf-8"):
                pass
            with mock.patch("app_updater.subprocess.Popen") as popen:
                ok, message = launchUpdateAndRebuild(root)
            popen.assert_not_called()
            self.assertFalse(ok)
            self.assertIn("git pull", message.lower())
