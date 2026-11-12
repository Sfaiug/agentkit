"""A host's room is the free space of each `virtiofs` mount the kernel's mount table lists,
whatever bytes its path holds and whatever else the table lists.

The kernel parts a row's fields with a space and escapes a space, tab, newline or backslash in a
path as a backslash and three octal digits; every other byte is the path's own, one no codec
reads included.  Offline: a mount table of the test's own (`host.PROC`) and statvfs answered per
path; nothing is mounted.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import host

MIB = 1 << 20


def statvfs(free_mb, blocks=1000):
    return os.statvfs_result((MIB, MIB, blocks, free_mb, free_mb, 0, 0, 0, 0, 255))


class MountTable(unittest.TestCase):
    def disk_use(self, table, shares):
        """`host.disk_use` of a 1000 MiB disk 400 used, beside this mount table and these shares'
        free MiB by the path statvfs is handed."""
        with tempfile.TemporaryDirectory() as proc:
            (Path(proc) / "self").mkdir()
            (Path(proc) / "self/mounts").write_bytes(table)
            with patch.object(host, "PROC", Path(proc)), \
                    patch.object(os, "statvfs", lambda path: statvfs(shares.get(path, 600))), \
                    patch.dict(os.environ, {"AK_HOST_READINGS": ""}):
                return host.disk_use("/home/acme")

    def test_a_share_s_path_is_its_own_bytes(self):
        unreadable = b"/dev/vdb /mnt/acme-\xff ext4 rw 0 0\n"
        # no-break, em and next-line spaces and a line separator: Unicode's, never the kernel's
        named = [(name.encode(), name) for name in (f"/mnt/acme{chr(gap)}shared"
                                                    for gap in (0xa0, 0x2003, 0x85, 0x2028))]
        for written, path in [(rb"/mnt/acme\040shared", "/mnt/acme shared"),
                              (rb"/mnt/acme\134shared", "/mnt/acme\\shared"),
                              (b"/mnt/acme-\xff", os.fsdecode(b"/mnt/acme-\xff")), *named]:
            with self.subTest(path=path):
                self.assertEqual(self.disk_use(
                    unreadable + b"share " + written + b" virtiofs rw,relatime 0 0\n",
                    {path: 100}), (400, 500))

    def test_no_share_leaves_the_disk_as_it_reads(self):
        self.assertEqual(self.disk_use(b"/dev/vda1 / ext4 rw 0 0\n", {}), (400, 1000))


if __name__ == "__main__":
    unittest.main()
