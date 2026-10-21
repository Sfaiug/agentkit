"""ak's colours fit the terminal they are on, and a usage bar's colour says what is left; offline.

A pty stands in for the terminal: `sense` asks it for its background and its attributes and the
test has answered, or has not, on a clock that stands still while `sense` waits, so only the wait
running out ends it.  tmux is a faked `subprocess.run`; nothing real is asked.
"""

import json
import os
import pty
import select
import subprocess
import sys
import time
import tty
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, guard, menu, terminal

QUERY = b"\033]11;?\033\\\033[c"
WHITE = b"\033]11;rgb:ffff/ffff/ffff\033\\"
ATTRIBUTES = b"\033[?62;22c"   # DA1's answer, which a terminal sends after any answer before it


class Still:
    """`time` as `terminal` sees it, standing still: `sense`'s wait ends only by running out."""

    def monotonic(self):
        return 0.0

    def __getattr__(self, name):
        return getattr(time, name)


class Waits:
    """`select` as `terminal` sees it, each wait going through `select`."""

    def __init__(self, select):
        self.select = select


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
        """`terminal.sense` on a terminal that has sent `sent` already; whether its wait ran out."""
        for part in sent:
            os.write(self.master, part)
        ready = []

        def waited(*args):
            found = select.select(*args)
            ready.append(found[0])
            return found

        with patch.object(terminal, "select", Waits(waited)), \
                patch.object(terminal, "time", Still()):
            terminal.sense()
        self.assertEqual(os.read(self.master, 64), QUERY)   # what it asked the terminal
        return not all(ready)

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
                    self.assertEqual(tmux.call_args.args[0], [guard.real("tmux"), "display",
                                                              "-p", "#{client_termfeatures}"])
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

    def test_a_popup_handed_its_clients_features_asks_tmux_nothing(self):
        # what `orch.tmux_conf`'s popup is handed as the key is pressed, read for its first frame
        for said, rgb in (("256,RGB,bpaste,title", True), ("256,bpaste,title", False)):
            with self.subTest(features=said), patch.dict(os.environ, {
                    "TMUX": "/tmp/tmux-1000/default,1,0", terminal.FEATURES_ENV: said}), \
                    patch.object(terminal.subprocess, "run", side_effect=AssertionError("tmux")):
                self.sense()
                self.assertIs(terminal._RGB, rgb)

    def test_a_white_answer_picks_the_light_palette_and_none_in_time_the_dark(self):
        self.assertFalse(self.sense(WHITE, ATTRIBUTES))
        self.assertTrue(terminal._LIGHT)
        with patch.object(terminal, "colour_depth", return_value=24):
            for kind, rgb in (("accent", "30;102;245"), ("working", "30;102;245"),
                              ("needs you", "156;99;20"), ("done", "51;128;34"),
                              ("FAIL", "210;15;57"), ("dim", "108;111;133")):
                self.assertIn(f"38;2;{rgb}m", terminal.styled("x", kind), kind)
            self.assertIn("38;2;30;102;245m", terminal.highlight(" row"))
        # a dark answer, BEL-ended, and no answer at all within a tenth of a second: dark
        self.sense(b"\033]11;rgb:1e1e/1e1e/2e2e\007", ATTRIBUTES)
        self.assertFalse(terminal._LIGHT)
        terminal._LIGHT = True
        self.assertTrue(self.sense())
        self.assertFalse(terminal._LIGHT)
        with patch.object(terminal, "colour_depth", return_value=24):
            self.assertIn("38;2;137;180;250m", terminal.styled("x", "accent"))

    def test_attributes_alone_end_the_wait_at_once_and_read_as_dark(self):
        # tmux, in a popup: no answer to OSC 11, its own to DA1 at once
        terminal._LIGHT = True
        self.assertFalse(self.sense(b"\033[?1;2;4c"))
        self.assertFalse(terminal._LIGHT)
        self.assertIsNone(terminal.read_key(0.2))

    def test_the_answer_never_reaches_read_key_as_keys(self):
        # a key typed while the answers were awaited is kept for read_key, the answers are not,
        # and one typed after them is the keyboard's own
        self.sense(b"j", WHITE, b"k", ATTRIBUTES, b"l")
        self.assertTrue(terminal._LIGHT)
        for char in "jkl":
            self.assertEqual(terminal.read_key(0.2), terminal.Key("char", char))
        self.assertIsNone(terminal.read_key(0.2))
        # answers come after their tenth of a second are swallowed whole by read_key
        self.sense()
        self.assertFalse(terminal._LIGHT)
        os.write(self.master, WHITE + ATTRIBUTES + b"k")
        self.assertEqual(terminal.read_key(0.5), terminal.Key("char", "k"))
        os.write(self.master, b"\033]11;rgb:ffff/ffff/ffff\007")
        self.assertIsNone(terminal.read_key(0.2))
        # and one cut short by the tenth of a second is swallowed from where it was cut
        self.sense(WHITE[:9])
        os.write(self.master, WHITE[9:] + ATTRIBUTES + b"q")
        self.assertEqual(terminal.read_key(0.5), terminal.Key("char", "q"))
        self.assertIsNone(terminal.read_key(0.2))


class Bars(Sandbox):
    def test_meters_are_grey_at_rest_and_the_one_pointed_at_in_its_companys_colour(self):
        week = {"name": "weekly", "resets_at": 10000 + 3 * 86400, "window_secs": 604800}
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [{**week, "used": 50}]},
            "openai": {"meters": [{**week, "used": 85}]},
            "meta": {"meters": [{**week, "used": 97}]}}}))
        for depth in (24, 256, 8):
            with self.subTest(depth=depth), \
                    patch.object(terminal, "colour_depth", return_value=depth):
                rest = "\n".join(menu.usage_lines(self.cfg, 120))
                # 50% left is five cells of ten, 15% two, and 3% still one, none in a colour
                for cells in (5, 2, 1):
                    self.assertIn("▰" * cells + terminal.styled("▱" * (10 - cells), "dim"), rest)
                lit = "\n".join(menu.usage_lines(self.cfg, 120, lit=1))
                self.assertIn(terminal.styled("Claude", "#D97757"), lit)
                self.assertIn(terminal.styled("▰" * 5, "#D97757") +
                              terminal.styled("▱" * 5, "dim"), lit)
                self.assertNotIn(terminal.styled("Claude", "#D97757"), rest)

    def test_a_light_grey_of_the_callers_reads_as_its_mirror_on_a_light_background(self):
        with patch.object(terminal, "colour_depth", return_value=24):
            dark = [terminal.styled("█", own) for own in ("#FFFFFF", "#C8C8C0", "#303030", "#D97757")]
            with patch.object(terminal, "_LIGHT", True):
                light = [terminal.styled("█", own) for own in ("#FFFFFF", "#C8C8C0", "#303030", "#D97757")]
        self.assertEqual(dark, ["\033[38;2;255;255;255m█\033[0m", "\033[38;2;200;200;192m█\033[0m",
                                "\033[38;2;48;48;48m█\033[0m", "\033[38;2;217;119;87m█\033[0m"])
        # ChatGPT's white reads black and a light grey dark; a dark grey and a hue read as they are
        self.assertEqual(light, ["\033[38;2;0;0;0m█\033[0m", "\033[38;2;55;55;63m█\033[0m",
                                 "\033[38;2;48;48;48m█\033[0m", "\033[38;2;217;119;87m█\033[0m"])
        with patch.object(terminal, "colour_depth", return_value=8), \
                patch.object(terminal, "_LIGHT", True):
            self.assertEqual(terminal.styled("█", "#FFFFFF"), "\033[30m█\033[0m")


if __name__ == "__main__":
    unittest.main()
