"""`ak standby` on a home opens each machine's record without waiting and reads only a regular
file: at a host's record path a named pipe, whether nobody writes to it or a process holds it open
for writing, a folder, or a link to a named pipe is a record that cannot be read, listed as such
beside the other host's copy and its age, and the command ends and exits 0.  A link to a whole
record is followed: it lists that record's copy as the record itself is listed.  Black-box,
through tests/fixtures/akbin.py, with the home's clocks from AK_NOW.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

RECORDS = ".agentkit/tmp/copies"      # the home's records of the machines that copy it
TOLD = "1789000000 50000 acme-boot-1"      # the home's clocks at a request
LATER = "1789000300 50300 acme-boot-1"     # five minutes on
FIVE_MINUTES = r"(?<![\w-])5m(?![\w-])"     # an age of five minutes, a word of its own


class AHomeOpensOnlyRegularRecords(unittest.TestCase):
    def setUp(self):
        """A home holding acme-vm's whole record, and the path acme-mac's is at."""
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env["AK_NOW"] = TOLD
        done = self.home.ak("standby", "--copied", "acme-vm", "0", "yes")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.damaged = self.home.path / RECORDS / "acme-mac"

    def listed(self):
        """acme-vm's line and acme-mac's of `ak standby` on the home five minutes on, which ends
        and exits 0, acme-vm's copy listed with its age."""
        self.home.env["AK_NOW"] = LATER
        said = self.home.ak("standby")
        self.assertEqual(said.code, 0, said.out + said.err)
        lines = said.out.splitlines()
        [vm] = [line for line in lines if "acme-vm" in line]
        [mac] = [line for line in lines if "acme-mac" in line]
        self.assertRegex(vm, FIVE_MINUTES)
        return vm, mac

    def assertUnreadable(self):
        self.assertIn("cannot be read", self.listed()[1])

    def test_a_named_pipe_nobody_writes_to_cannot_be_read(self):
        os.mkfifo(self.damaged)
        self.assertUnreadable()

    def test_a_named_pipe_held_open_for_writing_cannot_be_read(self):
        os.mkfifo(self.damaged)
        # for reading too, which opens a named pipe without waiting for its other end
        held = os.open(self.damaged, os.O_RDWR)
        self.addCleanup(os.close, held)
        self.assertUnreadable()

    def test_a_folder_cannot_be_read(self):
        self.damaged.mkdir()
        self.assertUnreadable()

    def test_a_link_to_a_named_pipe_cannot_be_read(self):
        pipe = self.home.path / "acme-pipe"
        os.mkfifo(pipe)
        self.damaged.symlink_to(pipe)
        self.assertUnreadable()

    def test_a_link_to_a_whole_record_lists_its_copy_as_the_record_itself(self):
        self.damaged.symlink_to("acme-vm")
        vm, mac = self.listed()
        self.assertEqual(mac.replace("acme-mac", "acme-vm"), vm)


if __name__ == "__main__":
    unittest.main()
