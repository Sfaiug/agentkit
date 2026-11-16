"""`a` on a fresh window's `c` says each reason a move was refused for once, led by the seats it
held, and what it says never pushes the matrix's rows off the screen.

The owner (12 Nov 2026), of fourteen seats under fourteen copies of one reason that scrolled the
screen off its own rows: "weird output … Not user friendly."  Black-box: `AK_BIN`, in a person's
terminal (tests/fixtures/akterm.py) over seats as ak leaves them (tests/fixtures/akseat.py), their
harnesses fakes (tests/fixtures/fakeadapter.py): six seats on 6 Astra gone from tmux, whose
move to Fable 5.1 the fake Claude Code's `auth` refuses on Claude I, and with them one on
Opus 5.5, gone too, whose own login, Claude II, `auth` refuses too.  Fails against `/bin/false`,
and against an ak that says the six's reason six times.

Each draw fits what was said to the terminal as it is: the names leading a reason to its width,
and the reasons to the lines its rows leave, the last saying how many more there are, before
which even ak's version gives way, and then that count.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEYS = "  ↑↓←→ move   ␣ mark   r recommended   a apply to all sessions   esc back"
NO_LOGIN = "token expired; run claude, type /login and sign in again to open a seat here"
# named so long that their reason, every name before it, takes two lines
SIX = [f"acme-fix-{number}" for number in range(1, 7)]
SIX_LED = ", ".join(SIX)        # every name fits the line
SIX_WHY = "Fable 5.1: Claude I is signed out"
OTHER = "acme-0"        # listed first, so its reason is said first
LOGIN = "acme-ii"       # its own login, which only it asks
OTHER_WHY = "Fable 5.1: Claude II is signed out"
SIGNED_OUT = "this login was signed out on another machine"
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
    """The matrix's rows, from whom its marks are for to the note under them; the meters over
    them read the logins meanwhile."""
    shown = blocks(screen)
    return shown[next(n for n, block in enumerate(shown) if block.startswith("  For")):-2]


def said(screen):
    """The note under the matrix, each line as wrapped."""
    return blocks(screen)[-2].split("\n")


def told(*wrapped):
    """The lines of one thing said, as one line."""
    return " ".join(line.strip() for line in wrapped)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnApplySaysAReasonOnce(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        self.fakes["claude"].answer("auth", NO_LOGIN, 1)
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "opus": "claude", "astra": "codex"},
                       workers=["fable"], reviewers=["fable"],
                       providers={"anthropic": {"accounts": ["default", LOGIN]}})
        for name in SIX:
            Seat(self.home, name, model="astra", alive=False,
                 record={"workers": ["astra"], "reviewers": ["astra"]})

    def applied(self):
        """The screen once `Apply` is picked and the matrix is back, and the one before `a`."""
        self.term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1", **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("c config")
        self.term.keys("c")
        before = self.term.wait(lambda screen: key_line(screen) == KEYS)
        self.term.keys("a")
        self.term.wait(lambda screen: "  × Apply" in lines(screen))
        self.term.keys("Down", "Enter")
        return self.term.wait(lambda screen: key_line(screen) == KEYS
                              and "signed out" in screen), before

    def test_six_seats_refused_alike_are_told_once_led_by_the_names_that_fit(self):
        after, before = self.applied()
        _, *six = said(after)
        self.assertEqual((len(six), told(*six)), (2, f"{SIX_LED}: {SIX_WHY}"), after)
        self.assertEqual(matrix(after), matrix(before))
        self.term.resize(40, 45)
        narrow = self.term.wait(lambda screen: "─" * 41 not in screen
                                and "acme-fix-2 and 4 more:" in screen)
        self.assertEqual(told(*said(narrow)[1:]),
                         f"acme-fix-1, acme-fix-2 and 4 more: {SIX_WHY}", narrow)
        self.term.resize(100, 30)
        wide = self.term.wait(lambda screen: key_line(screen) == KEYS and SIX_LED in screen)
        self.assertEqual(said(wide), said(after))

    def other(self):
        """A seat on Opus 5.5, listed first and gone from tmux too, whose move keeps its own
        login, which `auth` refuses too."""
        self.fakes["claude"].answer("auth", SIGNED_OUT, 1, account=LOGIN)
        Seat(self.home, OTHER, model="opus", alive=False,
             record={"workers": ["opus"], "reviewers": ["opus"], "account": LOGIN})

    def test_a_seat_refused_in_other_words_is_told_on_a_line_of_its_own(self):
        self.other()
        after, before = self.applied()
        version, other, *six = said(after)
        self.assertEqual(version, "  Version ?")
        self.assertEqual(other, f"  {OTHER}: {OTHER_WHY}", after)
        self.assertEqual((len(six), told(*six)), (2, f"{SIX_LED}: {SIX_WHY}"), after)
        self.assertEqual(matrix(after), matrix(before))

    def test_a_shorter_terminal_keeps_every_row_and_says_how_many_more(self):
        self.other()
        after, before = self.applied()
        self.term.resize(100, 28)       # a line too short for both reasons under the rows
        shorter = self.term.wait(lambda screen: "  1 more reason" in lines(screen))
        version, other, more = said(shorter)
        self.assertEqual(version, "  Version ?")
        self.assertEqual(other, f"  {OTHER}: {OTHER_WHY}", shorter)
        self.assertEqual(matrix(shorter), matrix(before))
        self.assertEqual(key_line(shorter), KEYS)
        self.term.resize(100, 26)       # the rows leave one line: the first reason takes it
        first = [f"  {OTHER}: {OTHER_WHY}"]
        shortest = self.term.wait(lambda screen: key_line(screen) == KEYS
                                  and said(screen) == first)
        self.assertEqual(matrix(shortest), matrix(before))


if __name__ == "__main__":
    unittest.main()
