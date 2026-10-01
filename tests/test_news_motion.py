"""A change on the main screen announces itself once, then is still.

`menu.loop` on a scripted wait over a true-colour terminal, news landing the way `Live` brings
it -- the seats read again and a byte on the wake pipe: a seat turning `needs you` pulses its `!`
twice toward the light over 600 ms and is still in its colour; one turning `done` has its `✓`
settle from bright to its colour over 400 ms; a usage bar that moves glides to its new value in
eighths of a cell over 300 ms, a frame writing only the cells that moved, and ends on exactly the
bar the draw wrote; a task bar filling up lights its new blocks and then sends one light across
it, left to right, once -- and so does a bar that was drawn full already, its value reaching
full.  The first draw, one after another screen, a notice or a resize, and a menu opened again
draw what they find as it is, and nothing moves under NO_COLOR.  Offline, in a throwaway HOME:
the probe is never started, the reads are the test's own and the keyboard is a stand-in.
"""

import io
import json
import os
import re
import select
import time
from unittest.mock import patch
import unittest

from test_v4n import Sandbox, menu_input
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


def brightened(kind):
    """`kind`'s colour as news lights it: (r, g, b)."""
    light = terminal.faded(kind, -motion.BRIGHTER)
    return tuple(int(light[i:i + 2], 16) for i in (1, 3, 5))


LIT = brightened("working")         # a plain bar's light


def filled(bar):
    """How full a bar is, in cells, its partial block counted in eighths."""
    return sum(1 if char == "█" else (motion.PARTS.index(char) + 1) / 8
               for char, _ in bar if char == "█" or char in motion.PARTS)


def lit(bar, light=LIT):
    """The cells of a bar lit by news, `light` a coloured bar's own."""
    return {n for n, (_, colour) in enumerate(bar) if colour == light}


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
        self.words, self.tasks, self.notices, self.live = {}, {}, [], None
        self.cache(used=20)

        def row_state(cfg, session, look=True, **facts):
            return {"word": self.words[session["name"]], "reason": "", "since": None}

        def watch(live, last):              # read once, now, and again only when news says so
            self.live, live.last = live, last
            live.read()

        for target, name, fake in (
                (orch, "listing", lambda: [{"name": name, "repo": str(repo), "path": str(repo),
                                            "created": 0} for name in self.words]),
                (menu, "run_records", list),
                (menu, "seat_row_state", row_state),
                (menu, "seat_progress", lambda name: self.tasks.get(name, (0, 0))),
                (menu, "seat_estimate", lambda *args, **kwargs: None),
                (orch, "job_notices", lambda: [self.notices.pop()] if self.notices else []),
                (menu.Live, "probe", lambda self, now=None: False),
                (menu.Live, "watch", watch),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),     # a taken keyboard's, no real terminal's
                (terminal, "width", lambda *args: 100)):
            self.stack.enter_context(patch.object(target, name, fake))
        self.addCleanup(setattr, terminal, "_ASKED", False)

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
            waits.append((timeout, time.monotonic(), out.getvalue()))
            out.seek(0)
            out.truncate()
            if wake is not None and select.select([wake], [], [], 0)[0]:
                return None
            if not steps:
                last.setdefault("at", (len(waits) - 1, time.monotonic()))
                if timeout > motion.FRAME or time.monotonic() - last["at"][1] > after:
                    return ""
                time.sleep(timeout)
                return None
            step = steps.pop(0)
            if callable(step):
                step()
                return None
            if step is None:
                time.sleep(min(timeout, motion.FRAME))
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

    def bar(self, cells, start, size):
        """The bar of `size` cells from `start`, as each frame left it: (when, a (block, colour)
        a cell).  The draw's own frame writes every cell; each frame after it only cells that
        changed."""
        (row, column), frames = start, []
        for when, (at_row, at_column), text in cells:
            if at_row != row or not column <= at_column < column + size:
                continue
            [block] = painted(text)
            if not frames or frames[-1][0] != when:
                frames.append((when, dict(frames[-1][1]) if frames else {}))
            if len(frames) > 1:
                self.assertNotEqual(frames[-1][1].get(at_column), block, "a cell that did not move")
            frames[-1][1][at_column] = block
        self.assertEqual(len(frames[0][1]), size)
        return [(when, [state[column + n] for n in range(size)]) for when, state in frames]

    def cell(self, screen, name, text):
        """Where `text` starts on `name`'s row of a drawn screen: its row and its column."""
        lines = screen.partition("\033[H")[2].rpartition("\033[J")[0].split("\n")
        for row, line in enumerate((terminal.ANSI.sub("", line) for line in lines), 1):
            if name in line and text in line:
                return row, terminal.cells(line[:line.index(text)]) + 1
        self.fail(f"no {text!r} on {name}'s row:\n{screen}")

    def assert_still(self, waits):
        """Nothing moves now: the menu was left on a wait longer than a frame."""
        self.assertGreater(waits[-1][0], motion.FRAME)

    def test_a_seat_turning_needs_you_pulses_twice_then_is_still(self):
        self.words = {"fix-api": "working", "web-portal": "done"}
        waits, at = self.run_menu([None] * 3 + [self.news(
            lambda: self.words.update({"fix-api": "needs you"}))])
        screen, cells = self.written(waits, at)
        mark = self.cell(screen, "fix-api", "! needs you")
        self.assertEqual({cell for _, cell, _ in cells}, {mark})    # the `!`, and nothing else
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
        self.assertEqual({cell for _, cell, _ in cells}, {tick})    # web-portal's `!` is old news
        shades = [colour for _, _, text in cells for char, colour in painted(text)]
        light = [sum(colour) for colour in shades]
        # bright the moment it appears, then easing down to `done`'s colour and no further
        self.assertGreater(light[0], sum(DONE) + 60)
        self.assertEqual(light, sorted(light, reverse=True))
        self.assertEqual(shades[-1], DONE)
        self.assertTrue(0.35 <= cells[-1][0] - cells[0][0] <= 0.7, cells[-1][0] - cells[0][0])
        self.assert_still(waits)

    def test_a_usage_bar_glides_to_its_new_value_and_ends_on_it_exactly(self):
        self.words = {"web-portal": "done"}
        waits, at = self.run_menu([None, self.news(lambda: self.cache(used=70))])
        screen, cells = self.written(waits, at)
        self.assertIn("30% left", terminal.ANSI.sub("", screen))     # the words say it at once
        (row, column) = start = self.cell(screen, "Claude", "█")
        self.assertEqual({cell for _, cell, _ in cells}, {(row, column + n) for n in range(12)})
        frames = self.bar(cells, start, 12)
        # 80% left was ten cells of twelve, 30% is four: it glides down from the one to the
        # other through the eighths
        full = [filled(bar) for _, bar in frames]
        self.assertEqual(full, sorted(full, reverse=True))
        self.assertEqual(full[0], 10)
        self.assertEqual(full[-1], 4)
        self.assertGreater(len({value % 1 for value in full}), 2, full)
        # and its last frame is the bar the draw wrote, cell for cell
        drawn = painted(next(line for line in screen.split("\n") if "Claude" in line))
        self.assertEqual(frames[-1][1], drawn[column - 1:column + 11])
        self.assertEqual("".join(block for block, _ in frames[-1][1]), "████░░░░░░░░")
        self.assertTrue(0.25 <= frames[-1][0] - frames[0][0] <= 0.6, frames[-1][0] - frames[0][0])
        self.assert_still(waits)

    def assert_swept(self, frames, size, light=LIT):
        """One light crosses the bar left to right, once, after anything else lit on it: from the
        last frame lit in more than one cell on, each frame lights one cell at most, never one
        left of the one before; and the bar ends unlit."""
        lights = [lit(bar, light) for _, bar in frames]
        after = max((n for n, cells in enumerate(lights) if len(cells) > 1), default=-1) + 1
        sweep = [min(cells) for cells in lights[after:] if cells]
        self.assertTrue(all(len(cells) <= 1 for cells in lights[after:]), lights)
        self.assertEqual(sweep, sorted(sweep), lights)
        self.assertLessEqual(sweep[0], 2, lights)
        self.assertGreaterEqual(sweep[-1], size - 3, lights)
        self.assertEqual(lights[-1], set())

    def test_a_task_bar_filling_up_lights_its_new_blocks_and_sweeps_once(self):
        self.words, self.tasks = {"fix-api": "working"}, {"fix-api": (1, 4)}
        waits, at = self.run_menu([None, self.news(
            lambda: self.tasks.update({"fix-api": (4, 4)}))])
        screen, cells = self.written(waits, at)
        start = self.cell(screen, "fix-api", "████████ 4/4")
        dot = self.cell(screen, "fix-api", "●")
        frames = self.bar(cells, start, 8)
        # two cells of eight become eight: the six new ones light as it glides over them...
        self.assertTrue(any(len(lit(bar)) > 1 and lit(bar) <= set(range(2, 8))
                            for _, bar in frames), [lit(bar) for _, bar in frames])
        # ...and then one light crosses the whole full bar, left to right, once
        self.assert_swept(frames, 8)
        self.assertEqual("".join(block for block, _ in frames[-1][1]), "████████")
        self.assertEqual({colour for _, colour in frames[-1][1]}, {None})   # plain, as drawn
        # still after it: no more writes to it, while the dot breathes on
        ended = frames[-1][0]
        self.assertTrue(0.6 <= ended - cells[0][0] <= 1.0, ended - cells[0][0])
        self.assertTrue(any(when > ended + 0.2 for when, cell, _ in cells if cell == dot))

    def test_a_bar_drawn_full_already_sweeps_when_its_value_reaches_full(self):
        # 19/20 and 99% left both round to a full bar: the value, not the blocks, is the news
        self.words, self.tasks = {"fix-api": "working"}, {"fix-api": (19, 20)}
        self.cache(used=1)

        def full():
            self.tasks["fix-api"] = (20, 20)
            self.cache(used=0)
        waits, at = self.run_menu([None, self.news(full)])
        screen, cells = self.written(waits, at)
        claude = brightened(menu.colour(self.cfg, "anthropic"))      # its company's, lit
        for name, text, size, light in (("fix-api", "████████ 20/20", 8, LIT),
                                         ("Claude", "█", 12, claude)):
            with self.subTest(name):
                frames = self.bar(cells, self.cell(screen, name, text), size)
                self.assertEqual({filled(bar) for _, bar in frames}, {size})   # nothing glides
                self.assert_swept(frames, size, light)

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
