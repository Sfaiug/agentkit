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
        # out of what it is on, `Keep` the highlight and `Stop` the background, to its colours
        # 0.15 s on, never darker frame to frame
        self.assertEqual((keep[0], stop[0], keep[-1], stop[-1]),
                         (light("selection"), light("background"), light("text"), light("amber")))
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
        self.assertTrue(keep[0] < keep[1] < keep[-1] and stop[0] < stop[1] < stop[-1])
        self.assertEqual({row(waits[n][2], "✓ Keep") for n in up[1:]},
                         {row(waits[landed][2], "✓ Keep")})
        # the seat's dot breathes through it, in one phase, and alone once it is up
        for n in up[2:]:
            found = test_breathing.DOT.findall(waits[n][2])
            self.assertEqual({(int(r), int(c)) for r, c, *_ in found}, self.dots(waits[landed][2]))
            self.assertEqual(len({dot[2:] for dot in found}), 1)
        self.assert_breathing(waits[landed][2], waits[up[-1] + 1:-1])

    def remove(self, *script, at=-1, news=None):
        """`− remove` under Claude II, the card's waits answered from `script` (`answering`) and
        none removed: each wait's timeout, when it was asked, and what was written before it."""
        # its providers alone: a removal goes no further than its save, never signing anything out
        cfg = {"providers": {"anthropic": {"accounts": ["default", "b2"]}}}
        out, waits, answer = io.StringIO(), [], answering(self.sleep, script, at, news)
        out.isatty = lambda: True

        def wait_key(prompt, timeout=None, wake=None):
            waits.append((timeout, self.now, out.getvalue()))
            out.seek(0)
            out.truncate()
            return answer(timeout)
        with patch.object(menu, "wait_key", wait_key), redirect_stdout(out), \
                patch.object(terminal, "_TAKEN", test_breathing.Keyboard()):
            said = menu.config_remove_provider(cfg, ("anthropic", "b2", "Claude II"))
        self.assertEqual((said, cfg["providers"]["anthropic"]["accounts"]), ("", ["default", "b2"]))
        return waits

    def test_down_half_way_up_draws_the_card_at_rest_and_esc_after_it_no_more(self):
        waits, asked = self.ask(None, Key("down"))
        pressed = asked + 2                 # what the key drew
        self.assertAlmostEqual(waits[pressed][1] - waits[asked][1], motion.FADE / 2)
        self.assertLess(ink(waits[pressed - 1][2], "✓ Keep"), light("text"))
        self.assertEqual([ink(waits[pressed][2], word) for word in ("✓ Keep", "× Stop")],
                         [light("text"), light("amber")])
        self.assertNotIn("✓ Keep", waits[pressed + 1][2])    # Esc, the highlight still moving
        # Down again as the highlight still lands on `× Remove`, the last: it is there, at rest
        waits = self.remove(None, Key("down"), Key("down"), Key("esc"))
        self.assertIsNone(waits[-1][0])

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
        waits = self.remove(None, "✓ Keep", at=1, news=lambda: setattr(self, "cols", 120))
        self.assertAlmostEqual(waits[1][1] - waits[0][1], motion.FRAME)     # read at FADE / 2,
        self.assertLess(ink(waits[1][2], "✓ Keep"), light("text"))          # the card coming up

    def test_where_nothing_moves_the_card_is_up_at_once_and_waits_for_a_key_alone(self):
        rows = []
        for still in (patch.dict(os.environ, {"NO_COLOR": "1"}),
                      patch.object(terminal, "height", side_effect=lambda: rows[0])):  # it scrolls
            with self.subTest(still), still:
                rows[:] = [8]
                waits, asked = self.ask(*[None] * 4)
                # the terminal grown as the first is read: drawn again where it can move, up
                removing = self.remove(None, Key("esc"), at=0, news=lambda: rows.__setitem__(0, 24))
                self.assertEqual([timeout for timeout, _, _ in removing], [None, None])
                for _, _, written in waits[asked:-1] + removing:      # Esc read last
                    self.assertNotRegex(written.rpartition("\033[J")[2], r"\x1b\[\d+;\d+H")
        self.assertEqual([ink(waits[asked][2], word) for word in ("✓ Keep", "× Stop")],
                         [light("text"), light("amber")])       # on 8 rows, at rest at once
        # a page's, as `c`'s whose `a` asks: drawn first where nothing moves, it is up, and stays
        # up drawn again where it can
        page = motion.Clock(page=True)
        with patch.object(motion, "movable", side_effect=[False, True]):
            self.assertEqual([page.rise(["acme"]) for _ in "up"], [False, False])

    def test_where_nothing_moves_a_card_its_count_still_pending_is_drawn_once(self):
        frames = [None] * (int(menu.TICK / motion.FRAME) + 1)      # past the whole screen's TICK
        with patch.object(terminal, "height", return_value=8):     # it scrolls: nothing moves
            waits, _ = self.ask(*frames, lands=len(frames) + 1)    # once the menu is left
        self.assertEqual(sum(QUESTION in terminal.ANSI.sub("", written)
                             for _, _, written in waits), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
