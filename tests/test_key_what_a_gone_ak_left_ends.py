"""What an `ak` command's harness call left running in that `ak`'s session, the next tick ends;
what the call left in a session of its own runs on.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each in
a session of its own, its harness the fake of tests/fixtures/fakeadapter.py, whose first `usage`
here leaves a `sleep 600` in the call's session, the `ak`'s, and one in a session of its own, each
writing its pid down.  The whole file runs in one box (`rerun_boxed`): the tick must see them.
"""

from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import BOXED, Home, rerun_boxed

# Before the fake's answer: neither `sleep` holds the call's output open.
LEAVE = """if [ "$1" = usage ] && [ ! -e {root}/left ]; then
  sleep='echo $$ >"$0.tmp" && mv "$0.tmp" "$0" && exec sleep 600'
  sh -c "$sleep" {root}/left </dev/null >/dev/null 2>&1 &
  setsid sh -c "$sleep" {root}/service </dev/null >/dev/null 2>&1 &
fi"""


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class GoneAkLeftovers(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fake = fakeadapter.install(self.home, claude="pass")["claude"]
        akconfig.write(self.home, {"fable": "claude"})
        first, rest = fake.script.read_text().split("\n", 1)
        fake.script.write_text("\n".join(
            [first, LEAVE.format(root=shlex.quote(str(self.home.root))), rest]))

    def running(self, name):
        """Whether the `sleep 600` whose pid is in `name` runs: an exited one's reads empty."""
        try:
            pid = (self.home.root / name).read_text().strip()
            return Path(f"/proc/{pid}/cmdline").read_bytes() == b"sleep\x00600\x00"
        except OSError:
            return False

    def until(self, done, what):
        deadline = time.monotonic() + 30
        while not done():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_the_next_tick_ends_what_a_gone_ak_left_in_its_session(self):
        done = self.home.ak("usage")
        self.assertEqual(done.code, 0, done.err)
        self.until(lambda: self.running("left") and self.running("service"), "the call left none")
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.err)
        self.until(lambda: not self.running("left"), "the tick left the leftover running")
        self.assertTrue(self.running("service"), "the tick ended a service")


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
