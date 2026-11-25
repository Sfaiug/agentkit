"""Enter on a new seat's row keeps ak's screen up while the seat is made, its header naming the
job, `agentkit · starting`, and every line under it as it was; the seat then has the terminal.

The owner (24 Nov 2026): a session being started shows `starting` in the menu instead of
dropping to the shell.  A seat ak refuses to make says why on ak's own screen, and Esc there is
the menu again, no seat made.
Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) in
every colour, its motion clock held (motion.moment), its harnesses tests/fixtures/fakeadapter.py's.
The making is held on the seat's record's lock, which this test takes and lets go once ak waits
on it, as tests/test_key_apply_to_all_counts_in_the_header.py holds one.  Fails against
`/bin/false`.
"""

import fcntl
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal
from test_key_a_job_keeps_a_run_changed_while_it_adopts_it import waited_on

ROW_KEYS = "⏎ start   tab models   esc back"


def lines(screen):
    return screen.rstrip("\n").split("\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheHeaderSaysASessionIsStarting(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": {}, "astra": {"effort": "high"}})
        clock = self.home.write("clock", "1000")
        self.state = self.home.path / ".agentkit/state"
        self.menu = Terminal(self.home, size=(100, 40),
                             env={"COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(clock)})
        self.menu.wait("esc leave")
        self.menu.keys("n")
        self.menu.wait(ROW_KEYS)
        self.menu.type("fix-login")
        self.menu.wait("fix-login▏")

    def test_the_screen_stays_up_naming_the_job_until_the_seat_is_made(self):
        before = lines(self.menu.screen(colours=True))
        lock = self.state / ".session-fix-login.lock"
        with lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.menu.keys("Enter")
            deadline = time.monotonic() + 30
            while not waited_on(lock):
                self.assertLess(time.monotonic(), deadline,
                                f"ak never made the seat; it shows:\n{self.menu.screen()}")
                time.sleep(0.05)
            self.menu.wait(lambda screen: lines(screen)[0].startswith("agentkit · starting "))
            during = lines(self.menu.screen(colours=True))
            self.assertEqual(during[1:], before[1:])
        deadline = time.monotonic() + 30
        while "fix-login 1" not in self.home.tmux(
                "list-sessions", "-F", "#{session_name} #{session_attached}").out.splitlines():
            self.assertLess(time.monotonic(), deadline,
                            f"fix-login never opened; it shows:\n{self.menu.screen()}")
            time.sleep(0.05)

    def test_a_seat_ak_refuses_is_said_on_its_screen_and_esc_is_the_menu(self):
        # tmux holds the name once the row is open: `orch.create` refuses it, the row does not
        self.assertEqual(self.home.tmux("new-session", "-d", "-s", "fix-login", "sleep 600").code,
                         0)
        self.menu.keys("Enter")
        why = "new session: tmux already holds a session named 'fix-login'"
        note = self.menu.wait(lambda screen: why in " ".join(screen.split()))
        self.assertTrue(lines(note)[0].startswith("agentkit · note "), note)
        self.menu.keys("Escape")
        self.menu.wait(lambda screen: lines(screen)[-1].strip().endswith("esc leave"))
        self.assertFalse((self.state / "session-fix-login.json").exists())


if __name__ == "__main__":
    unittest.main()
