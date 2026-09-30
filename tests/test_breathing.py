"""A working session's dot breathes, every one in step, and nothing else on the screen moves.

`menu.loop` on a scripted wait over a true-colour terminal with two working seats and one that
needs you: between draws only the two working `●` are rewritten, each frame both in one colour,
the colour easing between `working`'s and a dimmer tone of it; at most twenty frames a second;
a key pressed mid-animation has its frame out within 100 ms; the dots breathe on through the
wait for a second digit and under the stop question, and a resize as a frame falls due draws
the whole screen instead.  From a pipe, under NO_COLOR and at eight colours the wait is the
plain TICK and no frame is drawn.  Offline, in a throwaway HOME: the probe is never started,
opening a seat is a line saying so, and the keyboard is a stand-in.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
import re
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, menu, motion, orch, terminal

Key = terminal.Key
TERMINAL = terminal.Keyboard       # the real one, for a stdin that is a pipe
WORKING = (0x89, 0xb4, 0xfa)       # `working` on a dark background
# one dot rewritten: its cell, its colour, and on the highlighted row the row's brightness too
DOT = re.compile(r"\x1b\[(\d+);(\d+)H(?:\x1b\[1m)?\x1b\[38;2;(\d+);(\d+);(\d+)m●"
                 r"\x1b\[0(?:;1m\x1b\[0)?m")
WORDS = {"fix-api": "working", "tidy-docs": "working", "web-portal": "needs you"}


class Keyboard:
    """A terminal the menu has taken, so keys are `terminal.Key`s and the screen is written over."""

    def take(self):
        return True

    def give(self):
        pass

    def close(self):
        pass


class Breathing(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop("NO_COLOR")
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color",
            "COLORTERM": "truecolor"}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)
        self.words = dict(WORDS)

        def row_state(cfg, session, look=True, **facts):
            return {"word": self.words[session["name"]], "reason": "", "since": None}

        for target, name, fake in (
                (orch, "listing", lambda: [{"name": name, "repo": str(repo), "path": str(repo),
                                            "created": 0} for name in self.words]),
                (menu, "run_records", list),
                (menu, "seat_row_state", row_state),
                (menu, "seat_progress", lambda name: (0, 0)),
                (orch, "job_notices", lambda: []),
                (menu.Live, "probe", lambda self, now=None: False),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),     # a taken keyboard's, no real terminal's
                (terminal, "width", lambda *args: 100),
                (menu, "open_session", lambda cfg, session, dry_run:
                 print(f"<opened {session['name']}>"))):
            self.stack.enter_context(patch.object(target, name, fake))
        self.addCleanup(setattr, terminal, "_ASKED", False)

    def run_menu(self, answer):
        """`menu.loop` with every wait answered by `answer(timeout)`; each wait's timeout, when it
        was asked, and what was written before it."""
        out, waits = io.StringIO(), []
        out.isatty = lambda: True           # a terminal, as far as colour is concerned

        def wait_key(prompt, timeout=None, wake=None):
            waits.append((timeout, time.monotonic(), out.getvalue()))
            out.seek(0)
            out.truncate()
            return answer(timeout)

        with patch.object(menu, "wait_key", side_effect=wait_key), \
                patch.object(menu, "read", return_value="q"), redirect_stdout(out):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        return waits

    def dots(self, screen):
        """Each working seat's `●` on a drawn screen: its row and its column, counted from 1."""
        lines = screen.partition("\033[H")[2].rpartition("\033[J")[0].split("\n")
        working = [name for name, word in self.words.items() if word == "working"]
        return {(row, text.index("●") + 1)
                for row, text in enumerate((terminal.ANSI.sub("", line) for line in lines), 1)
                if "●" in text and any(f" {name} " in text for name in working)}

    def assert_breathing(self, screen, waits):
        """Each wait no longer than a frame, and what was written before each a frame of the dots
        `screen` drew and nothing else, both dots in one colour; a frame at a turn of the breath,
        where the colour has not moved, writes nothing."""
        dots = self.dots(screen)
        self.assertEqual(len(dots), 2, screen)
        self.assertTrue(all(0 <= timeout <= motion.FRAME for timeout, _, _ in waits), waits)
        frames = [written for _, _, written in waits if written]
        self.assertTrue(frames)
        for written in frames:
            self.assertRegex(written, rf"^(?:{DOT.pattern})+$")
            found = DOT.findall(written)
            self.assertEqual({(int(r), int(c)) for r, c, *_ in found}, dots)
            self.assertEqual(len({dot[2:] for dot in found}), 1, written)   # in one phase

    def test_only_the_working_dots_move_and_they_move_together(self):
        calls = iter(range(40))

        def answer(timeout):
            if next(calls) == 39:
                return "q"
            time.sleep(timeout)             # nothing typed: the wait runs to its frame
            return None
        waits = self.run_menu(answer)
        screen, drawn = waits[0][2], [written for _, _, written in waits[1:]]
        dots = self.dots(screen)
        self.assertEqual(len(dots), 2, screen)
        # the draw itself paints the dots at the clock's phase, in its one write
        tail = screen.rpartition("\033[J")[2]
        self.assertEqual({(int(r), int(c)) for r, c, *_ in DOT.findall(tail)}, dots)
        colours = []
        for written in filter(None, drawn):     # a frame the colour did not move writes nothing
            # a frame is the working dots and nothing else: no other cell, no other row
            self.assertRegex(written, rf"^(?:{DOT.pattern})+$")
            found = DOT.findall(written)
            self.assertEqual({(int(r), int(c)) for r, c, *_ in found}, dots)
            self.assertEqual(len({dot[2:] for dot in found}), 1, written)   # in one phase
            colours.append(tuple(int(v) for v in found[0][2:]))
        self.assertGreater(len(set(colours)), 5)            # it moves, frame to frame
        for colour in colours:                              # between `working` and half of it
            for channel, full in zip(colour, WORKING):
                self.assertTrue(full // 2 <= channel <= full, colour)
        # at most twenty frames a second, each wait no longer than one frame
        self.assertTrue(all(0 <= timeout <= motion.FRAME for timeout, _, _ in waits))
        spent = waits[-1][1] - waits[1][1]
        self.assertLessEqual(len(drawn) - 1, spent * 20 + 1)
        # one breath, out to the dimmer tone and back, is two seconds
        self.assertEqual([motion.breath(at) for at in (0, 1, 2)], [0, 1, 0])

    def test_a_key_mid_animation_is_answered_within_100_ms(self):
        script = iter([None] * 5 + [Key("down"), Key("char", "q")])
        pressed = {}

        def answer(timeout):
            key = next(script)
            time.sleep(timeout if key is None else timeout / 2)   # typed half way to a frame
            if key is not None and key.name == "down":
                pressed["at"] = time.monotonic()
            return key
        waits = self.run_menu(answer)
        answered = next(at for _, at, _ in waits if at > pressed["at"])
        self.assertLess(answered - pressed["at"], 0.1)
        self.assertTrue(all(timeout <= motion.FRAME for timeout, _, _ in waits[1:]))
        # and the frame it answers with is the highlight moved: `›` on the first working seat
        screen = waits[-1][2]
        lit = [terminal.ANSI.sub("", line) for line in screen.split("\n") if "›" in line]
        self.assertIn(" fix-api ", lit[0])

    def test_the_second_digit_and_the_stop_question_wait_breathing(self):
        self.words.update({f"zz-{n}": "done" for n in range(7)})     # ten seats: `1` may be 1x
        script = iter([Key("char", "1"), *[None] * 4, "resize", *[None] * 10, Key("char", "x"),
                       *[None] * 6, Key("esc"), "q"])

        def answer(timeout):
            key = next(script)
            if key is None or key == "resize":
                time.sleep(timeout)          # nothing typed: the wait runs to its frame
            if key == "resize":
                terminal._ASKED = True       # what `read_key` leaves when a resize ended it
                return None
            return key
        waits = self.run_menu(answer)
        # `1` waits half a second for a second digit, the dots breathing, then opens seat 1; a
        # resize in that half second draws the list anew and the dots breathe on where it put them
        opened = next(n for n, (_, _, written) in enumerate(waits) if "<opened fix-api>" in written)
        redrawn = next(n for n in range(1, opened) if waits[n][2][:3] == "\033[H")
        self.assert_breathing(waits[0][2], waits[1:redrawn])
        self.assertGreater(opened - redrawn, 2)
        self.assert_breathing(waits[redrawn][2], waits[redrawn + 1:opened])
        # `x` asks under the highlighted seat, and the dots breathe where that screen put them
        asked = next(n for n, (_, _, written) in enumerate(waits)
                     if "Stop fix-api and everything it runs?" in terminal.ANSI.sub("", written))
        self.assertEqual(waits[asked + 7][2][:3], "\033[H")          # Esc kept it: the list
        self.assertNotEqual(self.dots(waits[asked][2]), self.dots(waits[0][2]))
        self.assert_breathing(waits[asked][2], waits[asked + 1:asked + 7])

    def test_a_resize_as_a_frame_falls_due_draws_the_whole_screen(self):
        script = iter([*[None] * 6, "resize", *[None] * 6, "q"])

        def answer(timeout):
            step = next(script)
            time.sleep(timeout)
            if step == "resize":
                terminal._ASKED = True       # what `read_key` leaves when a resize ended it
                return None
            return step
        waits = self.run_menu(answer)
        self.assert_breathing(waits[0][2], waits[1:7])
        self.assertEqual(waits[7][2][:3], "\033[H")      # drawn again, not a frame at old cells
        self.assert_breathing(waits[7][2], waits[8:])

    def test_a_pipe_no_color_and_eight_colours_draw_no_frames(self):
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = os.fdopen(reader)
        self.addCleanup(pipe.close)
        stills = {"pipe": (patch.object(sys, "stdin", pipe), patch.object(
                      terminal, "Keyboard", TERMINAL)),
                  "NO_COLOR": (patch.dict(os.environ, {"NO_COLOR": "1"}),),
                  "eight colours": (patch.dict(os.environ, {"COLORTERM": ""}),
                                    patch("curses.setupterm"),
                                    patch("curses.tigetnum", return_value=8))}
        for still, patches in stills.items():
            with self.subTest(still), ExitStack() as stack:
                for each in patches:
                    stack.enter_context(each)
                script = iter([None, "q"])
                waits = self.run_menu(lambda timeout: next(script))
                self.assertEqual([timeout for timeout, _, _ in waits], [menu.TICK] * 2)
                for _, _, written in waits:
                    self.assertNotRegex(written, r"\x1b\[\d+;\d+H")   # no cell rewritten


if __name__ == "__main__":
    unittest.main(verbosity=2)
