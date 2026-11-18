"""The same kind of motion takes the same time wherever ak draws it (docs/cli-design.md, Motion;
the owner, 10 Nov 2026: "complete consistency. In animations, hovering, colors, speed").

From its first frame, what comes up is at rest at 0.15 s, a cell filling at 0.1 s, in its last
shape from half way, and a light passing once gone at 0.45 s, each still moving 0.01 s before; a
light going round is, 2.0 s on, where it was (a wait's rule: tests/test_key_c_pages_come_up.py).
The screens as tests/test_moving_lights_are_the_rainbow.py drives them, on a clock of their own.
"""

import unittest
from unittest.mock import patch

from test_moving_lights_are_the_rainbow import CATALOG, Screens
from test_news_motion import Keyboard
from agentkit import config, menu, motion, terminal

Key = terminal.Key
REST = 1.0          # seconds after its first frame every motion here has long ended


class OneTime(Screens):
    def setUp(self):
        super().setUp()
        self.moved, self.records = {}, []
        self.words = {"fix-api": "needs you", "web-portal": "done"}     # nothing breathes
        config.save_session(self.cfg, "web-portal", "opus", ["astra"])
        config.save_session(self.cfg, "fix-api", "opus", ["astra"], {"cwd": "/", "created": 0})
        case, Clock = self, motion.Clock

        class Kept(Clock):      # each frame's moment -> the cells it still moves to an end
            def frame(self):
                out, now = super().frame(), motion.moment()
                case.moved[now] = {(row, column + n) for (row, column), (at, until)
                                   in self.cells.items() if until is not None
                                   for n in range(terminal.cells(at(now)))}
                return out
        for target, name, fake in (
                (motion, "Clock", Kept),
                (menu, "run_records", lambda **_kw: self.records),
                # a seat's runs are news of its row too
                (menu, "stamps", lambda cfg, found, mine, *_args: {seat["name"]: (
                    self.words.get(seat["name"]), self.tasks.get(seat["name"]),
                    repr(mine.get(seat["name"]))) for seat in found})):
            self.stack.enter_context(patch.object(target, name, fake))

    def moments(self, *seconds):
        """Steps for `run_menu`, a step each: the clock `seconds` after `since`, the first's."""
        def step(n):
            def go():
                self.since = self.since if n else self.now
                self.now = self.since + seconds[n]
            return go
        return [step(n) for n in range(len(seconds))]

    def seen(self, script, screen=None):
        """Seconds after `since` -> (the screen, as its last whole draw left it) `script` drew."""
        frames, _ = self.frames(script, 0, screen)
        return lambda seconds: next(shown for when, *shown in reversed(frames)
                                    if when == self.since + seconds)

    def assert_takes(self, seen, cells, still, rest, clock=False):
        """`cells` move from their first frame, on their way `still` seconds on and as at REST at
        `rest`; a cell filling, in its last shape from half way, by what the clock moves."""
        def shown(seconds):
            return [seen(seconds)[0].get(cell) for cell in cells]
        self.assertTrue(cells and shown(0) != shown(REST), "at rest from its first frame")
        if clock:
            self.assertTrue(set(cells) & self.moved[self.since + still], f"at rest {still} s on")
            self.assertFalse(set(cells) & self.moved[self.since + rest], f"moving {rest} s on")
        else:
            self.assertTrue(shown(still) != shown(REST), f"at rest {still} s on")
        self.assertTrue(shown(rest) == shown(REST), f"still moving {rest} s on")

    def under(self, seen, row=3):
        """Every cell from `row` down at REST."""
        return sorted(cell for cell in seen(REST)[0] if cell[0] >= row)

    def stepped(self):
        """Opus's effort on `c` for fix-api stepped onto the highest the catalog lists (`seen`)."""
        config.change_efforts("fix-api", lambda data: config.orchestrating_at(
            self.cfg["models"], data, "opus", CATALOG["claude-opus-5-5"][-2]))
        seen = self.seen([None] * 4 + [Key("down"), Key("right"), Key("space"),
                                       *self.moments(0.09, 0.1, 0.44, 0.45, REST)],
                         lambda: menu.show_config(False, Keyboard(), "fix-api"))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["efforts"]["opus"]["effort"],
                         CATALOG["claude-opus-5-5"][-1])    # applied once the page has closed
        return seen

    def test_what_comes_up_takes_150_ms(self):
        with self.subTest("the line under a row the highlight comes to"):
            seen = self.seen([None, Key("down"), *self.moments(0.14, 0.15, REST)])
            row = self.cells(seen(REST)[0], " web-portal ", "web-portal")[0][0] + 1
            self.assert_takes(seen, [cell for cell in self.under(seen) if cell[0] == row],
                              0.14, 0.15)
        with self.subTest("the rows of a page `c` opens"):
            seen = self.seen(self.moments(0.14, 0.15, REST),
                             lambda: menu.models_page(self.cfg, Keyboard()))
            self.assert_takes(seen, self.under(seen), 0.14, 0.15)
        with self.subTest("the content of the popup over a seat"):
            seen = self.seen(self.moments(0.14, 0.15, REST),
                             lambda: menu.loop(self.cfg, dry_run=True, overlay=True))
            self.assert_takes(seen, self.under(seen), 0.14, 0.15)

    def test_a_cell_filling_takes_100_ms(self):
        with self.subTest("a mark set on `c`"):
            seen = self.seen([None] * 4 + [Key("down"), Key("right"), Key("right"), Key("space"),
                                           *self.moments(0.09, 0.1, REST)],
                             lambda: menu.show_config(False, Keyboard(), "fix-api"))
            self.assert_takes(seen, self.cells(seen(REST)[0], "Opus 5.5", "■"), 0.09, 0.1,
                              clock=True)
        with self.subTest("an effort stepped up on `c`"):
            seen = self.stepped()
            self.assert_takes(seen, self.cells(seen(REST)[0], "Opus 5.5"), 0.09, 0.1, clock=True)

    def test_a_light_passing_once_takes_450_ms(self):
        with self.subTest("across a seat that turned `done`"):
            self.words["fix-api"], self.tasks = "working", {"fix-api": (4, 4)}
            seen = self.seen([None] * 3 + [
                self.news(lambda: self.words.update({"fix-api": "done"})),
                *self.moments(0.44, 0.45, REST)])
            self.assert_takes(seen, self.cells(seen(REST)[0], " fix-api "), 0.44, 0.45)
        with self.subTest("through an effort stepped to its highest"):
            seen = self.stepped()
            self.assert_takes(seen, self.cells(seen(REST)[0], "Opus 5.5", "max"), 0.44, 0.45)
        with self.subTest("none through an effort with no word, `c` drawn"), \
                patch.dict(CATALOG, {"claude-opus-5-5": ["low", ""]}):
            seen = self.stepped()
            bar = self.cells(seen(REST)[0], "Opus 5.5")
            self.assertEqual([seen(REST)[0][cell][0] for cell in bar], ["━", "━"])
            rest = [cell for cell in self.under(seen, bar[0][0]) if cell not in bar]
            for seconds in (0, 0.09, 0.44):
                self.assertEqual(*([seen(at)[0][cell] for cell in rest] for at in (seconds, REST)))

    def test_a_light_going_round_along_a_line_with_no_plan_takes_a_breath(self):
        self.words["fix-api"] = "working"
        seen = self.seen(self.moments(0.3, 1.3, 2.3))
        cells = self.cells(seen(0.3)[1], " fix-api ")
        shown, drawn = ([view[cell] for cell in cells] for view in seen(0.3))
        self.assertTrue(shown != drawn, "no light on it")
        self.assertTrue([seen(1.3)[0][cell] for cell in cells] != shown, "still a second on")
        self.assertTrue([seen(2.3)[0][cell] for cell in cells] == shown, "elsewhere 2.0 s on")


if __name__ == "__main__":
    unittest.main(verbosity=2)
