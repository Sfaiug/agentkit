"""A working session's dot breathes, every one in step, and nothing else on the screen moves.

`menu.loop` on a scripted wait over a true-colour terminal with two working seats and one that
needs you: between draws only the two working `●` are rewritten, each frame both in one colour,
the colour easing between `working`'s and a dimmer tone of it; at most twenty frames a second;
a key pressed mid-animation has its frame out within 100 ms.  From a pipe, under NO_COLOR and
at eight colours the wait is the plain TICK and no frame is drawn.  Offline, in a throwaway
HOME: the probe is never started and the keyboard is a stand-in.
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
DOT = re.compile(r"\x1b\[(\d+);(\d+)H\x1b\[38;2;(\d+);(\d+);(\d+)m●\x1b\[0m")
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
        seats = [{"name": name, "repo": str(repo), "path": str(repo), "created": 0}
                 for name in WORDS]

        def row_state(cfg, session, look=True, **facts):
            return {"word": WORDS[session["name"]], "reason": "", "since": None}

        for target, name, fake in (
                (orch, "listing", lambda: [dict(seat) for seat in seats]),
                (menu, "run_records", list),
                (menu, "seat_row_state", row_state),
                (menu, "seat_progress", lambda name: (0, 0)),
                (orch, "job_notices", lambda: []),
                (menu.Live, "probe", lambda self, now=None: False),
                (terminal, "Keyboard", Keyboard),
                (terminal, "sense", lambda: None),     # a taken keyboard's, no real terminal's
                (terminal, "width", lambda *args: 100)):
            self.stack.enter_context(patch.object(target, name, fake))

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
        return {(row, terminal.ANSI.sub("", line).index("●") + 1)
                for row, line in enumerate(lines, 1) for name, word in WORDS.items()
                if word == "working" and f" {name} " in terminal.ANSI.sub("", line)}

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
