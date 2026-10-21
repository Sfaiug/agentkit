"""Ctrl-C during a command that is waiting ends it with exit 130, one word, and nothing left behind.

A person or a harness interrupts `ak fetch` while it waits on the Mac for a file.  The shell and
any script around it read the interrupt from the exit status, 130 as for any program a SIGINT
ended; the person reads one line saying the command was interrupted, never a traceback; and the
request the command had queued for the Mac is taken back, so the Mac does not send a file
nobody waits for.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, signalled as a terminal's Ctrl-C signals its foreground process group,
and this test fails against `/bin/false`.
"""

import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

MAC_FILE = "/Users/acme/report.pdf"   # a path on the Mac, which this host does not have


class SigintExits130(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.bridge = self.home.path / ".agentkit" / "macbridge"

    def queued(self, proc, bound=30):
        """The requests the command queued for the Mac, once there is one; a dot file is one
        still being written."""
        requests = self.bridge / "requests"
        deadline = time.monotonic() + bound
        while True:
            queued = [path for path in requests.glob("*") if not path.name.startswith(".")]
            if queued:
                return queued
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"ak fetch queued no request (exit {proc.poll()})")
            time.sleep(0.05)

    def interrupt(self, *args):
        """Start `ak fetch`, Ctrl-C it once it waits on the Mac, and return its exit and its
        output."""
        # Long enough that the wait is still on when the interrupt comes.
        proc = self.home.spawn("fetch", *args, env={"AK_FETCH_TIMEOUT": "600"})
        self.assertEqual(len(self.queued(proc)), 1)
        os.killpg(proc.pid, signal.SIGINT)
        code = proc.wait(timeout=30)
        # the Home's first spawn, as each case has a Home of its own
        return (code, self.home.log("spawn-1.out").read_text(),
                self.home.log("spawn-1.err").read_text())

    def test_an_interrupted_wait_exits_130_saying_only_that(self):
        code, out, err = self.interrupt(MAC_FILE)
        self.assertEqual(code, 130, err)
        self.assertEqual(out, "")
        self.assertEqual(err, "\nak fetch: interrupted\n")

    def test_the_request_the_mac_was_asked_for_is_taken_back(self):
        code, _out, err = self.interrupt(MAC_FILE)
        self.assertEqual(code, 130, err)
        self.assertEqual(list((self.bridge / "requests").iterdir()), [])
        self.assertEqual(list((self.bridge / "inbox").iterdir()), [])

    def test_a_file_already_printed_stays_printed(self):
        here = self.home.write("notes.txt", "kept\n")
        code, out, err = self.interrupt(str(here), MAC_FILE)
        self.assertEqual(code, 130, err)
        self.assertEqual(out, f"{here}\n")
        self.assertEqual(err, "\nak fetch: interrupted\n")


if __name__ == "__main__":
    unittest.main()
