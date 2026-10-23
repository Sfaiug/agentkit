"""A tmux session a seat started is saved and closed once every pane in it has been dead a day.

A seat starts sessions of its own for a build, a server or a long test, and nothing ends them
once their work is done: a tick saves each pane's screen to ~/.agentkit/tmp and closes the
session the day after its last pane ended.  Younger than a day, with a pane still running, or
started by no seat, it stays: the owner's own sessions on ak's server are never the tick's.
Black-box: the sessions start through a seat's own tmux shim (tests/fixtures/shims.py) on the
Home's real tmux, and the tick runs boxed with a loopback of its own, as cron runs it; judged by
what tmux holds and the files the tick wrote.  This test fails against `/bin/false`.

tmux stamps a pane's end with its server's own clock, which nothing outside can wind back: the
tick here meets a tmux that reads each dead pane's end `@dead_ago` seconds earlier than it was,
where the pane's session holds that option, so a pane can be a day dead without a day's wait.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home, boxable
from fixtures.shims import Shims

DAY = 86400
# A dead pane's end as the tick's tmux reads it: `@dead_ago` seconds back where its session holds
# that option.
AGO = ("#{?#{&&:#{pane_dead},#{@dead_ago}},#{e|-:#{pane_dead_time},#{@dead_ago}},"
       "#{pane_dead_time}}")
WOUND = """#!{python} -I
import os, sys
wound = [arg.replace("#{{pane_dead_time}}", {ago!r}) for arg in sys.argv[1:]]
os.execv({held!r}, [{held!r}, *wound])
"""


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class FinishedSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.shims = Shims(home)
        held = home.root / "tmux-held"
        (home.bin / "tmux").rename(held)
        home.fake("tmux", WOUND.format(python=sys.executable, held=str(held), ago=AGO))
        cls.finished("docs", DAY + 3600)
        cls.finished("lint", DAY - 3600)
        cls.finished("notes", DAY + 3600, seat=None)
        cls.finished("serve", DAY + 3600)
        done = home.tmux("split-window", "-d", "-t", "=serve:", "sleep 3600")
        assert done.code == 0, done.err
        cls.done = home.tick()
        cls.saved = sorted((home.path / ".agentkit" / "tmp").glob("tmux-*"))

    @classmethod
    def finished(cls, name, ago, seat="acme"):
        """A session whose one pane printed `built` and ended `ago` seconds back, started by
        that seat's own tmux, or by the test where no seat is named."""
        start = ("-L", SOCKET, "new-session", "-d", "-s", name, "-x", "60", "-y", "8",
                 "-P", "-F", "#{pane_id}", "sh -c 'read go; echo built'")
        done = (cls.shims.run("tmux", *start, seat=seat) if seat else
                cls.home.tmux(*start[2:]))
        assert done.code == 0, done.err
        pane = done.out.strip()
        for option in (("remain-on-exit", "on"), ("@dead_ago", str(ago))):
            assert cls.home.tmux("set-option", "-t", f"={name}:", *option).code == 0
        cls.home.tmux("send-keys", "-t", pane, "Enter")
        deadline = time.monotonic() + 30
        while cls.home.tmux("display-message", "-p", "-t", pane, "#{pane_dead}").out != "1\n":
            assert time.monotonic() < deadline, f"the pane of {name} never ended"
            time.sleep(0.05)

    def alive(self, name):
        return self.home.tmux("has-session", "-t", f"={name}").code == 0

    def test_the_tick_exits_0(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)

    def test_one_a_seat_started_dead_a_day_is_saved_and_closed(self):
        self.assertFalse(self.alive("docs"))
        self.assertEqual(len(self.saved), 1, self.saved)
        self.assertRegex(self.saved[0].name, r"^tmux-[0-9a-f]+\.txt$")
        lines = self.saved[0].read_text().splitlines()
        self.assertEqual(lines[0], "docs (started by acme)")
        self.assertIn("built", lines[1:])      # the pane's screen, as it was left

    def test_one_dead_less_than_a_day_stays(self):
        self.assertTrue(self.alive("lint"))

    def test_one_with_a_pane_still_running_stays(self):
        self.assertTrue(self.alive("serve"))

    def test_one_no_seat_started_stays_however_long_dead(self):
        self.assertTrue(self.alive("notes"))


if __name__ == "__main__":
    unittest.main()
