"""`ak run gc` removes a model report no seat's record names, and keeps one a seat's does.

A seat's harness reports its model in `~/.agentkit/state/model-<conversation>.json`, the name
sometimes carrying the call's moment after a dot.  Reports of a conversation no seat names, with
and without a moment, are what the dry run names, removing nothing; the collection then takes
them and leaves the named conversation's, whatever follows its dot.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, boxed with a /tmp and processes
of its own, and this test fails against `/bin/false`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, boxable, Home
from fixtures.garbage import ROOM

BOX = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--unshare-pid", "--proc", "/proc")
REPORT = {"model": "acme-model", "effort": "high"}


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class ModelReports(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.write(".agentkit/state/session-acme-gemini.json",
                   {"orchestrator": "gemini", "conversation": "conv-held"})
        self.free, self.held = ([home.write(f".agentkit/state/model-conv-{kind}{moment}.json",
                                            REPORT) for moment in ("", ".1794652800000000")]
                                for kind in ("free", "held"))

    def gc(self, *args):
        done = self.home.run(*self.home.box(BOX), AK, "run", "gc", *args, env=ROOM)
        self.assertEqual((done.code, done.err), (0, ""))
        return done.out.splitlines()

    def test_gc_removes_the_reports_no_seat_names_and_keeps_the_named_ones(self):
        planned = sorted(line for line in self.gc("--dry-run") if " model-report " in line)
        self.assertEqual(planned, sorted(f"gc: would remove model-report {path}: "
                                         "no seat names this conversation" for path in self.free))
        self.assertEqual([path for path in self.free + self.held if not path.exists()], [])
        self.gc()
        self.assertEqual([path for path in self.free + self.held if path.exists()], self.held)


if __name__ == "__main__":
    unittest.main()
