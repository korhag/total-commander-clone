"""
Drive list: Linux mount filtering, octal path decoding, and choosing
which dropdown entry contains the current folder.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from drive_list import (
    DriveEntry,
    DriveSpace,
    driveLabelForPath,
    findDriveForPath,
    isRemotePath,
    parseLinuxMounts,
    readDriveSpace,
)


HOME = "/home/korhag"

# Trimmed copy of a real /proc/self/mounts.
SAMPLE_MOUNTS = "\n".join([
    "/dev/mapper/root / btrfs rw 0 0",
    "proc /proc proc rw 0 0",
    "tmpfs /tmp tmpfs rw 0 0",
    "/dev/mapper/root /home btrfs rw 0 0",
    "/dev/mapper/root /var/log btrfs rw 0 0",
    "/dev/sda1 /boot vfat rw 0 0",
    "gvfsd-fuse /run/user/1000/gvfs fuse.gvfsd-fuse rw 0 0",
    "portal /run/user/1000/doc fuse.portal rw 0 0",
    "snapmaker-orca.AppImage /tmp/.mount_snapmaPfnhGc fuse.snapmaker-orca.AppImage rw 0 0",
    "cgroup2 /sys/fs/cgroup cgroup2 rw 0 0",
    "KromekaShared: /home/korhag/Kromeka-Shared fuse.rclone rw 0 0",
])


@unittest.skipUnless(os.name == "posix", "Linux mount paths")
class ParseLinuxMountsTests(unittest.TestCase):

    def test_keepsOnlyRealMountedFolders(self):
        entries = parseLinuxMounts(SAMPLE_MOUNTS, HOME)
        self.assertEqual(
            entries,
            [DriveEntry("Kromeka-Shared", "/home/korhag/Kromeka-Shared", True)],
        )

    def test_decodesSpacesInMountPath(self):
        text = "x /run/media/korhag/My\\040Stick vfat rw 0 0"
        entries = parseLinuxMounts(text, HOME)
        self.assertEqual(entries[0].label, "My Stick")
        self.assertEqual(entries[0].path, "/run/media/korhag/My Stick")

    def test_keepsRemovableMediaUnderRun(self):
        text = "/dev/sdb1 /run/media/korhag/USB vfat rw 0 0"
        self.assertEqual(len(parseLinuxMounts(text, HOME)), 1)

    def test_skipsHiddenAndHomeItself(self):
        text = "\n".join([
            "x /.snapshots btrfs rw 0 0",
            "x /home/korhag btrfs rw 0 0",
        ])
        self.assertEqual(parseLinuxMounts(text, HOME), [])

    def test_ignoresMalformedLines(self):
        self.assertEqual(parseLinuxMounts("bad line\n\n", HOME), [])


@unittest.skipUnless(os.name == "posix", "Linux mount paths")
class FindDriveForPathTests(unittest.TestCase):

    ENTRIES = [
        DriveEntry("/", "/", False),
        DriveEntry("~", HOME, False),
        DriveEntry("Kromeka-Shared", "/home/korhag/Kromeka-Shared", True),
    ]

    def test_prefersDeepestMatch(self):
        self.assertEqual(findDriveForPath(self.ENTRIES, "/home/korhag/Kromeka-Shared/Docs"), 2)
        self.assertEqual(findDriveForPath(self.ENTRIES, "/home/korhag/Downloads"), 1)
        self.assertEqual(findDriveForPath(self.ENTRIES, "/etc"), 0)

    def test_doesNotMatchSiblingWithSamePrefix(self):
        self.assertEqual(
            findDriveForPath(self.ENTRIES, "/home/korhag/Kromeka-Shared-old"), 1
        )

    def test_noMatchReturnsMinusOne(self):
        self.assertEqual(findDriveForPath([], "/etc"), -1)


@unittest.skipUnless(os.name == "posix", "Linux mount paths")
class DriveLabelForPathTests(unittest.TestCase):

    ENTRIES = [
        DriveEntry("/", "/", False),
        DriveEntry("~", HOME, False),
        DriveEntry("Kromeka-Shared", "/home/korhag/Kromeka-Shared", True),
    ]

    def test_mountWinsOverHomeAndRoot(self):
        self.assertEqual(
            driveLabelForPath(self.ENTRIES, "/home/korhag/Kromeka-Shared/Docs"),
            "Kromeka-Shared",
        )
        self.assertEqual(driveLabelForPath(self.ENTRIES, "/home/korhag/Downloads"), "~")
        self.assertEqual(driveLabelForPath(self.ENTRIES, "/etc"), "/")

    def test_unknownPathFallsBackToRoot(self):
        self.assertEqual(driveLabelForPath([], "/etc/passwd"), "/")
        self.assertEqual(driveLabelForPath([], ""), "")


class ReadDriveSpaceTests(unittest.TestCase):

    def test_tempDirHasConsistentTotals(self):
        space = readDriveSpace(tempfile.gettempdir())
        self.assertIsInstance(space, DriveSpace)
        self.assertGreaterEqual(space.total, space.free)
        self.assertGreaterEqual(space.used, 0)
        self.assertGreaterEqual(space.total, space.used)

    def test_missingPathReturnsNone(self):
        missing = os.path.join(tempfile.gettempdir(), "does-not-exist-drive-space-xyz")
        self.assertIsNone(readDriveSpace(missing))
        self.assertIsNone(readDriveSpace(""))


class IsRemotePathTests(unittest.TestCase):

    def test_rcloneMountIsRemoteAndLocalDiskIsNot(self):
        self.assertTrue(
            isRemotePath("/home/korhag/Kromeka-Shared/Docs", SAMPLE_MOUNTS)
        )
        self.assertFalse(isRemotePath("/home/korhag/Downloads", SAMPLE_MOUNTS))
        self.assertFalse(isRemotePath("/", SAMPLE_MOUNTS))

    def test_sshfsNfsAndCifsAreRemote(self):
        text = "\n".join([
            "/dev/sda1 / btrfs rw 0 0",
            "host:/share /mnt/server fuse.sshfs rw 0 0",
            "server:/export /mnt/nfs nfs4 rw 0 0",
            "//srv/share /mnt/smb cifs rw 0 0",
        ])
        self.assertTrue(isRemotePath("/mnt/server/a", text))
        self.assertTrue(isRemotePath("/mnt/nfs/a", text))
        self.assertTrue(isRemotePath("/mnt/smb/a", text))
        self.assertFalse(isRemotePath("/home/local", text))

    def test_emptyPathIsNotRemote(self):
        self.assertFalse(isRemotePath("", SAMPLE_MOUNTS))


if __name__ == "__main__":
    unittest.main()
