"""A page comes up as it opens: under its header and rule it fades in out of the background
while the header keeps `agentkit` and writes the page's name out after it, in FADE seconds, and
is then as drawn -- `c`, `p`, a project's features, the models and the new-session picker as each
opens.  A screen gone back to is drawn as it is.

The owner's pick of 18 Oct 2026 (motion 5, a page that slides in).  Offline: a temporary HOME,
no terminal, the motion clock's time injected and each frame it writes read back.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import menu, motion, terminal  # noqa: E402

OPENED = 500.0


class Time:
    """`time` as motion.py sees it: what `now` says, every other name the real module's."""

    def __init__(self):
        self.now = OPENED

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


def rows(frame):
    """What a frame writes on each row it writes from its first column, {row: text}."""
    parts = re.split(r"\033\[(\d+);1H", frame)
    return {int(row): text for row, text in zip(parts[1::2], parts[2::2])}


class PageComesUp(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.stack.enter_context(patch.object(terminal, "height", return_value=24))
        self.time = Time()
        self.stack.enter_context(patch.object(motion, "time", self.time))
        self.made = []
        made, Clock = self.made, motion.Clock

        class Kept(Clock):        # each clock a screen makes, kept to read once it has gone
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                made.append(self)
        self.stack.enter_context(patch.object(motion, "Clock", Kept))

    def assert_comes_up(self, clock, name):
        lines, began = clock.rising
        self.assertEqual(began, OPENED)
        header = terminal.header_line(name, terminal.plain(lines[0]).split()[-1])
        self.assertEqual(lines[0], header)
        for at, x in ((0, 0), (0.5, None), (1, 1)):
            self.time.now = OPENED + at * motion.FADE
            written = rows(clock.frame())
            # `agentkit` and the rule stay as drawn; the name writes itself out after it
            self.assertTrue(written[1].startswith("agentkit"))
            self.assertEqual(terminal.cells(written[1]), terminal.cells(header))
            self.assertEqual(written[2], lines[1])
            if x is not None:
                self.assertEqual(written[1], motion.titled(header, x))
            amount = 1 - motion.eased((self.time.now - OPENED) / motion.FADE)
            for row, line in enumerate(lines[2:], 3):
                self.assertEqual(written[row], terminal.fade(line, amount))
        self.assertEqual(written[1], header)
        self.assertIsNone(clock.rising)     # and up: drawn as it is from here

    def test_the_name_writes_itself_out_after_agentkit(self):
        header = terminal.header_line("past sessions", "19:01")
        self.assertEqual(motion.titled(header, 0).split(), ["agentkit", "19:01"])
        half = motion.titled(header, 0.5)
        self.assertTrue(half.startswith("agentkit · past "), half)
        self.assertNotIn("sessions", half)
        self.assertEqual(terminal.cells(half), terminal.cells(header))
        self.assertEqual(motion.titled(header, 1), header)
        menus = terminal.header_line("", "19:01")
        self.assertEqual(motion.titled(menus, 0), menus)          # the menu's has no name

    def test_past_comes_up_under_its_header_as_it_opens(self):
        seat = {"name": "fix-api", "repo": None, "path": "/", "created": 9000, "closed": 9500}
        output = io.StringIO()
        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "read_key", return_value=terminal.Key("esc")), \
                redirect_stdout(output):
            menu.show_past({"fixture": True}, [seat], keyboard=None)
        clock, = self.made
        self.assertNotIn("\033[Kagentkit", output.getvalue())     # never first drawn as it is
        self.assertIn("fix-api", terminal.plain("".join(clock.rising[0])))
        self.assert_comes_up(clock, "past sessions")

    def test_a_page_gone_back_to_is_drawn_as_it_is(self):
        """`x` on the past screen as it opens: the stop's own screen, and the page back as it is,
        as `c` is back from its models."""
        seats = [{"name": name, "repo": None, "path": "/", "created": 9000, "closed": 9500}
                 for name in ("fix-api", "fix-web")]
        keys = iter([terminal.Key("char", "x"), terminal.Key("esc")])

        def read_key(*_args, **_kwargs):
            self.time.now += motion.FADE / 6        # each key well inside the opening
            return next(keys)
        output = io.StringIO()
        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "read_key", side_effect=read_key), \
                patch.object(menu, "teardown", return_value=[sys.executable, "-c", ""]), \
                redirect_stdout(output):
            menu.show_past({"fixture": True}, seats, keyboard=Mock())
        back = output.getvalue().rsplit("\033[H", 1)[-1]
        self.assertTrue(back.startswith("\033[Kagentkit · past sessions"), repr(back[:120]))
        clock, = self.made
        self.assertIsNone(clock.rising)


if __name__ == "__main__":
    unittest.main()
