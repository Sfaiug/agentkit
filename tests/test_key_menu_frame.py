"""The menu's main screen is its frame and nothing else: the `agentkit` header with the clock,
a rule the full width, the usage grid, two blank lines, each project's heading over its seat
rows, and the key line last, above the two rows every draw keeps; with no seat it says how to
start one.

This is the screen the owner approved: the usage stays on top, the keys at the bottom, and no
line names what a seat works on, though its plan is read for the `N of M` on its row.  A build
that moves a part, adds a line between them or names a task draws another screen.  Black-box:
the menu runs in a person's terminal (tests/fixtures/akterm.py) beside seats of
tests/fixtures/akseat.py, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

WIDTH, HEIGHT = 100, 30
KEY_LINE = "  ↑↓←→ move   ⏎ choose   n new   c config   esc leave"
EMPTY = "  no sessions; n starts one"
PLAN = ("# Dates\n\n- [x] Teach the parser dates\n- [ ] Ship the dates page\n"
        "- [ ] Retire the old parser\n")
TASKS = ("Teach the parser dates", "Ship the dates page", "Retire the old parser")


def rows(screen, height):
    """The terminal's rows, top to bottom, without trailing blanks."""
    return [row.rstrip() for row in screen.split("\n")][:height]


def grid_end(shown):
    """The row after the usage grid, which starts under the rule and runs to a blank row."""
    return shown.index("", 2)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Frame(unittest.TestCase):
    """What every main screen holds, read at rest: once each seat's look has landed."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        atoll = home.path / "code" / "atoll"
        done = home.run("git", "init", "-q", str(atoll))
        assert done.code == 0, done.err
        filed = {"repo": str(atoll)}
        Seat(home, "atoll-fix", screen="claude-working-pane.txt", cwd=atoll, record=filed)
        Seat(home, "atoll-ask", screen="claude-question-pane.txt", cwd=atoll, record=filed)
        home.write(".agentkit/state/plan-atoll-fix.md", PLAN)
        menu = Terminal(home, size=(WIDTH, HEIGHT))

        held = {}

        def at_rest(screen):
            said = {name: next((row for row in screen.split("\n") if f" {name} " in row), "")
                    for name in ("atoll-fix", "atoll-ask")}
            # the plan's line eases out to its share and its count counts up with it
            # (agentkit/motion.py), so a fast host reads `0 of 3` mid-way: the row is at rest
            # once it has held still for a second
            if held.get("row") != said["atoll-fix"]:
                held.update(row=said["atoll-fix"], since=time.monotonic())
            return (KEY_LINE in screen and "working" in said["atoll-fix"]
                    and "needs you" in said["atoll-ask"] and time.monotonic() - held["since"] >= 1)
        cls.shown = rows(menu.wait(at_rest, bound=60), HEIGHT)

    def test_the_header_is_the_name_and_the_clock_over_a_rule_the_full_width(self):
        self.assertRegex(self.shown[0], r"^agentkit +\d\d:\d\d$")
        self.assertEqual(len(self.shown[0]), WIDTH)
        self.assertEqual(self.shown[1], "─" * WIDTH)

    def test_two_blank_lines_part_the_usage_grid_from_the_project_and_its_seats(self):
        end = grid_end(self.shown)
        self.assertGreater(end, 2, self.shown)
        self.assertEqual(self.shown[end:end + 3], ["", "", "atoll"])
        seats = self.shown[end + 3:end + 5]
        self.assertEqual(sorted(name for row in seats for name in ("atoll-fix", "atoll-ask")
                                if name in row), ["atoll-ask", "atoll-fix"])
        self.assertTrue(seats[0].startswith("›"), seats)

    def test_the_key_line_is_last_above_the_two_rows_every_draw_keeps(self):
        end = grid_end(self.shown)
        self.assertEqual(self.shown[-3], KEY_LINE)
        self.assertEqual(self.shown[-2:], ["", ""])
        # Nothing between the last seat and the key line: no tip, no task, no other line.
        self.assertFalse(any(self.shown[end + 5:-3]), self.shown)

    def test_a_seat_with_a_plan_shows_its_count_and_no_task_is_named(self):
        plan_row = next(row for row in self.shown if "atoll-fix" in row)
        self.assertTrue(plan_row.endswith(" 1 of 3"), plan_row)
        for task in TASKS:
            self.assertNotIn(task, "\n".join(self.shown))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Empty(unittest.TestCase):
    def test_with_no_seat_the_menu_says_how_to_start_one_and_esc_leaves(self):
        with Home() as home:
            height = 24     # not the frame's: the key line keeps to the bottom of any height
            menu = Terminal(home, size=(WIDTH, height))
            shown = rows(menu.wait(KEY_LINE, bound=60), height)
            end = grid_end(shown)
            self.assertEqual(shown[end:end + 3], ["", "", EMPTY])
            # no project heading, nor anything else, between it and the keys
            self.assertEqual(shown[end + 3:], [""] * (height - end - 6) + [KEY_LINE, "", ""])
            menu.keys("Escape")
            self.assertEqual(menu.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
