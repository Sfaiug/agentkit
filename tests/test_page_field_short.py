"""A secret typed under its row on a page `c` opens stays on a short screen, its cursor on it.

A review of the Discord page (#1330) found that opening a field on a 40x8 terminal drew every
row and the note, ten lines, so the frame scrolled and the cursor went below the field.  The
field's lines are drawn on the page matrix_key would show, held on them.  Offline: the frame
and the field are faked, nothing is written.
"""

from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, terminal  # noqa: E402


class ShortField(unittest.TestCase):
    def opened(self, height, row):
        """The frames the Discord page draws on a 40-column screen `height` tall, with the
        field under its `row`th row (0, Mention; 1, Webhook) opened, and the field's own frame
        with the screen row it said its line was on."""
        frames, cursor = [], []

        def framed(title, body=(), keyline="esc back", **_kw):
            frames.append([terminal.header_line(title, ""), "", *body, "",
                           *terminal.key_line(keyline)])
            return {}

        def field(prompt, hint, around):
            line = around(prompt + "typed")
            cursor.append((line, frames[-1]))
            return None
        keys = [terminal.Key("down")] * row + [terminal.Key("enter"), terminal.Key("esc")]
        with ExitStack() as stack:
            for target, name, value in ((menu, "_secret", ""), (menu, "read", None),
                                        (terminal, "width", 40), (terminal, "height", height)):
                stack.enter_context(patch.object(target, name, return_value=value))
            stack.enter_context(patch.object(terminal, "read_key", side_effect=keys))
            stack.enter_context(patch.object(terminal, "frame", side_effect=framed))
            stack.enter_context(patch.object(terminal, "field", side_effect=field))
            stack.enter_context(redirect_stdout(io.StringIO()))
            menu.config_discord()
        return frames, cursor[0]

    def test_the_field_and_its_cursor_stay_on_a_short_screen(self):
        for height in (8, 9, 40):
            for row in (0, 1):
                with self.subTest(height=height, row=row):
                    frames, (cursor, typed) = self.opened(height, row)
                    self.assertTrue(all(len(frame) <= height for frame in frames),
                                    [len(frame) for frame in frames])
                    self.assertEqual(terminal.plain(typed[cursor - 1]).strip(), "typed")


if __name__ == "__main__":
    unittest.main()
