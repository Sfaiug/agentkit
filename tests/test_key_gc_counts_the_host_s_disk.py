"""On a guest's disk, gc's pressure starts where it would on a disk holding only its host's room.

A Mac's Linux machine keeps its disk in an image on the Mac's own disk, growing as it fills: it
has as much room left as the least of its own free space and that of each folder the host shares
through `virtiofs`, and the blocks it reserves for root are none of that room.  A disk half full
whose host folder has almost no room is full, and so is one nearly empty that reserves blocks:
`ak run gc` takes a throwaway run two days old, as it does only under pressure.  The same
half-full disk beside a host folder with more room than its own, or beside none, keeps it.  The
readings come from outside (`AK_HOST_READINGS`), never from a filled disk.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and this test fails
against `/bin/false`.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.garbage import run

HALF = {"disk_total_mb": 100_000, "disk_used_mb": 50_000, "disk_free_mb": 50_000}


@unittest.skipUnless(boxable(), "no bwrap able to give the collection a /tmp of its own")
class HostsRoom(unittest.TestCase):
    def kept(self, **readings):
        """Whether `ak run gc` on a half-full disk, with these readings in place of its own,
        keeps the run."""
        with Home() as home:
            throwaway = run(home, "acme-throwaway", 2, state="pass",
                            repo=str(home.path / ".agentkit" / "tmp" / "acme-suite"))
            done = home.ak("run", "gc", boxed=True,
                           env={"AK_HOST_READINGS": json.dumps({**HALF, **readings})})
            self.assertEqual((done.code, done.err), (0, ""))
            return throwaway.exists()

    def test_a_host_folder_with_almost_no_room_fills_the_disk(self):
        self.assertFalse(self.kept(virtiofs_free_mb=[100]))

    def test_a_disk_s_reserved_blocks_are_no_room_beside_a_full_host(self):
        self.assertFalse(self.kept(disk_used_mb=10_000, disk_free_mb=85_000,
                                   virtiofs_free_mb=[100]))

    def test_a_host_folder_roomier_than_the_disk_leaves_it_half_full(self):
        self.assertTrue(self.kept(virtiofs_free_mb=[200_000]))

    def test_no_host_folder_leaves_it_half_full(self):
        self.assertTrue(self.kept())


if __name__ == "__main__":
    unittest.main()
