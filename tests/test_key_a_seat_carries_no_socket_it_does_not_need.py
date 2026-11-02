"""A seat carries AGENTKIT_TMUX_SOCKET only when its server is not the one its HOME names.

So HOME alone decides: an `ak` under another HOME inside a seat lands on that HOME's own server,
never the seat's, while a server a caller named stays with the seats opened on it.  Black-box: a
seat opens through tests/fixtures/akbin.py with a terminal on its stdin and a `tmux` first on PATH
that records its arguments and answers nothing, so no server is ever started or reached and the
pane's launch file is left to read.  What the seat starts with is its `-e` words, less what that
file unsets.  This test fails against `/bin/false`.
"""

import hashlib
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home

VARIABLE = "AGENTKIT_TMUX_SOCKET"


def recording(home):
    home.fake("tmux", LOG.format(python=shlex.quote(sys.executable),
                                 log=shlex.quote(str(home.log("tmux")))))


def servers(home):
    """Every server `home`'s program named after `-L` so far."""
    return {call[call.index("-L") + 1] for call in home.calls("tmux") if "-L" in call}


def own_server(home):
    place = str((home.path / ".agentkit").resolve()).encode()
    return f"agentkit-{hashlib.sha256(place).hexdigest()[:8]}"


def seat_started_with(home, socket):
    """Open a seat with the variable at `socket`: the environment it starts with, and each word
    of the tmux calls that set up its session."""
    recording(home)
    done = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", tty=True,
                   env={VARIABLE: socket})
    assert done.code == 0, done.err
    started = next(call for call in home.calls("tmux") if "new-session" in call)
    values = dict(word.split("=", 1) for before, word in zip(started, started[1:])
                  if before == "-e")
    launch = Path(shlex.split(started[-1])[-1]).read_text()
    for line in launch.splitlines():
        if line.startswith("unset "):
            for name in line.split()[1:]:
                values.pop(name, None)
    return values, [word for call in home.calls("tmux") for word in call]


class SeatSocket(unittest.TestCase):
    def setUp(self):
        self.seat_home, self.other_home = Home(), Home()
        for home in (self.seat_home, self.other_home):
            self.addCleanup(home.close)

    def test_a_seat_on_its_homes_own_server_starts_without_the_variable(self):
        values, words = seat_started_with(self.seat_home, None)
        self.assertEqual(servers(self.seat_home), {own_server(self.seat_home)})
        self.assertEqual(values["AGENTKIT_SESSION"], "acme")
        self.assertNotIn(VARIABLE, values)
        at = words.index("set-environment")
        self.assertIn(("-r", VARIABLE), zip(words[at:], words[at + 1:]))

    def test_an_ak_with_that_seats_environment_under_another_home_names_that_homes_server(self):
        values, _words = seat_started_with(self.seat_home, None)
        recording(self.other_home)
        done = self.other_home.ak("orch", "list", env={
            VARIABLE: None, **values, "HOME": str(self.other_home.path)})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(servers(self.other_home), {own_server(self.other_home)})

    def test_a_server_the_caller_named_stays_with_the_seat(self):
        values, words = seat_started_with(self.seat_home, "x")
        self.assertEqual(values[VARIABLE], "x")
        self.assertEqual(servers(self.seat_home), {"x"})
        self.assertNotIn(("-r", VARIABLE), zip(words, words[1:]))


if __name__ == "__main__":
    unittest.main()
