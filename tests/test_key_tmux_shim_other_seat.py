"""Inside a seat, its tmux can neither end another seat nor type into one.

Seats never message one another, and nothing one seat writes is typed into another (owner
rules).  A seat's tmux refuses a call that would end another seat's session or type into its
pane, in each form tmux takes one, and says why; the seat's own pane, a session that is no seat,
and every call of a worker or of no seat pass.  Black-box: the shims a seat's launch installs
(tests/fixtures/shims.py), run as a seat's commands against the Home's real tmux, judged by the
sessions tmux holds and what each pane received; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

ENDS = ("ak refused `tmux {}`: it would end beta, another session's seat. A seat never ends "
        "another seat; ask the owner.\n")
TYPES = ("ak refused `tmux {}`: it would type into beta, another session's seat. Nothing a "
         "seat writes is typed into another seat.\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnotherSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        cls.acme, cls.beta = Seat(cls.home, "acme"), Seat(cls.home, "beta")
        cls.home.tmux("set-buffer", "pasted")     # a paste that got through would show

    def tmux(self, *args, seat="acme", env=None):
        return self.shims.run("tmux", "-L", SOCKET, *args, seat=seat, env=env)

    def refused(self, cases, why, untyped=()):
        """Each call refused, and beta, and each seat of `untyped`, as they were before."""
        seats = (self.beta, *untyped)
        counts = [len(seat.lines()) for seat in seats]
        for args, command in cases:
            with self.subTest(args=args):
                done = self.tmux(*args)
                self.assertEqual((done.code, done.err), (1, why.format(command)))
        self.assertEqual(self.home.tmux("has-session", "-t", "=beta").code, 0)
        for seat, count in zip(seats, counts):
            # tmux types in order: what reached the pane before shows in or before this line
            self.home.tmux("send-keys", "-t", seat.pane, "-l", "mark")
            self.home.tmux("send-keys", "-t", seat.pane, "Enter")
            self.assertEqual(seat.wait_lines(count + 1)[count:], ["mark"], seat.name)

    def test_each_way_of_ending_another_seat_is_refused_and_it_lives(self):
        self.refused([(("kill-session", "-t", "beta"), "kill-session"),
                      (("kill-session", "-t", "=beta"), "kill-session"),
                      (("kill-window", "-t", "=beta:"), "kill-window"),
                      (("kill-pane", "-t", self.beta.pane), "kill-pane"),
                      (("kill-session", "-a"), "kill-session"),
                      (("kill-server",), "kill-server")], ENDS)

    def test_a_refused_command_takes_the_whole_call_with_it(self):
        self.refused([(("send-keys", "-t", "=acme:", "x", ";", "kill-window", "-t", "=beta:"),
                       "kill-window")], ENDS, untyped=[self.acme])

    def test_typing_into_another_seat_is_refused(self):
        self.refused([(("send-keys", "-t", "beta:", "hi", "Enter"), "send-keys"),
                      (("send-keys", "-t", "=beta:", "-l", "hi"), "send-keys"),
                      (("paste-buffer", "-t", "beta"), "paste-buffer")], TYPES)

    def test_its_own_pane_and_a_session_that_is_no_seat_take_what_it_types(self):
        scratch = Seat(self.home, "scratch")
        # a session ak keeps no record of is no seat
        (self.home.path / ".agentkit/state/session-scratch.json").unlink()
        self.addCleanup(self.home.tmux, "kill-session", "-t", "=scratch")
        for seat in (self.acme, scratch):
            with self.subTest(seat=seat.name):
                count = len(seat.lines())
                for keys in (("-l", "hi"), ("Enter",)):
                    done = self.tmux("send-keys", "-t", f"={seat.name}:", *keys)
                    self.assertEqual(done.code, 0, done.err)
                self.assertEqual(seat.wait_lines(count + 1)[count:], ["hi"])

    def test_a_worker_and_a_command_of_no_seat_may_end_another_seat(self):
        for seat, env in (("acme", {"AK_RUN_ROLE": "worker"}), (None, None)):
            with self.subTest(seat=seat, env=env):
                Seat(self.home, "gamma")
                self.addCleanup(self.home.tmux, "kill-session", "-t", "=gamma")
                done = self.tmux("kill-session", "-t", "gamma", seat=seat, env=env)
                self.assertEqual(done.code, 0, done.err)
                self.assertNotEqual(self.home.tmux("has-session", "-t", "=gamma").code, 0)


if __name__ == "__main__":
    unittest.main()
