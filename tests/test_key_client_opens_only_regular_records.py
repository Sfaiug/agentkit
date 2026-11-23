"""`ak standby` reads the record of a server and the stamp of a client's last pass only as regular
files, opened without waiting: a named pipe nobody writes to at either reads as that record not
there, and the command ends saying what it says then.  Black-box, through tests/fixtures/akbin.py.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

SERVER = ".agentkit/state/server"     # the record of a server, naming the home
STAMP = ".agentkit/tmp/standby/copied"      # the stamp of the last pass that ended well


def standby(server, piped=None):
    """The exit and output of `ak standby` on a machine whose record of a server reads `server`,
    or that has none, with a named pipe at `piped` where one is named."""
    with Home() as home:
        if server:
            home.write(SERVER, server)
        if piped:
            path = home.write(piped, "")
            path.unlink()
            os.mkfifo(path)
        said = home.ak("standby")
    return said.code, said.out


class AClientOpensOnlyRegularRecords(unittest.TestCase):
    def test_a_named_pipe_at_the_record_of_a_server_reads_as_none(self):
        self.assertEqual(standby(None, SERVER), standby(None))

    def test_a_named_pipe_at_the_stamp_reads_as_none(self):
        self.assertEqual(standby("acme-vm\n", STAMP), standby("acme-vm\n"))


if __name__ == "__main__":
    unittest.main()
