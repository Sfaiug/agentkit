"""A page comes up as it opens: under its header and rule it fades in out of the background
while the header keeps `agentkit` and writes the page's name out after it, in FADE seconds, and
is then as drawn -- `c`, `p`, a project's features, the models, the new-session picker and the
pages `c` opens as each opens.  A screen gone back to is drawn as it is, and a list one of `c`'s
pages opens comes up under its row as the line under the menu's highlighted row does.

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
from agentkit.terminal import Key  # noqa: E402

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

    def pages(self):
        """The pages `c` opens: each one's name and how it opens."""
        return (("models", lambda: menu.models_page(self.cfg, None)),
                ("discord", menu.config_discord),
                ("weekly audit", lambda: menu.config_audit(self.cfg)))

    def read(self, opens, keys, step=motion.FADE / 6):
        """What `opens()` writes read with `keys`, each `step` seconds after the one before,
        then Esc; and the clock it made.  A key may be a call, read at once, giving the key."""
        keys = iter([*keys, Key("esc")])

        def read_key(*_args, **_kwargs):
            key = next(keys)
            if callable(key):
                return key()
            self.time.now += step
            return key
        self.made.clear()
        self.time.now, output = OPENED, io.StringIO()
        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "read_key", side_effect=read_key), redirect_stdout(output):
            opens()
        clock, = self.made
        return output.getvalue(), clock

    def test_cs_pages_come_up_under_their_header_as_they_open(self):
        for name, opens in self.pages():
            with self.subTest(name):
                output, clock = self.read(opens, [], step=0)
                self.assertNotIn("\033[Kagentkit", output)      # never first drawn as it is
                self.assert_comes_up(clock, f"config · {name}")

    def test_a_cs_page_gone_back_to_from_a_list_or_a_field_is_drawn_as_it_is(self):
        """Inside the opening, Weekly audit's `Orchestrator` list opened and closed, and
        Discord's `Mention` typed into and left."""
        pages = dict(self.pages())
        for name, keys in (("weekly audit", [Key("down"), Key("enter"), Key("esc")]),
                           ("discord", [Key("enter"), Key("esc")])):
            with self.subTest(name):
                output, clock = self.read(pages[name], keys)
                back = output.rsplit("\033[H", 1)[-1]
                self.assertTrue(back.startswith(f"\033[Kagentkit · config · {name}"),
                                repr(back[:120]))
                self.assertIsNone(clock.rising)

    def test_a_list_a_cs_page_opens_comes_up_under_its_row(self):
        """Weekly audit's `Orchestrator`, on screen row 4, opened once the page is up: each
        choice under it fades in in OPEN seconds from the draw, and nothing else moves."""
        frames = []

        def drawn():              # the key after Enter, read once the list is drawn
            clock, began, lines = self.made[0], self.time.now, terminal.on_screen()
            for at in (0.5, 1):
                self.time.now = began + at * motion.OPEN
                amount = 1 - motion.eased((self.time.now - began) / motion.OPEN)
                frames.append((amount, rows(clock.frame()), lines))
            return Key("esc")
        self.read(lambda: menu.config_audit(self.cfg), [Key("down"), Key("enter"), drawn], step=1)
        choices = list(range(5, 5 + len(menu.config.offered(self.cfg))))
        self.assertEqual(len(frames), 2)
        for amount, written, lines in frames:
            self.assertEqual(sorted(written), choices)
            for row in choices:
                self.assertEqual(written[row], terminal.fade(lines[row - 1], amount))

    def test_a_page_gone_back_to_is_drawn_as_it_is(self):
        """`x` on the past screen as it opens: the stop's own screen, and the page back as it is,
        as `c` is back from its models."""
        seats = [{"name": name, "repo": None, "path": "/", "created": 9000, "closed": 9500}
                 for name in ("fix-api", "fix-web")]
        keys = iter([terminal.Key("char", "x"), terminal.Key("down"), terminal.Key("enter"),
                     terminal.Key("esc")])

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
