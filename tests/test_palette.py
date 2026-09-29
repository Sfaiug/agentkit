"""ak's colours fit the terminal they are on, and a usage bar's colour says what is left; offline.

A pty stands in for the terminal: `sense` asks it for its background and the test has answered,
or has not.  tmux is a faked `subprocess.run`; nothing real is asked.
"""

import json
import os
import pty
import subprocess
import sys
import time
import tty
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, menu, terminal

QUERY = b"\033]11;?\033\\"
WHITE = b"\033]11;rgb:ffff/ffff/ffff\033\\"


class Palette(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        tty.setcbreak(slave)            # as `Keyboard.take` leaves it: no lines, no echo
        stdin, stdout = os.fdopen(slave, "r"), os.fdopen(os.dup(slave), "w")
        for end in (stdin, stdout):
            self.addCleanup(end.close)
        self.addCleanup(os.close, self.master)
        for target, name, value in ((terminal, "_RGB", False), (terminal, "_LIGHT", False),
                                    (terminal, "_KEYED", b""), (sys, "stdin", stdin),
                                    (sys, "stdout", stdout)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        environ = patch.dict(os.environ, {"TERM": "xterm-256color", "LANG": "C.UTF-8"}, clear=True)
        environ.start()
        self.addCleanup(environ.stop)

    def sense(self, *sent):
        """`terminal.sense` on a terminal that has sent `sent` already; how long it took."""
        for part in sent:
            os.write(self.master, part)
        began = time.monotonic()
        terminal.sense()
        took = time.monotonic() - began
        self.assertEqual(os.read(self.master, 64), QUERY)   # what it asked the terminal
        return took

    def test_tmux_reporting_rgb_gives_true_colour_with_colorterm_unset(self):
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,1,0"}), \
                patch("curses.setupterm"), patch("curses.tigetnum", return_value=256):
            self.assertNotIn("COLORTERM", os.environ)
            self.assertEqual(terminal.colour_depth(), 256)
            for said, depth in (("256,RGB,bpaste,clipboard,title\n", 24), ("256,Tc\n", 24),
                                ("256,bpaste,clipboard,title\n", 256), ("", 256)):
                with self.subTest(features=said), patch.object(
                        terminal.subprocess, "run",
                        return_value=subprocess.CompletedProcess([], 0, said, "")) as tmux:
                    self.sense()
                    self.assertEqual(tmux.call_args.args[0],
                                     ["tmux", "display", "-p", "#{client_termfeatures}"])
                    self.assertEqual(terminal.colour_depth(), depth)
                    self.assertEqual(terminal.styled("working", "working"),
                                     "\033[38;2;137;180;250mworking\033[0m" if depth == 24 else
                                     "\033[38;5;111mworking\033[0m")
                    with patch.dict(os.environ, {"NO_COLOR": ""}):
                        self.assertEqual(terminal.colour_depth(), 0)   # whatever tmux says
        # outside tmux nothing is asked of it
        with patch.object(terminal.subprocess, "run", side_effect=AssertionError("tmux")):
            self.sense()
        self.assertFalse(terminal._RGB)

    def test_a_white_answer_picks_the_light_palette_and_none_in_time_the_dark(self):
        self.assertLess(self.sense(WHITE), 0.1)
        self.assertTrue(terminal._LIGHT)
        with patch.object(terminal, "colour_depth", return_value=24):
            for kind, rgb in (("accent", "30;102;245"), ("working", "30;102;245"),
                              ("needs you", "156;99;20"), ("done", "51;128;34"),
                              ("FAIL", "210;15;57"), ("dim", "108;111;133")):
                self.assertIn(f"38;2;{rgb}m", terminal.styled("x", kind), kind)
            self.assertIn("38;2;30;102;245m", terminal.highlight(" row"))
        # a dark answer, BEL-ended, and no answer at all within a tenth of a second: dark
        self.sense(b"\033]11;rgb:1e1e/1e1e/2e2e\007")
        self.assertFalse(terminal._LIGHT)
        terminal._LIGHT = True
        self.assertGreaterEqual(self.sense(), 0.1)
        self.assertFalse(terminal._LIGHT)
        with patch.object(terminal, "colour_depth", return_value=24):
            self.assertIn("38;2;137;180;250m", terminal.styled("x", "accent"))

    def test_the_answer_never_reaches_read_key_as_keys(self):
        # a key typed while the answer was awaited is kept for read_key, the answer is not
        self.sense(b"j", WHITE)
        self.assertTrue(terminal._LIGHT)
        self.assertEqual(terminal.read_key(0.2), terminal.Key("char", "j"))
        self.assertIsNone(terminal.read_key(0.2))
        # an answer come after its tenth of a second is swallowed whole by read_key
        self.sense()
        self.assertFalse(terminal._LIGHT)
        os.write(self.master, WHITE + b"k")
        self.assertEqual(terminal.read_key(0.5), terminal.Key("char", "k"))
        os.write(self.master, b"\033]11;rgb:ffff/ffff/ffff\007")
        self.assertIsNone(terminal.read_key(0.2))
        # and one cut short by the tenth of a second is swallowed from where it was cut
        self.sense(WHITE[:9])
        os.write(self.master, WHITE[9:] + b"q")
        self.assertEqual(terminal.read_key(0.5), terminal.Key("char", "q"))
        self.assertIsNone(terminal.read_key(0.2))


class Bars(Sandbox):
    def test_bars_at_half_a_sixth_and_a_thirtieth_left_draw_accent_amber_red(self):
        week = {"name": "weekly", "resets_at": 10000 + 3 * 86400, "window_secs": 604800}
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [{**week, "used": 50}]},
            "openai": {"meters": [{**week, "used": 85}]},
            "meta": {"meters": [{**week, "used": 97}]}}}))
        for depth in (24, 256, 8):
            with self.subTest(depth=depth), \
                    patch.object(terminal, "colour_depth", return_value=depth):
                rows = {terminal.plain(row).split()[0]: row
                        for row in menu.usage_lines(self.cfg, 100)[1:]}
                # 50% left is six cells of twelve, 15% two, and 3% still one
                for label, cells, kind in (("Claude", 6, "accent"), ("ChatGPT", 2, "amber"),
                                           ("Muse", 1, "FAIL")):
                    self.assertIn(terminal.styled("█" * cells, kind) +
                                  terminal.styled("░" * (12 - cells), "dim"), rows[label])
        self.assertEqual([menu.fill(left) for left in (100, 21, 20, 6, 5, 1, 0)],
                         ["accent", "accent", "amber", "amber", "FAIL", "FAIL", "FAIL"])
        with patch.object(terminal, "colour_depth", return_value=24):
            dark = "\n".join(menu.usage_lines(self.cfg, 100))
            with patch.object(terminal, "_LIGHT", True):
                light = "\n".join(menu.usage_lines(self.cfg, 100))
        for text, accent, amber, red in ((dark, "137;180;250", "249;226;175", "243;139;168"),
                                         (light, "30;102;245", "156;99;20", "210;15;57")):
            self.assertIn(f"\033[38;2;{accent}m██████\033[0m", text)
            self.assertIn(f"\033[1;38;2;{amber}m██\033[0m", text)
            self.assertIn(f"\033[38;2;{red}m█\033[0m", text)


if __name__ == "__main__":
    unittest.main()
