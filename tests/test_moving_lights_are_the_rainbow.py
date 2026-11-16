"""A light that moves is the theme's rainbow (the owner, 12 Nov 2026): at the head of a line that
glides, round a working line with no plan, across a line just done, along the rule of a screen
that waits and through an effort stepped to its highest, six cells, each its own glyph, in the
theme's error, warning, success, info, accent and special from its head back -- as many as a
word has where it is shorter -- every other cell as drawn.  The ak screen, `c` and a screen's
wait on a clock of their own, as tests/test_news_motion.py drives them, each frame played onto a
screen of the test's own, on a true-colour terminal that sets no background and a white one.
"""

import re
import threading
import unittest
from unittest.mock import patch

from test_news_motion import Keyboard, Menu
from agentkit import config, menu, motion, orch, terminal, update, usage

Key = terminal.Key
# from the head back: a terminal that sets no background has the black theme, a white one white
RAINBOWS = {terminal.BLACK: ("fe756f", "d79200", "33b65f", "00b0bf", "4da3ff", "da7de0"),
            terminal.WHITE: ("c52a2f", "8e5e00", "007935", "00747d", "0067c6", "a23baa")}
TOKENS = re.compile(r"\x1b\[\??([\d;]*)([A-Za-z])|\x1b\][^\x07]*\x07|(.)", re.S)
CATALOG = {"claude-haiku-4-5": ["none"],
           "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"]}


def played(waits):
    """At each of `run_menu`'s waits, (when, the screen, the screen as its last whole draw left
    it), a screen {(row, column): (glyph, its colour as `rrggbb`, or None)}."""
    cells, drawn, row, column, ink, frames = {}, {}, 1, 1, None, []
    for _, now, text in waits:
        for args, final, char in TOKENS.findall(text):
            if char in ("\r", "\n"):
                row, column = row + (char == "\n"), 1
            elif char:
                if terminal.cells(char) > 1:    # a glyph two cells wide covers the next one too
                    cells.pop((row, column + 1), None)
                cells[row, column] = char, ink
                column += terminal.cells(char)
            elif final == "H":
                row, column = map(int, args.split(";")) if args else (1, 1)
            elif final in "JK":     # cleared to the screen's end, after a whole draw, or the line's
                cells = {at: cell for at, cell in cells.items()
                         if at < (row, column) or final == "K" and at[0] > row}
                drawn = dict(cells) if final == "J" else drawn
            elif final == "m":
                codes = args.split(";")
                while codes:
                    code = codes.pop(0)
                    if code in ("38", "48"):        # in 24 bits
                        ink = bytes(map(int, codes[1:4])).hex() if code == "38" else ink
                        codes = codes[4:]
                    elif code in ("", "0", "39"):
                        ink = None
        frames.append((now, dict(cells), drawn))
    return frames


class Lights(Menu):
    def setUp(self):
        super().setUp()

        def switched(cfg, name, model, providers=None, effort=None, **_kw):
            """The seat's orchestrator moved, at `effort`, with no harness asked."""
            config.update_session(name, orchestrator=model)
            config.change_efforts(name, lambda data: config.orchestrating_at(
                cfg["models"], data, model, effort))
            return ""
        for target, name, fake in (
                # `c`'s catalog however read, build, meters and seat, none asked of a harness
                *((config, read, lambda harness, cfg=None: [
                    {"id": model, "label": config.model_label(harness, model), "efforts": efforts}
                    for model, efforts in CATALOG.items() if harness == "claude"])
                  for read in ("catalog", "catalog_now", "catalog_held")),
                (update, "agentkit_version", lambda: "2816 · 2026-09-29"),
                (usage, "collect", lambda cfg, **kwargs: usage.Readings({})),
                (orch, "switch_orchestrator", switched)):
            self.stack.enter_context(patch.object(target, name, fake))

    def frames(self, script, after=1.2, screen=None):
        """`run_menu`'s frames (`played`), and those from the first after `script`; a `screen`
        on a keyboard taken."""
        with patch.object(terminal, "taken", return_value=screen is not None):
            waits, at = self.run_menu(script, after, screen)
        frames = played(waits)
        return frames, frames[at:]

    def terminals(self, check):
        """`check(rainbow)` on each terminal, a subtest, from the clock's 1000th second."""
        for theme, rainbow in RAINBOWS.items():
            self.now = 1000.0
            with self.subTest(theme=theme), patch.object(terminal, "THEME", theme):
                check(rainbow)

    def at(self, frames, moment):
        """The frame nearest `moment`."""
        return min(frames, key=lambda frame: abs(frame[0] - moment))

    def cells(self, screen, beside, run="[━╸─]+"):
        """The cells of the first `run` on the row of `screen` that holds `beside`, a glyph each."""
        for row in sorted({row for row, _ in screen}):
            columns = sorted(column for at, column in screen if at == row)
            text = "".join(screen[row, column][0] for column in columns)
            if beside in text:
                return [(row, columns[n]) for n in range(*re.search(run, text).span())]
        self.fail(f"no row holds {beside!r}")

    def assert_light(self, frames, moment, cells, rainbow):
        """At `moment` the light on `cells`: six neighbours, or as many as they are, each its own
        glyph, in `rainbow` from its head back, every other cell as drawn; and no cell of them at
        any frame in a colour but as drawn or one of `rainbow`."""
        _, screen, drawn = self.at(frames, moment)
        head = next(n + rainbow.index(screen[cell][1]) for n, cell in enumerate(cells)
                    if screen[cell] != drawn[cell])
        self.assertEqual(sum(0 <= head - n < 6 for n in range(len(cells))), min(6, len(cells)))
        self.assertEqual([screen[cell] for cell in cells],
                         [(drawn[cell][0], rainbow[head - n]) if 0 <= head - n < 6 else drawn[cell]
                          for n, cell in enumerate(cells)])
        for when, screen, drawn in frames:
            for cell in cells:
                self.assertIn(screen[cell][1], [drawn[cell][1], *rainbow], when)
                self.assertEqual(screen[cell][0], drawn[cell][0], when)

    def test_a_working_line_with_no_plan_holds_the_rainbow_half_a_round_on(self):
        def check(rainbow):
            self.words, self.tasks = {"fix-api": "working"}, {}
            frames, _ = self.frames([], after=motion.ROUND)
            # the light's place is the clock's, round from each ROUND seconds
            self.assert_light(frames, 1000 + motion.ROUND / 2,
                              self.cells(frames[-1][2], " fix-api "), rainbow)
        self.terminals(check)

    def test_a_line_gliding_has_the_rainbow_at_its_head(self):
        def check(rainbow):
            self.words, self.tasks = {"fix-api": "working"}, {"fix-api": (4, 12)}
            frames, moved = self.frames([None, self.news(
                lambda: self.tasks.update({"fix-api": (10, 12)}))], after=2.2)
            since, line = moved[0][0], self.cells(frames[-1][2], " fix-api ")
            for when, screen, _ in moved:
                done = [screen[cell][1] for cell in line if screen[cell][0] in "━╸"]
                if when < since + motion.GLIDE:     # the six to its head the light, the rest still
                    self.assertEqual(done, [rainbow[4]] * (len(done) - 6) + [*rainbow[::-1]],
                                     when)
            half = self.at(moved, since + motion.GLIDE / 2)[1]
            self.assertEqual(sum(half[cell][0] == "━" for cell in line),
                             round(len(line) * 7 / 12))     # half way from 4 of 12 to 10
            # at rest, as its tip breathes nearest its colour, its done part all the accent
            rest = self.at(moved, 1002.0)[1]
            self.assertEqual({rest[cell][1] for cell in line if rest[cell][0] in "━╸"},
                             {rainbow[4]})
        self.terminals(check)

    def test_a_line_just_done_is_crossed_by_the_rainbow(self):
        def check(rainbow):
            self.words, self.tasks = {"fix-api": "working"}, {"fix-api": (4, 4)}
            frames, moved = self.frames([None] * 3 + [self.news(
                lambda: self.words.update({"fix-api": "done"}))])
            line = self.cells(moved[0][2], " fix-api ")
            self.assert_light(moved, moved[0][0] + motion.SWEEP / 2, line, rainbow)
            # and after it, the whole line in done's colour
            self.assertEqual({frames[-1][1][cell] for cell in line}, {("━", rainbow[2])})
        self.terminals(check)

    def test_the_rule_of_a_screen_that_waits_holds_the_rainbow(self):
        def check(rainbow):
            held = threading.Event()
            self.addCleanup(held.set)

            def waits():
                with self.assertRaises(menu.Back):
                    menu.waited(held.wait, "config · models", lambda: ["  acme"])
            frames, _ = self.frames([], motion.WAIT + motion.LAP, waits)
            self.assert_light(frames, 1000 + motion.WAIT + motion.LAP / 2,
                              self.cells(frames[-1][2], "─" * 60), rainbow)
        self.terminals(check)

    def stepped(self, highest):
        """`frames` of Opus's effort on `c` stepped from xhigh to `highest`, and its cells."""
        config.save_session(self.cfg, "fix-api", "opus", ["astra"], {"cwd": "/", "created": 0})
        config.change_efforts("fix-api", lambda data: config.orchestrating_at(
            self.cfg["models"], data, "opus", "xhigh"))
        with patch.dict(CATALOG, {"claude-opus-5-5": ["low", "medium", "high", "xhigh", highest]}):
            frames, moved = self.frames([None] * 4 + [Key("down"), Key("right"), Key("space")],
                                        1, lambda: menu.show_config(False, Keyboard(), "fix-api"))
        return frames, moved, self.cells(moved[0][2], "Opus 5.5", highest)

    def test_an_effort_stepped_to_its_highest_sends_the_rainbow_through_its_word(self):
        def check(rainbow):
            frames, moved, word = self.stepped("max")
            self.assert_light(moved, moved[0][0] + motion.SHIMMER / 2, word, rainbow)
            self.assertEqual([frames[-1][1][cell] for cell in word],
                             [moved[0][2][cell] for cell in word])
        self.terminals(check)

    def test_the_light_through_a_word_of_wide_letters_is_six_of_its_cells(self):
        def check(rainbow):
            _, moved, word = self.stepped("最高努力")
            half = self.at(moved, moved[0][0] + motion.SHIMMER / 2)[1]
            self.assertEqual(sum(terminal.cells(half[cell][0]) for cell in word
                                 if half[cell][1] in rainbow), 6)
        self.terminals(check)


if __name__ == "__main__":
    unittest.main(verbosity=2)
