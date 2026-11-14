"""A Claude subscription shows the resets it holds and spends one of the kind picked, from the menu.

The owner (10 Nov 2026): "See amount of resets and spend one inside the ak menu", with any
provider.  A Claude login's kinds refill different things -- a weekly reset the week, a Fable
reset only Fable's own cap -- so its meter offers one act for each kind it can spend now, named
after it, and the one pressed is the kind its adapter is asked to spend (`reset Fable`); what
that spend read back, every meter and the count by kind, is the reading after it.  A kind held
but not spendable now is offered no act, and a spend refused leaves the reading as it was.
Black-box: `AK_BIN`'s ak screen in a terminal (tests/fixtures/akterm.py) over a Claude
subscription under the real adapters/claude.toml, its adapter a fake that logs every verb
(tests/fixtures/fakeadapter.py), NO_COLOR, so the act lit is marked `›`.  This test fails
against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
UNLIT, LIT = "  ↑↓←→ move   esc back", "  ↑↓←→ move   ⏎ {}   esc back"
METER = re.compile(r"[━╸─]+  \d+% left")
WEEK = 604800


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under_grid(screen):
    """The ak screen's line under the usage grid: what the meter under the pointer says."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if METER.search(line)) + 1]


def offered(screen):
    """The spends a meter's list offers, as drawn, `›` on the one lit."""
    return [line for line in lines(screen) if re.match(r"[ ›] → spend a", line)]


def answer(fable, left=3, fable_used=17):
    """A usage answer as adapters/claude.sh says one: the week, Fable's own cap within it, and
    the resets held by kind, `fable` whether a Fable one can be spent now."""
    until = int(time.time()) + 86400
    week = {"used": 40, "resets_at": until, "window_secs": WEEK}
    return {"meters": [{"name": "weekly_all", **week},
                       {"name": "weekly_scoped", **week, "used": fable_used, "scope": "Fable"}],
            "resets": 1 + left, "reset_kinds": [{"kind": "weekly", "left": 1, "usable": True},
                                                {"kind": "Fable", "left": left, "usable": fable}],
            "error": None}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ClaudeResetInTheMenu(unittest.TestCase):
    def open(self, fable=True):
        """The ak screen over a Claude subscription whose usage answer holds a weekly reset and
        three Fable ones, once its reading is in: the line under the grid for its meter."""
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fake = fakeadapter.install(self.home, claude="pass")["claude"]
        self.fake.answer("usage", json.dumps(answer(fable)))
        akconfig.write(self.home, {"opus": "claude"})
        self.term = Terminal(self.home, size=(120, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.main = lines(self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                         and METER.search(screen)))
        return self.pointed()

    def spot(self):
        """Where Claude's meter is: its row and a column inside its label, counted from 1."""
        row, found = next((number, found) for number, line in enumerate(self.main)
                          if (found := re.search(r"Claude", line)))
        return row + 1, found.start() + 3

    def pointed(self, *also):
        """The line under the grid once the pointer is on Claude's meter, and holding `also`."""
        row, column = self.spot()
        self.term.type(f"\x1b[<35;{column};{row}M")
        return under_grid(self.term.wait(
            lambda screen: MAIN_KEYS in lines(screen) and under_grid(screen).startswith(
                "  Claude  ") and "in hand" in screen and all(word in screen for word in also)))

    def listed(self):
        """Claude's meter clicked: the screen once its list is drawn with nothing lit."""
        row, column = self.spot()
        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        return self.term.wait(lambda screen: offered(screen) and UNLIT in lines(screen))

    def spend_fable(self):
        """`spend a Fable reset` pressed on Claude's list: moved onto, then Enter."""
        self.listed()
        self.term.keys("Down", "Down")
        self.term.wait(lambda screen: "› → spend a Fable reset" in lines(screen)
                       and LIT.format("spend a Fable reset") in lines(screen))
        self.term.keys("Enter")

    def noted(self, said):
        """The notice the press ends in, saying `said`, put away with Esc."""
        self.term.wait(lambda screen: said in screen and MAIN_KEYS not in lines(screen))
        self.term.keys("Escape")
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))

    def test_a_meter_says_its_resets_by_kind_and_offers_a_spend_of_each(self):
        line = self.open()
        self.assertIn(" · Fable 83% left", line)
        self.assertTrue(line.endswith(" · 1 weekly, 3 Fable resets in hand"), line)
        self.assertEqual(offered(self.listed()),
                         ["  → spend a weekly reset", "  → spend a Fable reset"])
        self.assertEqual(self.fake.calls("reset-status"), [])
        self.assertEqual(self.fake.calls("reset"), [])

    def test_a_fable_reset_spent_shows_what_its_spend_read_back(self):
        self.open()
        # what `reset` reads back once a Fable reset has gone: Fable's cap refilled, two left
        after = answer(True, left=2, fable_used=0)
        self.fake.answer("reset", json.dumps({"code": "reset", "available": after["resets"],
                                              "reset_kinds": after["reset_kinds"],
                                              "meters": after["meters"]}), given=("Fable",))
        self.spend_fable()
        self.noted("Claude · 60% left")
        line = self.pointed("Fable 100%")
        self.assertIn(" · Fable 100% left", line)
        self.assertTrue(line.endswith(" · 1 weekly, 2 Fable resets in hand"), line)
        self.assertEqual([call["argv"] for call in self.fake.calls("reset")], [["Fable"]])

    def test_a_kind_it_cannot_spend_now_is_offered_no_act(self):
        self.assertTrue(self.open(fable=False).endswith(" · 1 weekly, 3 Fable resets in hand"))
        self.assertEqual(offered(self.listed()), ["  → spend a weekly reset"])

    def test_a_spend_refused_spends_nothing_and_the_line_reads_as_before(self):
        before = self.open()
        self.fake.answer("reset", json.dumps({"code": "cooldown"}), given=("Fable",))
        self.spend_fable()
        self.noted("Claude: no reset was spent")
        self.assertEqual(self.pointed(), before)
        self.assertEqual([call["argv"] for call in self.fake.calls("reset")], [["Fable"]])


if __name__ == "__main__":
    unittest.main()
