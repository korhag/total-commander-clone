"""
Choosing a terminal command without launching one.
"""

import unittest

from terminal_launcher import LINUX_FALLBACK_NAMES, buildTerminalCommand, openTerminalAt


FOLDER = "/home/user/work"


def _whichFrom(found):
    """which() that only resolves the names in `found`."""

    def which(name):
        return found.get(name)

    return which


# ------------------------------------------------------------
# Class: TestBuildTerminalCommand
# Purpose: Linux default-terminal order and the Windows fallback.
# ------------------------------------------------------------
class TestBuildTerminalCommand(unittest.TestCase):

    def test_terminal_env_xdg_terminal_exec_uses_dir_flag(self):
        argv = buildTerminalCommand(
            FOLDER,
            "Linux",
            {"TERMINAL": "xdg-terminal-exec"},
            _whichFrom({"xdg-terminal-exec": "/usr/bin/xdg-terminal-exec"}),
        )
        self.assertEqual(
            argv,
            ["/usr/bin/xdg-terminal-exec", f"--dir={FOLDER}"],
        )

    def test_terminal_env_kitty_uses_directory_flag(self):
        argv = buildTerminalCommand(
            FOLDER,
            "Linux",
            {"TERMINAL": "kitty"},
            _whichFrom({"kitty": "/usr/bin/kitty"}),
        )
        self.assertEqual(argv, ["/usr/bin/kitty", "--directory", FOLDER])

    def test_unknown_terminal_env_is_launched_bare(self):
        argv = buildTerminalCommand(
            FOLDER,
            "Linux",
            {"TERMINAL": "myterm"},
            _whichFrom({"myterm": "/usr/local/bin/myterm"}),
        )
        self.assertEqual(argv, ["/usr/local/bin/myterm"])

    def test_missing_terminal_env_falls_through(self):
        argv = buildTerminalCommand(
            FOLDER,
            "Linux",
            {"TERMINAL": "missing-term"},
            _whichFrom({"foot": "/usr/bin/foot"}),
        )
        self.assertEqual(argv, ["/usr/bin/foot", f"--working-directory={FOLDER}"])

    def test_fallback_order_skips_missing_terminals(self):
        seen = []

        def which(name):
            seen.append(name)
            if name == "konsole":
                return "/usr/bin/konsole"
            return None

        argv = buildTerminalCommand(FOLDER, "Linux", {}, which)
        self.assertEqual(argv, ["/usr/bin/konsole", "--workdir", FOLDER])
        self.assertEqual(seen, list(LINUX_FALLBACK_NAMES[: seen.index("konsole") + 1]))
        self.assertLess(seen.index("xdg-terminal-exec"), seen.index("alacritty"))
        self.assertLess(seen.index("alacritty"), seen.index("konsole"))

    def test_no_terminal_raises(self):
        with self.assertRaises(OSError):
            buildTerminalCommand(FOLDER, "Linux", {}, lambda name: None)

    def test_windows_prefers_windows_terminal(self):
        argv = buildTerminalCommand(
            r"C:\Users\me",
            "Windows",
            {},
            _whichFrom({"wt": r"C:\Program Files\WindowsApps\wt.exe"}),
        )
        self.assertEqual(
            argv,
            [r"C:\Program Files\WindowsApps\wt.exe", "-d", "."],
        )

    def test_windows_without_wt_uses_cmd(self):
        argv = buildTerminalCommand(
            r"C:\Users\me",
            "Windows",
            {},
            lambda name: None,
        )
        self.assertEqual(argv, ["cmd.exe"])

    def test_macos_opens_terminal_app(self):
        argv = buildTerminalCommand(FOLDER, "Darwin", {}, lambda name: None)
        self.assertEqual(argv, ["open", "-a", "Terminal", FOLDER])


# ------------------------------------------------------------
# Class: TestOpenTerminalAt
# Purpose: The launch is detached and starts in the folder.
#          A stand-in for Popen keeps the test from opening
#          a real terminal.
# ------------------------------------------------------------
class TestOpenTerminalAt(unittest.TestCase):

    def test_linux_starts_in_folder_and_detaches(self):
        captured = {}

        def popen(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

        openTerminalAt(
            FOLDER,
            popen=popen,
            system="Linux",
            env={"TERMINAL": "alacritty"},
            which=_whichFrom({"alacritty": "/usr/bin/alacritty"}),
        )
        self.assertEqual(
            captured["argv"],
            ["/usr/bin/alacritty", "--working-directory", FOLDER],
        )
        self.assertEqual(captured["kwargs"]["cwd"], FOLDER)
        self.assertTrue(captured["kwargs"]["start_new_session"])
        self.assertNotIn("creationflags", captured["kwargs"])

    def test_windows_opens_a_new_console_in_folder(self):
        captured = {}

        def popen(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

        openTerminalAt(
            r"C:\Work",
            popen=popen,
            system="Windows",
            env={},
            which=lambda name: None,
        )
        self.assertEqual(captured["argv"], ["cmd.exe"])
        self.assertEqual(captured["kwargs"]["cwd"], r"C:\Work")
        self.assertIn("creationflags", captured["kwargs"])
        self.assertNotIn("start_new_session", captured["kwargs"])


if __name__ == "__main__":
    unittest.main()
