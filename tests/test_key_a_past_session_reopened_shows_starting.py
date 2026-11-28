"""A session reopened from ak's screen keeps that screen up while its harness comes back, its
header naming the job, `agentkit · starting`, over the seat's row; the seat then has the
terminal, and a key typed meanwhile is the seat's.

The owner (24 Nov 2026): a session being started shows `starting` in the menu instead of
dropping to the shell.  A seat whose harness exited, Enter on its row; a closed one, Enter on
`past sessions`, whose header then reads `agentkit · past sessions · starting`.
Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its
motion clock held (motion.moment), beside seats of tests/fixtures/akseat.py whose harness is
tests/fixtures/fakeadapter.py's.  The reopening is held on the seat's record's lock, which this
test takes and lets go once ak waits on it, as
tests/test_key_the_header_says_a_session_is_starting.py holds a seat's making.  Fails against
`/bin/false`.
"""

import fcntl
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_a_job_keeps_a_run_changed_while_it_adopts_it import waited_on

BACK = "the harness is back"
HARNESS = f"sh -c 'echo {BACK}; IFS= read -r line; echo \"got <$line>\"; exec sleep 300'"


def lines(screen):
    return screen.rstrip("\n").split("\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class APastSessionReopenedShowsStarting(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        fakeadapter.install(self.home, claude="pass")["claude"].answer("interactive", HARNESS)

    def menu(self, up):
        """ak on a 100x30 terminal, once `up` holds of its screen: its usage meter read, the
        fake's an error, so no reading lands on it later."""
        self.clock = self.home.write("clock", "1000")
        self.term = Terminal(self.home, size=(100, 30), env={"AK_MOTION_CLOCK": str(self.clock)})
        self.term.wait(lambda screen: up(screen) and "— not reached" in screen)

    def held_under(self, header):
        """Enter, the reopening held: the header names it over fix-api's row, and a key typed
        then is the seat's; let go, the owner is in the seat with its harness back."""
        row = next(line for line in lines(self.term.screen()) if "fix-api" in line)
        lock = self.home.path / ".agentkit/state/.session-fix-api.lock"
        with lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.term.keys("Enter")
            deadline = time.monotonic() + 30
            while not waited_on(lock):
                self.assertLess(time.monotonic(), deadline,
                                f"ak never reopened the seat; it shows:\n{self.term.screen()}")
                time.sleep(0.05)
            during = lines(self.term.wait(
                lambda screen: lines(screen)[0].startswith(f"agentkit · {header} ")))
            self.assertIn(row, during[1:])
            self.term.type("z")
        self.term.wait(BACK)
        self.assertEqual(self.home.tmux("list-clients", "-F", "#{client_session}").out.split(),
                         ["fix-api"])
        self.term.keys("Enter")
        self.term.wait("got <z>")

    def test_a_seat_whose_harness_exited_says_starting_on_the_ak_screen(self):
        Seat(self.home, "fix-api")
        self.assertEqual(self.home.tmux("respawn-pane", "-k", "-t", "=fix-api:", "true").code, 0)
        deadline = time.monotonic() + 30
        while self.home.tmux("display-message", "-p", "-t", "=fix-api:",
                             "#{pane_dead}").out.strip() != "1":
            self.assertLess(time.monotonic(), deadline, "fix-api's harness never exited")
            time.sleep(0.05)
        self.menu(lambda screen: "fix-api" in screen and "esc leave" in lines(screen)[-1])
        self.held_under("starting")

    def test_a_closed_session_says_starting_on_past_sessions(self):
        Seat(self.home, "fix-api", alive=False)
        self.home.write(".agentkit/state/seat-fix-api.json",
                        {"stopped_at": time.time() - 9000, "closed_by_owner": True})
        self.menu(lambda screen: "p past" in lines(screen)[-1])
        self.term.keys("p")
        self.term.wait(lambda screen: "fix-api" in screen and "⏎ reopen" in screen)
        # its title comes up on the clock: moved on, so it is whole
        moved = self.clock.with_name("clock.new")
        moved.write_text("1010")
        moved.replace(self.clock)
        self.term.wait(lambda screen: screen.startswith("agentkit · past sessions "))
        self.held_under("past sessions · starting")


if __name__ == "__main__":
    unittest.main()
