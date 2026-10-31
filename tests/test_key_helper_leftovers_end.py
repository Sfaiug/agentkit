"""What a helper ak starts by itself leaves running in its session, the next tick ends once that
helper is gone.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each in
a session of its own, beside a user manager the Home fakes: its control socket listens, and its
`systemctl`, the Home's refusing fake, first leaves a `sleep 600` in the session of each caller,
writing its pid down under that session: a tick, and a helper the tick starts in a session of its
own, such as its background cleanup asking which units failed.  The whole file runs in one box
(`rerun_boxed`): the tick must see them.
"""

import os
from pathlib import Path
import shlex
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import BOXED, Home, rerun_boxed

# Before systemctl's refusal: the `sleep` holds none of the caller's output open.
LEAVE = """read -r _ _ _ _ _ session _ </proc/$$/stat
if mkdir {root}/left-"$session" 2>/dev/null; then
  sleep='echo $$ >"$0.tmp" && mv "$0.tmp" "$0" && exec sleep 600'
  sh -c "$sleep" {root}/left-"$session"/pid </dev/null >/dev/null 2>&1 &
fi"""


def session(pid):
    """That process's session, or None once it is gone."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[3])
    except (OSError, ValueError, IndexError):
        return None


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class GoneHelperLeftovers(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        manager = socket.socket(socket.AF_UNIX)
        self.addCleanup(manager.close)
        (self.home.root / "run" / "systemd").mkdir()
        manager.bind(str(self.home.root / "run" / "systemd" / "private"))  # XDG_RUNTIME_DIR's
        manager.listen(64)
        systemctl = self.home.bin / "systemctl"
        first, rest = systemctl.read_text().split("\n", 1)
        systemctl.write_text("\n".join([first, LEAVE.format(
            root=shlex.quote(str(self.home.root))), rest]))

    def left(self):
        """{session: the pid of the `sleep 600` systemctl left in it, while it runs}."""
        found = {}
        for path in self.home.root.glob("left-*/pid"):
            pid = path.read_text().strip()
            try:
                if Path(f"/proc/{pid}/cmdline").read_bytes() == b"sleep\x00600\x00":
                    found[int(path.parent.name.removeprefix("left-"))] = int(pid)
            except OSError:
                pass
        return found

    def alone(self, held, pid):
        """Whether the `sleep` at `pid` is all its session `held` still runs: its helper is gone."""
        return [other for other in map(int, filter(str.isdigit, os.listdir("/proc")))
                if session(other) == held] == [pid]

    def until(self, done, what):
        deadline = time.monotonic() + 60
        while not (found := done()):
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)
        return found

    def test_the_next_tick_ends_what_a_gone_helper_left_in_its_session(self):
        tick = self.home.spawn("watch")
        self.assertEqual(tick.wait(300), 0)
        helpers = self.until(lambda: {held: pid for held, pid in self.left().items()
                                      if held != tick.pid and self.alone(held, pid)},
                             "no helper the tick started left anything and ended")
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.err)
        self.until(lambda: not set(helpers.items()) & set(self.left().items()),
                   "the tick left a gone helper's leftover running")


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
