"""A config write does not wait for a collection pass, of which there is still one at a time.

A pass ends each old conversation with its harness's own command, for minutes on a home with
many.  It once held the lock every config write takes, ~/.agentkit's, so the models screen
stood still at the first mark made during a pass.  Here a pass is held ending an OpenCode
session (tests/test_key_gc_ends_idle_opencode_sessions.py) by a fake `opencode` that waits for
the test: the first command's rename of an old key, a config write
(tests/test_key_policy_names.py), ends meanwhile, and a second pass takes nothing.  A pass of
a version before this one holds ~/.agentkit throughout, so while the test holds it a pass takes
nothing either; and a home with no state folder is collected all the same.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each collection in a
box with a /tmp of its own, and this test fails against `/bin/false`.
"""

import fcntl
import os
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, boxable, Home
from fixtures.garbage import ROOM
from test_key_gc_ends_idle_opencode_sessions import OLD, database

NONE = "gc: no eligible artifacts\n"
TAKEN = f"gc: remove conversation {OLD}: untouched for 30 days\n"
# ends a session once the test removes the file it makes: the pass that asked waits meanwhile
WAITS = LOG + ": >{ending}\nwhile [ -e {ending} ]; do sleep 0.1; done\n"


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class GcLeavesTheConfigFree(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.refuse("opencode", LOG)
        database(home.path / ".local/share/opencode/opencode.db", (OLD, None, 31))

    def gc(self):
        return self.home.ak("run", "gc", boxed=True, env=ROOM)

    def test_a_config_write_and_a_second_pass_end_while_a_pass_ends_a_conversation(self):
        home, ending = self.home, self.home.root / "ending"
        home.refuse("opencode", WAITS, ending=shlex.quote(str(ending)))
        held = home.spawn("run", "gc", boxed=True, env=ROOM)
        deadline = time.monotonic() + 120
        while not ending.exists():
            if held.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("the pass asked OpenCode to end no session")
            time.sleep(0.05)
        self.assertEqual(self.gc(), (0, NONE, ""))
        config = home.path / ".agentkit" / "config.toml"
        shipped = config.read_text()
        config.write_text("rounds = 2\n" + shipped)
        self.assertEqual(home.ak("run", "--help").code, 0)
        self.assertEqual(config.read_text(), "review_rounds = 2\n" + shipped)
        ending.unlink()
        # A pass stops a harness that takes a minute and says it kept the session: one it says
        # it ended was still ending it when the test let go, after the second pass and the write.
        self.assertEqual((held.wait(timeout=120), home.log("spawn-1.out").read_text()),
                         (0, TAKEN))
        self.assertEqual(home.calls("opencode"), [["session", "delete", "--standalone", OLD]])

    def test_a_pass_takes_nothing_while_one_of_the_version_before_holds_home(self):
        held = os.open(self.home.path / ".agentkit", os.O_RDONLY)
        try:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertEqual(self.gc(), (0, NONE, ""))
        finally:
            os.close(held)
        self.assertEqual(self.gc(), (0, TAKEN, ""))

    def test_a_home_with_no_state_folder_is_collected(self):
        (self.home.path / ".agentkit" / "state").rmdir()
        self.assertEqual(self.gc(), (0, TAKEN, ""))


if __name__ == "__main__":
    unittest.main()
