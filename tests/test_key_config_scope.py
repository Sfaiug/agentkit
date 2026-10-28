"""`c` edits the seat the popup is over, whichever row is highlighted, and in a window of its own
new seats' [defaults], what the next `n` starts from, changing no seat's record.

The owner (24 Oct 2026): "when inside a session and I open the menu, only that session models
should be able to be edited … when I open a new ak window … and go in the config, the changes I
make should just reflect the next default settings for new sessions I start."  Black-box: the
program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) over two seats as ak
leaves them (tests/fixtures/akseat.py), its harnesses the fakes of tests/fixtures/fakeadapter.py,
judged by what the terminal shows, the seats' records and config.toml; this test fails against
`/bin/false`.  The terminal has no colour (NO_COLOR), so the mark the keys are on is bracketed.
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

NOW = int(time.time())
SEATS = {"atoll-fix": NOW - 900, "atoll-ask": NOW - 600}     # made first, so it is 1
MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
POPUP_KEYS = "  ↑↓←→ move   ⏎ open   n new   x stop   c config   esc leave"
MARK_KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
NEW_KEYS = "  ↑↓←→ move   ␣ mark   r recommended   a apply to all sessions   esc back"   # new seats'


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConfigScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seats = {name: Seat(home, name, model="fable",
                                record={"workers": ["astra"], "created": created})
                     for name, created in SEATS.items()}

    def setUp(self):
        # each case starts from the config and the records as the seats were opened with them
        akconfig.write(self.home, {"fable": "claude",
                                   "astra": {"harness": "codex", "effort": "high"}},
                       workers=["astra"])
        for name, seat in self.seats.items():
            self.home.write(f".agentkit/state/session-{name}.json", seat.record)
        self.defaults = akconfig.read(self.home)["defaults"]

    def menu(self, *args, env=()):
        """The menu with the highlight moved from atoll-fix down to atoll-ask."""
        term = Terminal(self.home, *args, size=(100, 30), env={"NO_COLOR": "1", **dict(env)})
        # ends this case's menu, keeping the terminal's server for the next case
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        keys = POPUP_KEYS if "--overlay" in args else MAIN_KEYS
        term.wait(lambda screen: "› 1  atoll-fix" in screen and key_line(screen) == keys)
        term.keys("j")
        term.wait("› 2  atoll-ask")
        return term

    def mark_builds(self, term, scope):
        """`c`, saying whom it edits, then Fable's builds mark flipped on."""
        term.keys("c")
        keys = NEW_KEYS if scope == "new seats" else MARK_KEYS
        screen = term.wait(lambda screen: key_line(screen) == keys and "› Fable 5.1" in screen)
        self.assertIn(f"  For  {scope}", lines(screen))
        term.keys("Right", "Right")         # past its effort
        term.wait("› Fable 5.1     ●  ▰▰▰▰▱   xhigh   [□]                  □")
        term.keys("Space")
        term.wait("› Fable 5.1     ●  ▰▰▰▰▱   xhigh   [■] ▰▰▰▰▱   xhigh    □")

    def record(self, name):
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_in_the_popup_c_edits_the_seat_it_is_over_whichever_row_is_highlighted(self):
        term = self.menu("attach", "--overlay", env={"AGENTKIT_SESSION": "atoll-fix"})
        self.mark_builds(term, "atoll-fix")
        self.until(lambda: self.record("atoll-fix")["workers"] == ["astra", "fable"],
                   "atoll-fix's record never took the mark")
        self.assertEqual(self.record("atoll-ask")["workers"], ["astra"])
        self.assertEqual(akconfig.read(self.home)["defaults"], self.defaults)

    def test_in_a_window_of_its_own_c_edits_new_seats_and_no_seat(self):
        term = self.menu()
        self.mark_builds(term, "new seats")
        self.until(lambda: akconfig.read(self.home)["defaults"]["workers"] == ["astra", "fable"],
                   "[defaults] never took the mark")
        self.assertEqual(akconfig.read(self.home)["defaults"]["orchestrator"], "fable")
        for name in SEATS:
            self.assertEqual(self.record(name)["workers"], ["astra"], name)


if __name__ == "__main__":
    unittest.main()
