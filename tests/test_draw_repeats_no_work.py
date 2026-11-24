"""A draw repeats no work an earlier one did: each character's width is looked up once a
process.

The owner's report (18 Oct 2026): every key should answer within a tenth of a second.  A main
screen draw looked up the width of thousands of characters, the same few dozen each time.
Offline: a temporary HOME, fake seats, no terminal; the work is counted, not timed.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal  # noqa: E402


class NoWorkTwice(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        row = {"word": "working", "reason": "", "since": None}
        self.stack.enter_context(patch.object(menu, "seat_row_state",
                                              side_effect=lambda *_a, **_kw: dict(row)))
        self.seats = [{"name": name, "repo": "", "path": "", "created": 9000}
                      for name in ("acme-api", "acme-docs")]
        for name in ("acme-api", "acme-docs"):
            config.save_session(self.cfg, name, "opus", ["astra"])
            config.plan_path(name).write_text("- [x] a\n- [ ] b — étapes ━ 準備\n")

    def draw(self):
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, "acme-api", {}, look=False, records=[])
        return out.getvalue()

    def test_a_second_draw_looks_up_no_character_s_width(self):
        first = self.draw()
        widths = self.stack.enter_context(patch.object(
            terminal.unicodedata, "east_asian_width", wraps=terminal.unicodedata.east_asian_width))
        self.assertEqual(self.draw(), first)
        self.assertEqual(widths.call_count, 0)
        texts = ("ab", "\033[1mab\033[0m", "━ é 準", "e\u0301")     # a wide one, a mark
        self.assertEqual([terminal.cells(text) for text in texts], [2, 2, 6, 1])


if __name__ == "__main__":
    unittest.main()
