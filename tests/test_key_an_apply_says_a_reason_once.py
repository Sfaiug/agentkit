"""`a` on a fresh window's `c` says each reason a move was refused for once, led by the seats it
held, and what it says never pushes the matrix's rows off the screen.

The owner (12 Nov 2026), of fourteen seats under fourteen copies of one reason that scrolled the
screen off its own rows: "weird output … Not user friendly."  Black-box: `AK_BIN`, in a person's
terminal (tests/fixtures/akterm.py) over seats as ak leaves them (tests/fixtures/akseat.py), their
harnesses fakes (tests/fixtures/fakeadapter.py): six seats on GPT-6-Astra gone from tmux, whose
move to Fable 5.1 the fake Claude Code's `auth` refuses in the same words, and with them one on
Opus 5.5 whose Claude Code would take Fable in place but for Fable's spent meter.  Fails against
`/bin/false`, and against an ak that says the six's reason six times.

A terminal made a line shorter after keeps every row: the six's reason, two lines long, gives
way to how many more reasons there are.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEYS = "  ↑↓←→ move   ␣ mark   r recommended   a apply to all sessions   esc back"
# as long as a harness's own words may be: two lines with the six's names before it
NO_LOGIN = "token expired; run claude, type /login and sign in again to open a seat here"
SIX = [f"acme-{number}" for number in range(1, 7)]
SIX_LED = ", ".join(SIX)        # every name fits the line
SPENT = "acme-0"        # listed first, so its reason is said first
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def matrix(screen):
    """The matrix's rows, from whom its marks are for to the note under them; the meters over
    them read the logins meanwhile."""
    shown = lines(screen)
    return shown[shown.index("  For  new seats"):shown.index("  Version ?")]


def said(screen):
    """The note under the matrix, ak's version first, each line as wrapped."""
    shown = lines(screen)
    return shown[shown.index("  Version ?"):shown.index(key_line(screen)) - 1]


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
                       workers=["fable"], reviewers=["fable"])
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
                              and "fable: token expired;" in screen), before

    def test_six_seats_refused_alike_are_told_once_under_every_row(self):
        after, before = self.applied()
        _, *six = said(after)
        self.assertEqual((len(six), told(*six)), (2, f"{SIX_LED}: fable: {NO_LOGIN}"), after)
        self.assertEqual(matrix(after), matrix(before))

    def spent(self):
        """A seat on Opus 5.5, listed first, whose move in place Fable's spent meter refuses."""
        now = time.time()
        meters = {"meters": [{"name": "weekly_all", "used": 100, "window_secs": 604800,
                              "resets_at": now + 86400}]}
        self.fakes["claude"].answer("usage", json.dumps({**meters, "error": None}))
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "providers": {"anthropic": {"provider": "anthropic", **meters}}})
        Seat(self.home, SPENT, model="opus", record={"workers": ["opus"], "reviewers": ["opus"]})

    def test_a_seat_refused_in_other_words_is_told_on_a_line_of_its_own(self):
        self.spent()
        after, before = self.applied()
        _, other, *six = said(after)
        self.assertTrue(other.startswith(f"  {SPENT}: fable is spent · resets "), after)
        self.assertEqual((len(six), told(*six)), (2, f"{SIX_LED}: fable: {NO_LOGIN}"), after)
        self.assertEqual(matrix(after), matrix(before))

    def test_a_shorter_terminal_keeps_every_row_and_says_how_many_more(self):
        self.spent()
        after, before = self.applied()
        self.term.resize(100, 27)       # a line too short for both reasons under the rows
        shorter = self.term.wait(lambda screen: "  and 1 more" in lines(screen))
        _, other, more = said(shorter)
        self.assertTrue(other.startswith(f"  {SPENT}: fable is spent · resets "), shorter)
        self.assertEqual(more, "  and 1 more")
        self.assertEqual(matrix(shorter), matrix(before))
        self.assertEqual(key_line(shorter), KEYS)


if __name__ == "__main__":
    unittest.main()
