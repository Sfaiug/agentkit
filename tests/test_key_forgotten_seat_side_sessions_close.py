"""A side session of a seat ak holds no record of closes at the next tick, its panes running.

A seat's sessions for a dev server, a build or a long test carry its name, and once ak has
forgotten that seat nothing else would ever end them: the tick saves each pane's screen to
~/.agentkit/tmp and closes the session, live panes and all.  One whose seat still has a session
in tmux stays.  Black-box: the sessions start through a seat's own tmux shim
(tests/fixtures/shims.py) on the Home's real tmux, and the tick runs boxed, as cron runs it;
judged by what tmux holds and the files the tick wrote.  This test fails against `/bin/false`.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home, boxable
from fixtures.shims import Shims


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ForgottenSeatSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        shims = Shims(home)
        done = home.tmux("new-session", "-d", "-s", "beta", "sleep 3600")
        assert done.code == 0, done.err
        for name, seat in (("serve", "gone"), ("watch", "beta")):
            done = shims.run("tmux", "-L", SOCKET, "new-session", "-d", "-s", name,
                             "sh -c 'echo serving; sleep 3600'", seat=seat)
            assert done.code == 0, done.err
        cls.done = home.tick()
        cls.saved = sorted((home.path / ".agentkit" / "tmp").glob("tmux-*"))

    def alive(self, name):
        return self.home.tmux("has-session", "-t", f"={name}").code == 0

    def test_the_tick_exits_0(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)

    def test_one_of_a_seat_ak_holds_no_record_of_is_saved_and_closed(self):
        self.assertFalse(self.alive("serve"))
        self.assertEqual(len(self.saved), 1, self.saved)
        lines = self.saved[0].read_text().splitlines()
        self.assertEqual(lines[0], "serve (started by gone)")
        self.assertIn("serving", lines[1:])

    def test_one_of_a_seat_with_a_session_in_tmux_stays(self):
        self.assertTrue(self.alive("watch"))


if __name__ == "__main__":
    unittest.main()
