"""A subscription's resets are read with its usage where its adapter says them, and said by kind.

The owner (10 Nov 2026): "See amount of resets and spend one inside the ak menu", for Claude
subscriptions as for ChatGPT.  A Claude login holds several kinds of reset at once, a weekly one
beside Fable ones, and its adapter says them in its `usage` answer, because Claude's endpoint
takes one request an ask (tests/test_claude_usage_polite.py).  Where a usage answer counts them,
ak asks no `reset-status`, and the line under the usage grid says them by kind in the answer's
order, as Claude Code does; where it counts none, `reset-status` does and the line says the
count alone.  Black-box: `AK_BIN`'s `ak usage`, then its ak screen in a terminal
(tests/fixtures/akterm.py), over a harness that says `[usage] reset` and logs every verb it is
asked (tests/fixtures/meters.py).  This test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
METER = re.compile(r"[━╸─]+  \d+% left")
WEEKLY = {"kind": "weekly", "left": 1, "usable": True}
FABLE = {"kind": "Fable", "left": 3, "usable": True}
# each account's usage answer beside its week, and what its line under the grid ends with;
# `pier`'s counts none, and its `reset-status` says 2
SAID = {"shoal": ({"resets": 4, "reset_kinds": [WEEKLY, FABLE]},
                  "1 weekly, 3 Fable resets in hand"),
        "reef": ({"resets": 3, "reset_kinds": [FABLE]}, "3 Fable resets in hand"),
        "kelp": ({"resets": 1, "reset_kinds": [WEEKLY]}, "1 weekly reset in hand"),
        "pier": ({}, "2 resets in hand")}
LABELS = dict(zip(SAID, ("Test I", "Test II", "Test III", "Test IV")))


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under_grid(screen):
    """The ak screen's line under the usage grid: what the meter under the pointer says."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if METER.search(line)) + 1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ResetsSaidByKind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.meter = meters.install(cls.home, reset=True)
        for account, (said, _) in SAID.items():
            cls.meter.week("test", account, used=40, **said)
        cls.meter.resets("pier", 2)
        echo = {"harness": "echo", "provider": "test", "model": "echo-1"}
        akconfig.write(cls.home, {"echo": echo},
                       providers={"test": {"mode": "subscription", "accounts": list(SAID)}})
        done = cls.home.ak("usage")
        assert done.code == 0, done.out + done.err
        cls.term = Terminal(cls.home, size=(120, 40), env={"NO_COLOR": "1"})
        cls.addClassCleanup(cls.home.tmux, "respawn-pane", "-k", "-t", cls.term.pane,
                            "sleep 86400", server=SERVER)
        cls.main = lines(cls.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                       and "Test IV" in screen))

    def pointed(self, label):
        """The line under the grid once the pointer is on `label`'s meter."""
        row, found = next((number, found) for number, line in enumerate(self.main)
                          if (found := re.search(rf"{label}(?![IV])", line)))
        self.term.type(f"\x1b[<35;{found.start() + 3};{row + 1}M")
        return under_grid(self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                         and under_grid(screen).startswith(f"  {label}  ")))

    def test_a_usage_answer_s_resets_are_said_by_kind_and_ask_no_reset_status(self):
        for account in ("shoal", "reef", "kelp"):
            with self.subTest(account):
                self.assertRegex(self.pointed(LABELS[account]),
                                 f" · {re.escape(SAID[account][1])}$")
        asked = {account for verb, _, account in self.meter.calls() if verb == "reset-status"}
        self.assertEqual(asked, {"pier"})

    def test_a_usage_answer_counting_none_has_reset_status_count_them(self):
        self.assertRegex(self.pointed(LABELS["pier"]), f" · {re.escape(SAID['pier'][1])}$")
        self.assertIn(("reset-status", "", "pier"), self.meter.calls())


if __name__ == "__main__":
    unittest.main()
