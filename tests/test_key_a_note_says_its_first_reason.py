"""A note under `c`'s rows with no room for its first reason names fewer seats until the reason
fits the lines the rows leave, and cuts it to them only where no fewer names fit, never saying
only a count of what it does not show.

Black-box: `AK_BIN`, in a person's terminal (tests/fixtures/akterm.py) over seats as ak leaves
them (tests/fixtures/akseat.py), their harnesses fakes (tests/fixtures/fakeadapter.py), as
tests/test_key_an_apply_says_a_reason_once.py drives `a` on `c`: six seats on 6 Astra gone from
tmux, whose move to Fable 5.1 the fake Claude Code's `auth` refuses on Claude I, their names and
that reason two lines long, on a 100x25 terminal; then six whose first name alone fills the
line.  Fails against `/bin/false`, against an ak that says "1 more reason" and nothing of the
reason, and against one that cuts off what was refused where fewer names would have fitted it.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEYS = "  ↑↓←→ move   ␣ mark   r your runs   a apply to all sessions   esc back"
NO_LOGIN = "token expired; run claude, type /login and sign in again to open a seat here"
SIX = [f"acme-fix-{number}" for number in range(1, 7)]
LONG = [f"acme-fix-{'the-long-errand-' * 4}{number}" for number in range(1, 7)]
WHY = "Fable 5.1: Claude I is signed out"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def blocks(screen):
    """The screen's runs of lines between blank ones: the note is the last over the keys'."""
    return "\n".join(lines(screen)).strip("\n").split("\n\n")


def matrix(screen):
    """The matrix's rows, from whom its marks are for to the note under them."""
    shown = blocks(screen)
    return shown[next(n for n, block in enumerate(shown) if block.startswith("  For")):-2]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ANoteSaysItsFirstReason(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        fakes["claude"].answer("auth", NO_LOGIN, 1)
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "astra": "codex"},
                       workers=["fable"], reviewers=["fable"],
                       providers={"anthropic": {"accounts": ["default", "acme-ii"]}})

    def applied(self, names):
        """The one line the rows leave the note once `a` held seats `names`, every row still up."""
        for name in names:
            Seat(self.home, name, model="astra", alive=False,
                 record={"workers": ["astra"], "reviewers": ["astra"]})
        term = Terminal(self.home, size=(100, 25), env={"NO_COLOR": "1", **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        before = term.wait(lambda screen: key_line(screen) == KEYS)
        term.keys("a")
        term.wait(lambda screen: "  × Apply" in lines(screen))
        term.keys("Down", "Enter")
        after = term.wait(lambda screen: key_line(screen) == KEYS
                          and blocks(screen)[-2].startswith(f"  {names[0]}"))
        self.assertEqual(matrix(after), matrix(before))
        # every row stays on screen, down to the last
        self.assertTrue(matrix(after)[-1].split("\n")[-1].startswith("  Money "), after)
        note = blocks(after)[-2].split("\n")
        self.assertEqual(len(note), 1, after)
        return note[0]

    def test_a_reason_taller_than_the_lines_left_names_fewer_seats(self):
        self.assertEqual(self.applied(SIX), f"  {', '.join(SIX[:4])} and 2 more: {WHY}")

    def test_a_reason_no_fewer_names_fit_is_cut_to_the_lines_left(self):
        note = self.applied(LONG)
        self.assertTrue(note.endswith("…"), note)
        self.assertTrue(f"  {LONG[0]} and 5 more: {WHY}".startswith(note[:-1]), note)


if __name__ == "__main__":
    unittest.main()
