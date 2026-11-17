"""A card that asks comes up as a page does, in a page's time (motion.FADE), on its screen's clock,
and a key is answered as it is read: an arrow draws it at rest, a click answers it as drawn.  On a
true-colour terminal and a clock moving only as the waits run (tests/test_breathing.py): `x` over
a working seat, the count of its runs landing as the test says, and a subscription's removal."""

from contextlib import redirect_stdout
import io
import os
import re
import threading
import unittest
from unittest.mock import patch

import test_breathing
from agentkit import menu, motion, terminal

Key = terminal.Key
QUESTION = menu.STOP_ASK.format("fix-api")


def light(kind):
    return sum(bytes.fromhex(terminal.colour(kind)))


def ink(written, word):
    """How light `word` shows where `written` last writes it: the foreground the codes before it
    on its row leave, the theme's text colour where they leave none."""
    at, rgb = written.rindex(word), None
    start = max([0, *(place.end() for place in re.finditer(r"\n|\x1b\[[\d;]*H", written[:at]))])
    for code in re.finditer(r"\x1b\[([\d;]*)m", written[start:at]):
        parts = [int(part or 0) for part in code[1].split(";")]
        while parts:
            first = parts.pop(0)
            if first in (38, 48) and parts[:1] == [2]:          # a background goes by
                rgb, parts = (parts[1:4] if first == 38 else rgb), parts[4:]
            elif first in (0, 39):
                rgb = None
    return sum(rgb) if rgb else light("text")


def row(written, word):
    """The row, from 1, `written` last writes `word` on."""
    at = written.rindex(word)
    place = list(re.finditer(r"\x1b\[(?:(\d+);\d+)?H", written[:at]))[-1]
    return int(place[1] or 1) + written.count("\n", place.end(), at)


def answering(sleep, script, at, news):
    """Each wait answered from `script`: None one run to its frame, a key typed half way to it, a
    word a click on it where the screen up shows it; `news()` as the `at`-th is read."""
    script = iter(enumerate(script))

    def answer(timeout):
        n, key = next(script)
        sleep((timeout or 0) / (1 if key is None else 2))
        if n == at:
            news()
        if key and isinstance(key, str):
            lines = [terminal.ANSI.sub("", line) for line in terminal.on_screen()]
            found = next(place for place, line in enumerate(lines) if key in line)
            return Key("click", "", lines[found].index(key) + 1, found + 1)
        return key
    return answer


class ComingUp(test_breathing.MainScreen):
    def setUp(self):
        super().setUp()
        # a width where the count landing takes a line off the card
        self.cols = next(width for width in range(60, 121) if len(terminal.wrap(
            menu.stop_means(None), width - 2)) > len(terminal.wrap(menu.stop_means(3), width - 2)))
        self.counting, self.counted, self.stopped = [], threading.Event(), []

        def seat_runs(name):                # counted off the draw: it lands when the test says
            self.counting.append(threading.current_thread())
            self.counted.wait()
            return ["one", "two", "three"]

        def join(fetch, timeout=None):      # the count waited on until it is being counted
            while fetch.is_alive() and fetch not in self.counting:
                threading.Thread.join(fetch, 0.01)
        for target, name, fake in ((terminal, "width", lambda *args: self.cols),
                                   (menu.transitions, "seat_runs", seat_runs),
                                   (menu.Fetch, "join", join),
                                   (menu, "stop_behind", lambda *seat: self.stopped.append(seat))):
            self.stack.enter_context(patch.object(target, name, fake))
        self.addCleanup(self.counted.set)   # a count still waiting ends with the test

    def land(self):
        self.counted.set()
        for thread in self.counting:        # landed: past the patched Fetch.join
            threading.Thread.join(thread)

    def ask(self, *keys, lands=0):
        """`x` over fix-api, `keys` and Esc, the count landing as the `lands`-th is read: each
        wait (run_menu), and the card's first."""
        waits = self.run_menu(answering(self.sleep, [Key("char", "x"), *keys, Key("esc"), ""],
                                        lands + 1, self.land), "fix-api")
        return waits, next(n for n, (_, _, written) in enumerate(waits)
                           if QUESTION in terminal.ANSI.sub("", written))

    def test_the_card_comes_up_on_the_main_screens_clock(self):
        waits, asked = self.ask(*[None] * 8)
        up = [n for n, (_, _, written) in enumerate(waits) if "✓ Keep" in written]
        self.assertEqual(up, list(range(asked, up[-1] + 1)))         # a write each frame
        keep, stop = ([ink(waits[n][2], word) for n in up] for word in ("✓ Keep", "× Stop"))
        # out of the background to its colours 0.15 s on, never darker frame to frame
        back = light("background")
        self.assertEqual((keep[0], stop[0], keep[-1], stop[-1]),
                         (back, back, light("text"), light("amber")))
        self.assertEqual((keep, stop), (sorted(keep), sorted(stop)))
        self.assertAlmostEqual(waits[up[-1]][1] - waits[asked][1], motion.FADE)
        # the count lands a frame after it opens, taking a line off the card: the answers a line
        # nearer the question, still at the clock's phase, the frames after it writing them there
        landed = asked + 1
        self.assertAlmostEqual(waits[landed][1] - waits[asked][1], motion.FRAME)
        self.assertEqual([menu.stop_means(None)[:13] in terminal.ANSI.sub("", waits[n][2])
                          for n in (asked, landed)], [True, False])      # "Its runs stop"
        under = [row(waits[n][2], "✓ Keep") - row(waits[n][2], QUESTION) for n in (asked, landed)]
        self.assertEqual(under[1], under[0] - 1)
        self.assertTrue(back < keep[1] < keep[-1] and back < stop[1] < stop[-1])
        self.assertEqual({row(waits[n][2], "✓ Keep") for n in up[1:]},
                         {row(waits[landed][2], "✓ Keep")})
        # the seat's dot breathes through it, in one phase, and alone once it is up
        for n in up[2:]:
            found = test_breathing.DOT.findall(waits[n][2])
            self.assertEqual({(int(r), int(c)) for r, c, *_ in found}, self.dots(waits[landed][2]))
            self.assertEqual(len({dot[2:] for dot in found}), 1)
        self.assert_breathing(waits[landed][2], waits[up[-1] + 1:-1])

    def test_down_half_way_up_draws_the_card_at_rest(self):
        waits, asked = self.ask(None, Key("down"), None)
        pressed = asked + 2                 # what the key drew
        self.assertAlmostEqual(waits[pressed][1] - waits[asked][1], motion.FADE / 2)
        self.assertLess(ink(waits[pressed - 1][2], "✓ Keep"), light("text"))
        self.assertEqual([ink(waits[pressed][2], word) for word in ("✓ Keep", "× Stop")],
                         [light("text"), light("amber")])

    def test_a_click_on_keep_half_way_up_keeps_whatever_moves_the_card_as_it_is_read(self):
        # the count landing takes a line off the card: `× Stop` comes up onto the row clicked
        waits, asked = self.ask(None, "✓ Keep", lands=1)
        self.assertAlmostEqual(waits[asked + 2][1] - waits[asked][1], motion.FADE / 2)
        self.assertNotIn("✓ Keep", waits[asked + 2][2])               # closed
        self.assertEqual(self.stopped, [])
        # and so does the terminal widening, on the card removing a subscription
        means = menu.REMOVE_SUBSCRIPTION_ASK[1]
        self.cols = next(width for width in range(60, 121) if len(terminal.wrap(
            means, width - 2)) > len(terminal.wrap(means, 118)))       # widened, a line less
        # its providers alone: a removal goes no further than its save, never signing anything out
        cfg = {"providers": {"anthropic": {"accounts": ["default", "b2"]}}}
        out = io.StringIO()
        out.isatty = lambda: True
        answer = answering(self.sleep, [None, "✓ Keep"], 1, lambda: setattr(self, "cols", 120))
        with patch.object(menu, "wait_key", lambda prompt, timeout=None, wake=None:
                          answer(timeout)), redirect_stdout(out):
            said = menu.config_remove_provider(cfg, ("anthropic", "b2", "Claude II"))
        self.assertEqual((said, cfg["providers"]["anthropic"]["accounts"]), ("", ["default", "b2"]))

    def test_under_no_color_or_on_a_screen_that_scrolls_no_frame_follows_the_cards(self):
        for still in (patch.dict(os.environ, {"NO_COLOR": "1"}),
                      patch.object(terminal, "height", return_value=8)):   # taller: it scrolls
            with self.subTest(still), still:
                waits, asked = self.ask(*[None] * 4)
                for _, _, written in waits[asked:-1]:      # Esc read last
                    self.assertNotRegex(written.rpartition("\033[J")[2], r"\x1b\[\d+;\d+H")
        self.assertEqual([ink(waits[asked][2], word) for word in ("✓ Keep", "× Stop")],
                         [light("text"), light("amber")])       # on 8 rows, at rest at once


if __name__ == "__main__":
    unittest.main(verbosity=2)
