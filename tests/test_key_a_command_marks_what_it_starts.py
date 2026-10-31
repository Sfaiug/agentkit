"""What an `ak` command runs carries a mark naming that `ak`; a seat it opens carries none.

The mark is AK_OWNER, `<pid namespace> <pid> <start> <session> <command>`: the `ak` process by
its pid namespace's inode, its pid, its start in clock ticks since boot and its POSIX session,
then the command it ran.  Everything the command starts inherits it, so what an `ak` leaves
running can be told apart once that `ak` is gone; what ak starts to outlive the command -- a
tmux server, a seat's harness -- is started without it.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, each in a session of its own, its harness the
fake of tests/fixtures/fakeadapter.py, which records the AK_* part of each call's environment
and opens a seat as `sleep 600`, and tmux and the seat's processes are read as the test.
"""

import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home


def started():
    """This process's start in clock ticks since boot, and the clock now, in the same ticks."""
    start = int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])
    return start, float(Path("/proc/uptime").read_text().split()[0]) * os.sysconf("SC_CLK_TCK")


def below(pid):
    """Every process below that one."""
    kids = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
    return [*kids, *(grandchild for kid in kids for grandchild in below(kid))]


class AkMarksWhatItStarts(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fake = fakeadapter.install(self.home, claude="pass")["claude"]
        akconfig.write(self.home, {"fable": "claude"})

    def mark(self, verb):
        return self.fake.calls(verb)[-1]["env"].get("AK_OWNER")

    def test_what_a_command_runs_carries_a_mark_naming_that_ak(self):
        done = self.home.ak("usage")
        self.assertEqual(done.code, 0, done.err)
        namespace, pid, start, session, command = self.mark("usage").split(" ")
        self.assertEqual(int(namespace), os.stat("/proc/self/ns/pid").st_ino)
        self.assertEqual(session, pid)      # the Home starts each ak as its session's leader
        mine, now = started()
        self.assertTrue(mine <= int(start) <= now, (mine, start, now))
        self.assertNotEqual(int(pid), os.getpid())
        self.assertEqual(command, "usage")

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_seat_and_its_tmux_server_carry_no_mark(self):
        done = self.home.ak("orch", "acme", "--model", "fable", "--workers", "fable", tty=True)
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(self.mark("interactive"))      # what `ak orch` asked in passing is its
        server = self.home.tmux("show-environment", "-g")
        self.assertEqual(server.code, 0, server.err)
        self.assertNotIn("AK_OWNER=", server.out)
        pane = self.home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_pid}").out.strip()
        deadline = time.monotonic() + 30
        while not (harness := [pid for pid in below(pane) if Path(f"/proc/{pid}/cmdline")
                               .read_bytes() == b"sleep\x00600\x00"]):
            self.assertLess(time.monotonic(), deadline, "the seat's harness never started")
            time.sleep(0.1)
        environ = Path(f"/proc/{harness[0]}/environ").read_bytes().split(b"\0")
        self.assertEqual([part for part in environ if part.startswith(b"AK_OWNER=")], [])


if __name__ == "__main__":
    unittest.main()
