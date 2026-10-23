"""The menu fits the terminal it is on: narrow when it shrinks, and never wider than 120 columns.

A person resizes a window, or opens ak on a phone at 40 columns: the menu redraws at once in its
narrow form, every line within the screen, each subscription on a line of its own, a seat's
progress line under its row and the keys wrapped whole.  On a wide monitor the frame stops at 120
columns and a seat's row at 100, so a row reads the same as on an ordinary terminal.  The
terminal is tmux (tests/fixtures/akterm.py), resized as a person's window is.
"""

from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

WEEK = 7 * 24 * 3600
CLOCK = re.compile(r"^agentkit +\d\d:\d\d$")
# The rule under the header, its glide (motion.fetching) lit while the usage is still fetched.
RULE = "^[─━]{%d}$"
FIX = "atoll-fix  Fable 5.1  ● working"


def shown(screen):
    return screen.split("\n")


def settled(screen):
    """Every seat says its word and the plan its count: the first frame comes before both."""
    return all(part in screen for part in ("! needs you", "● working", "3 of 7", "esc leave"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MenuWidth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        atoll = cls.home.path / "code" / "atoll"
        (atoll / ".git").mkdir(parents=True)
        # Seats are numbered in the order they were made, the highlight on the first.
        for name, screen, made in (("atoll-fix", "claude-working-pane.txt", 1200),
                                   ("atoll-ask", "claude-question-pane.txt", 600)):
            Seat(cls.home, name, model="fable", screen=screen, cwd=atoll,
                 record={"repo": str(atoll), "created": int(time.time()) - made})
        cls.home.write(".agentkit/state/plan-atoll-fix.md",
                       "".join(f"- [x] step {n}\n" for n in range(1, 4))
                       + "".join(f"- [ ] step {n}\n" for n in range(4, 8)))
        cls.home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": 79}]},
            "openai": {"meters": [{"name": "weekly", "used": 31, "window_secs": WEEK}]}}})

    def menu(self, width):
        term = Terminal(self.home, size=(width, 30))
        self.addCleanup(term.keys, "Escape")
        return term, shown(term.wait(settled))

    def test_a_resize_to_40_columns_redraws_the_menu_in_its_narrow_form(self):
        term, _ = self.menu(100)
        term.resize(40, 30)
        lines = shown(term.wait(lambda screen: settled(screen)
                                and "  c config   esc leave" in shown(screen)))
        self.assertRegex(lines[0], CLOCK)
        self.assertEqual(len(lines[0]), 40)
        self.assertRegex(lines[1], RULE % 40)
        self.assertIn("  Claude   ▰▰▱▱▱▱▱▱▱▱  21% left", lines)
        self.assertIn("  ChatGPT  ▰▰▰▰▰▰▰▱▱▱  69% left", lines)
        row = lines.index(f"› 1  {FIX}")
        self.assertRegex(lines[row + 1], r"^    ━+╸?─* 3 of 7$")
        self.assertEqual([line for line in lines if line.strip()][-2:],
                         ["  ↑↓ move   ⏎ open   n new   x stop", "  c config   esc leave"])
        self.assertEqual([line for line in lines if len(line) > 40], [])

    def test_past_120_columns_the_frame_stops_at_120_and_a_seat_row_at_100(self):
        _, lines = self.menu(170)
        self.assertRegex(lines[0], CLOCK)
        self.assertEqual(len(lines[0]), 120)
        self.assertRegex(lines[1], RULE % 120)
        self.assertEqual([line for line in lines if len(line) > 120], [])
        wide = next(line for line in lines if FIX in line)
        self.assertTrue(wide.endswith(" 3 of 7"), wide)
        self.assertEqual(len(wide), 100)
        # A terminal of its own: one shrunk from 170 keeps the old row, cut by tmux, until a draw.
        # A working seat's line fills smoothly, so only where it runs is the same.
        _, lines = self.menu(100)
        self.assertEqual(layout(next(line for line in lines if FIX in line)), layout(wide))


def layout(row):
    """The row with its progress line as the cells it takes, however much of it is filled."""
    return re.sub(r"[━╸─]+", lambda line: f"<{len(line[0])} cells>", row)


if __name__ == "__main__":
    unittest.main()
