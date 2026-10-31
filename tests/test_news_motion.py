"""A change on the main screen announces itself once, then is still.

`menu.loop` on a scripted wait over a true-colour terminal, news landing the way `Live` brings
it -- the seats read again and a byte on the wake pipe: a seat turning `needs you` pulses its `!`
twice toward the light over 600 ms and is still in its colour; one turning `done` has its `✓`
settle from bright to its colour over 400 ms; a seat's progress line glides to its new length
with a light at its head over 700 ms.  The first
draw, one after another screen, a notice or a resize, and a menu opened again draw what they find
as it is, and nothing moves under NO_COLOR.  Offline, in a throwaway HOME:
the probe is never started, the reads are the test's own, the keyboard is a stand-in, and the
menu's clock moves only as the stand-in's waits run, so a loaded host draws no frame late.
"""

import io
import json
import os
import re
import select
from unittest.mock import patch
import unittest

from fixtures.clock import Clock
from fixtures.sandbox import Sandbox, menu_input
from agentkit import config, menu, motion, orch, terminal

Key = terminal.Key
NEEDS = (0xf9, 0xe2, 0xaf)          # `needs you` on a dark background
DONE = (0xa6, 0xe3, 0xa1)           # `done`
CELL = re.compile(r"\x1b\[(\d+);(\d+)H((?:(?!\x1b\[\d+;\d+H).)*)", re.S)
WEEK = 604800


def painted(text):
    """What a frame wrote, a cell at a time: (character, its colour as (r, g, b), or None)."""
    colour, found = None, []
    for escape, final, char in re.findall(r"\x1b\[([\d;]*)([A-Za-z])|(.)", text, re.S):
        if char:
            found.append((char, colour))
            continue
        if final != "m":
            continue                        # a move or a clear, no colour
        codes = escape.split(";")
        if "38" in codes:
            colour = tuple(int(code) for code in codes[codes.index("38") + 2:][:3])
        elif codes[0] == "0":
            colour = None
    return found


class Keyboard:
    """A terminal the menu has taken, so keys are `terminal.Key`s and the screen is written over."""

    def take(self):
        return True

    def give(self):
        pass

    def close(self):
        pass


class NewsMotion(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop("NO_COLOR")
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color",
            "COLORTERM": "truecolor"}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.words, self.tasks, self.notices, self.live, self.reasons = {}, {}, [], None, {}
        self.cache(used=20)
        self.now = 1000.0                   # the menu's clock: still but for the waits it runs
        clock = Clock(self.sleep)
        clock.monotonic = lambda: self.now

        def row_state(cfg, session, look=True, **facts):
            return {"word": self.words[session["name"]],
                    "reason": self.reasons.get(session["name"], ""), "since": None}

        def watch(live, last):              # read once, now, and again only when news says so
            self.live, live.last = live, last
            live.read()

        for target, name, fake in (
                (orch, "listing", lambda: [{"name": name, "repo": str(repo), "path": str(repo),
                                            "created": 0} for name in self.words]),
                (menu, "run_records", lambda **_kw: []),
                (menu, "seat_row_state", row_state),
                (menu, "seat_progress", lambda name: self.tasks.get(name, (0, 0))),
                (orch, "job_notices", lambda: [self.notices.pop()] if self.notices else []),
                (menu.Live, "probe", lambda self, now=None: False),
                (menu.Live, "watch", watch),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),     # a taken keyboard's, no real terminal's
                (terminal, "width", lambda *args: 100),
                (menu, "time", clock), (motion, "time", clock)):
            self.stack.enter_context(patch.object(target, name, fake))
        self.addCleanup(setattr, terminal, "_ASKED", False)

    def sleep(self, seconds):
        self.now += seconds

    def cache(self, used):
        """Claude's shared week, `used` percent spent, as the probe writes it."""
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": used, "resets_at": 136800,
                                      "window_secs": WEEK}]}}}))

    def news(self, change):
        """A step on which `change` lands: the seats are read again and the wait is woken."""
        def step():
            change()
            self.live.read()
            self.live._wake()
        return step

    def run_menu(self, script, after=1.2):
        """`menu.loop` through `script`, a step a wait, and each wait's timeout, when it began and
        what was written before it; and the wait at which the last step was taken.

        A step is None for a wait nothing is typed in, a function for news landing in it, or a
        key.  Past the script the waits run on, and the menu is left once nothing moves or
        `after` seconds have passed.  A wake still unanswered ends a wait at once, as it does.
        """
        out, waits, steps = io.StringIO(), [], list(script)
        out.isatty = lambda: True           # a terminal, as far as colour is concerned
        last = {}

        def wait_key(prompt, timeout=None, wake=None):
            waits.append((timeout, self.now, out.getvalue()))
            out.seek(0)
            out.truncate()
            if wake is not None and select.select([wake], [], [], 0)[0]:
                return None
            if not steps:
                last.setdefault("at", (len(waits) - 1, self.now))
                if timeout > motion.FRAME or self.now - last["at"][1] > after:
                    return ""
                self.sleep(timeout)
                return None
            step = steps.pop(0)
            if callable(step):
                step()
                return None
            if step is None:
                self.sleep(min(timeout, motion.FRAME))
            return step

        with menu_input(wait=wait_key, return_value="q"), \
                patch("sys.stdout", out):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        return waits, last["at"][0]

    def written(self, waits, since):
        """The screen drawn at or after wait `since`, and each cell written from it on: (when,
        (row, column), text), the draw's own first frame first."""
        drawn = next(n for n in range(since, len(waits)) if waits[n][2].startswith("\033[H"))
        cells = []
        for timeout, at, text in waits[drawn:]:
            if cells and text.startswith("\033[H"):
                break                        # drawn again: what follows is another screen's
            tail = text.rpartition("\033[J")[2] if text.startswith("\033[H") else text
            cells += [(at, (int(row), int(column)), what)
                      for row, column, what in CELL.findall(tail)]
        return waits[drawn][2], cells

    def cell(self, screen, name, text):
        """Where `text` starts on `name`'s row of a drawn screen: its row and its column."""
        lines = screen.partition("\033[H")[2].rpartition("\033[J")[0].split("\n")
        for row, line in enumerate((terminal.ANSI.sub("", line) for line in lines), 1):
            if name in line and text in line:
                return row, terminal.cells(line[:line.index(text)]) + 1
        self.fail(f"no {text!r} on {name}'s row:\n{screen}")

    def assert_glows(self, cells, row, colour):
        """The whole of `row` on a background of `colour` at first, fading to none in about a
        second, and as drawn at the end."""
        frames = [(when, text) for when, cell, text in cells if cell == (row, 1)]
        backs = [re.findall(r"48;2;(\d+);(\d+);(\d+)", text) for _, text in frames]
        first = tuple(int(part) for part in backs[0][0])
        # its word's colour, a third of the way up from the background
        self.assertTrue(all(abs(first[n] - colour[n] * 0.3) < 12 for n in range(3)), first)
        self.assertEqual(backs[-1], [])
        self.assertTrue(0.8 <= frames[-1][0] - frames[0][0] <= 1.3, frames[-1][0] - frames[0][0])
        self.assert_on_glow(cells, row)

    def assert_on_glow(self, cells, row):
        """What moves inside `row` while it glows is written on the glow."""
        last = max(n for n, (_, cell, _) in enumerate(cells) if cell == (row, 1))
        inside = [text for _, (at, column), text in cells[:last] if at == row and column > 1]
        self.assertTrue(inside and all("48;2;" in text for text in inside), inside)

    def assert_still(self, waits):
        """Nothing moves now: the menu was left on a wait longer than a frame."""
        self.assertGreater(waits[-1][0], motion.FRAME)

    def test_a_seat_turning_needs_you_pulses_twice_then_is_still(self):
        self.words = {"fix-api": "working", "web-portal": "done"}
        waits, at = self.run_menu([None] * 3 + [self.news(
            lambda: self.words.update({"fix-api": "needs you"}))])
        screen, cells = self.written(waits, at)
        mark = self.cell(screen, "fix-api", "! needs you")
        # the `!` and its row's glow, and nothing else
        self.assertEqual({cell for _, cell, _ in cells}, {mark, (mark[0], 1)})
        self.assert_glows(cells, mark[0], NEEDS)
        cells = [one for one in cells if one[1] == mark]
        shades = []
        for _, _, text in cells:
            [(char, colour)] = painted(text)
            self.assertEqual(char, "!")
            shades.append(colour)
        light = [sum(colour) for colour in shades]
        # toward the light and back, twice: two peaks, and never dimmer than its colour
        self.assertEqual(sum(1 for n in range(1, len(light) - 1)
                             if light[n - 1] < light[n] > light[n + 1]), 2, shades)
        self.assertGreater(max(light), sum(NEEDS) + 40)
        self.assertTrue(all(value >= sum(NEEDS) for value in light), shades)
        # about 600 ms in all, and it ends in its own colour and stays there
        self.assertEqual(shades[-1], NEEDS)
        self.assertTrue(0.55 <= cells[-1][0] - cells[0][0] <= 0.9, cells[-1][0] - cells[0][0])
        self.assert_still(waits)

    def test_a_seat_turning_done_settles_from_bright(self):
        self.words = {"fix-api": "working", "web-portal": "needs you"}
        waits, at = self.run_menu([None] * 3 + [self.news(
            lambda: self.words.update({"fix-api": "done"}))])
        screen, cells = self.written(waits, at)
        tick = self.cell(screen, "fix-api", "✓ done")
        # the `✓` and its row's glow; web-portal's `!` is old news
        self.assertEqual({cell for _, cell, _ in cells}, {tick, (tick[0], 1)})
        self.assert_glows(cells, tick[0], DONE)
        cells = [one for one in cells if one[1] == tick]
        shades = [colour for _, _, text in cells for char, colour in painted(text)]
        light = [sum(colour) for colour in shades]
        # bright the moment it appears, then easing down to `done`'s colour and no further
        self.assertGreater(light[0], sum(DONE) + 60)
        self.assertEqual(light, sorted(light, reverse=True))
        self.assertEqual(shades[-1], DONE)
        self.assertTrue(0.35 <= cells[-1][0] - cells[0][0] <= 0.7, cells[-1][0] - cells[0][0])
        self.assert_still(waits)

    def test_a_line_just_done_is_crossed_by_one_light(self):
        for width in (100, 50):     # the line on the seat's row, or narrow on the line under it
            with self.subTest(width=width), patch.object(terminal, "width", lambda *_: width):
                self.crossed()

    def test_completion_prose_is_never_swept(self):
        for width in (100, 50):
            for locale, depth in (("C.UTF-8", 24), ("C", 256)):
                for progress in ((0, 0), (0, 2), (2, 2)):
                    with self.subTest(width=width, locale=locale, progress=progress), \
                            patch.dict(os.environ, {"LANG": locale, "LC_ALL": locale}), \
                            patch.object(terminal, "width", return_value=width), \
                            patch.object(terminal, "height", return_value=30), \
                            patch.object(terminal, "colour_depth", return_value=depth), \
                            patch.object(motion.time, "monotonic", return_value=10.0), \
                            patch("sys.stdout", io.StringIO()) as out:
                        self.words, self.tasks = {"fix-api": "working"}, {"fix-api": progress}
                        self.reasons = {}
                        clock = motion.Clock()
                        menu.draw(self.cfg, orch.listing(), cursor="fix-api", drawn={},
                                  look=False, records=[], clock=clock)
                        self.words["fix-api"] = "done"
                        self.reasons["fix-api"] = "Deployed - 1 of 2 services updated; ━╸─= 3 of 4"
                        out.seek(0)
                        out.truncate()
                        menu.draw(self.cfg, orch.listing(), cursor="fix-api", drawn={},
                                  look=False, records=[], clock=clock)
                        lines = terminal.ANSI.sub("", out.getvalue().partition("\033[J")[0]).split("\n")
                        prose = next(n for n, line in enumerate(lines, 1) if "Deployed" in line)
                        self.assertFalse([cell for cell in clock.cells if cell[0] >= prose])
                        if progress[1]:
                            row = next(n for n, line in enumerate(lines, 1)
                                       if f"{progress[0]} of {progress[1]}" in line)
                            swept = [terminal.plain(animation(10.1))
                                     for (r, col), (animation, _) in clock.cells.items()
                                     if r == row and col > 1]
                            self.assertGreater(sum(char in "━╸=─-" for char in swept), 1)

    def crossed(self):
        self.words, self.tasks = {"fix-api": "working"}, {"fix-api": (4, 4)}
        # what got done, on the line its row opens, may hold the line's glyphs too
        waits, at = self.run_menu([None] * 3 + [self.news(lambda: (
            self.words.update({"fix-api": "done"}), self.reasons.update({"fix-api": "redrew ━"})))])
        screen, cells = self.written(waits, at)
        lines = [terminal.ANSI.sub("", line)
                 for line in screen.partition("\033[H")[2].rpartition("\033[J")[0].split("\n")]
        row = next(n for n, line in enumerate(lines, 1) if "fix-api" in line)
        self.assert_on_glow(cells, row)     # the `✓`, and the light where it crosses the row
        row += "━" not in lines[row - 1]
        start = row, terminal.cells(lines[row - 1][:lines[row - 1].index("━")]) + 1
        light = terminal.faded("done", -motion.BRIGHTER)
        light = tuple(int(light[n:n + 2], 16) for n in (1, 3, 5))
        first = {}
        for when, (row, column), text in cells:
            if row == start[0] and column >= start[1] and painted(text)[0][1] == light:
                first.setdefault(column, when)
        # one light, from the line's start toward its end: each frame lights the cell the light
        # has reached, so a frame passes cells by, a slow first one those at the start too
        self.assertGreaterEqual(len(first), 2, first)
        self.assertEqual(sorted(first), sorted(first, key=first.get))
        self.assertLessEqual(3 * (min(first) - start[1]), max(first) - start[1], first)

    def test_a_line_glides_to_its_new_length_with_a_light_at_its_head(self):
        self.words, self.tasks = {"fix-api": "working"}, {"fix-api": (1, 4)}
        waits, at = self.run_menu([None, self.news(
            lambda: self.tasks.update({"fix-api": (4, 4)}))])
        screen, cells = self.written(waits, at)
        self.assertIn("4 of 4", terminal.ANSI.sub("", screen))     # the draw says it at once
        start = self.cell(screen, "fix-api", "━")
        light = terminal.faded("working", -motion.BRIGHTER)
        light = tuple(int(light[n:n + 2], 16) for n in (1, 3, 5))
        heads = [(when, column) for when, (row, column), text in cells
                 if row == start[0] and painted(text)[0][1] == light]
        # the head moves right, from a quarter of the line to its end, in about 700 ms
        self.assertGreater(len({column for _, column in heads}), 3, heads)
        self.assertEqual([column for _, column in heads], sorted(column for _, column in heads))
        self.assertTrue(0.4 <= heads[-1][0] - heads[0][0] <= 0.9, heads[-1][0] - heads[0][0])
        tip = self.cell(screen, "fix-api", "━ 4 of 4")
        self.assertLessEqual(heads[-1][1], tip[1])

    def test_a_line_whose_plan_grows_glides_back_from_its_old_length(self):
        line = terminal.cell_texts(terminal.plan_bar(1, 4, room=15).split(" 1 of 4")[0])
        frames, until = motion.growing(line, 10, motion.GLIDE, 6, "working")
        lengths = [sum(terminal.plain(frame(when)) == "━" for frame in frames)
                   for when in (10, 10 + motion.GLIDE / 2, until)]
        self.assertEqual(lengths, [6, 4, 2])

    def test_a_shrinking_line_keeps_its_half_cell_at_the_head(self):
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        line = terminal.cell_texts(terminal.plan_bar(1, 3, room=15).split(" 1 of 3")[0])
        frames, until = motion.growing(line, 10, motion.GLIDE, 6, "working")
        snapshots = ["".join(terminal.plain(frame(10 + step / 20)) for frame in frames)
                     for step in range(15)]
        self.assertEqual(snapshots[0], "━━━━━━──")
        for text in snapshots:
            self.assertRegex(text, r"^━*╸?─*$")
        self.assertEqual(snapshots[-2], "━━╸─────")
        self.assertEqual([frame(until) for frame in frames], line)

    def test_nothing_is_replayed_on_opening_after_another_screen_a_notice_or_a_resize(self):
        self.words = {"fix-api": "done", "web-portal": "needs you"}

        def away(*args, **kwargs):          # while `c` is up, a seat turns and the usage moves
            self.words["fix-api"] = "needs you"
            self.cache(used=70)
            self.live.read()

        def resized():                      # a resize, and news with it
            self.words["web-portal"] = "done"
            self.cache(used=90)
            terminal._ASKED = True

        def noticed(messages):              # while a notice is up, a seat turns again
            self.words["fix-api"] = "done"
            self.cache(used=50)
            self.live.read()

        with patch.object(menu, "show_config", side_effect=away), \
                patch.object(menu, "show_notices", side_effect=noticed):
            waits, _ = self.run_menu([Key("char", "c"), self.news(resized), None, self.news(
                lambda: self.notices.append("fix-api finished")), None])
        drawn = [n for n, (_, _, text) in enumerate(waits) if text.startswith("\033[H")]
        screens = [terminal.ANSI.sub("", waits[n][2]) for n in drawn]
        # opened, back from `c`, resized, a wait, back from the notice, a wait
        self.assertEqual(len(screens), 6, screens)
        self.assertIn("! needs you", screens[1].split("fix-api")[1].split("\n")[0])
        self.assertIn("10% left", screens[2])
        self.assertIn("✓ done", screens[4].split("fix-api")[1].split("\n")[0])
        self.assertIn("50% left", screens[4])
        for timeout, _, text in waits:
            self.assertNotRegex(text, r"\x1b\[\d+;\d+H")  # no cell ever written on its own
            self.assertGreater(timeout, motion.FRAME)       # and no wait for a frame
        # and a menu opened again draws what it finds, as it is
        self.words["fix-api"] = "done"
        self.cache(used=20)
        waits, _ = self.run_menu([])
        self.assertEqual(len(waits), 1)
        self.assertNotRegex(waits[0][2], r"\x1b\[\d+;\d+H")

    def test_under_no_color_news_is_drawn_still(self):
        self.words = {"fix-api": "working"}
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            waits, _ = self.run_menu([self.news(
                lambda: self.words.update({"fix-api": "needs you"}))])
        self.assertIn("! needs you", terminal.ANSI.sub("", waits[-1][2]))
        for timeout, _, text in waits:
            self.assertNotRegex(text, r"\x1b\[\d+;\d+H")
            self.assertEqual(timeout, menu.TICK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
