"""A draw repeats no work an earlier one did: each character's width is looked up once a
process, and a colour the terminal lacks is computed straight, not searched for, still the
nearest it has and the lower number on a tie.

The owner's report (18 Oct 2026): every key should answer within a tenth of a second.  A main
screen draw looked up the width of thousands of characters, the same few dozen each time, and a
fade's every new colour searched all 240 of xterm's.  Offline: a temporary HOME, fake seats, no
terminal; the work is counted, not timed.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal  # noqa: E402


def searched(rgb):
    """The nearest of xterm's 240 fixed colours, found by trying each in order."""
    wanted = [int(rgb[i:i + 2], 16) for i in (0, 2, 4)]
    colours = [(16 + 36 * r + 6 * g + b, (red, green, blue))
               for r, red in enumerate(terminal.LEVELS) for g, green in enumerate(terminal.LEVELS)
               for b, blue in enumerate(terminal.LEVELS)]
    colours += [(232 + n, (8 + 10 * n,) * 3) for n in range(24)]
    return min(colours, key=lambda item: sum((a - b) ** 2 for a, b in zip(wanted, item[1])))[0]


class NoWorkTwice(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=256))
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

    def test_a_colour_the_terminal_lacks_is_the_nearest_it_has(self):
        rng = random.Random(7)
        # every channel's halfway between two of the cube's levels, and each grey's, are ties
        edges = sorted({value for low, high in zip(terminal.LEVELS, terminal.LEVELS[1:])
                        for value in ((low + high) // 2, (low + high + 1) // 2)}
                       | {13 + 10 * n for n in range(24)} | {0, 255})
        colours = [(r, g, b) for r in edges for g in edges[::4] for b in edges[::4]]
        colours += [tuple(rng.randrange(256) for _ in "rgb") for _ in range(1500)]
        for rgb in (f"{r:02x}{g:02x}{b:02x}" for r, g, b in colours):
            self.assertEqual(terminal.xterm_colour(rgb), searched(rgb), rgb)


if __name__ == "__main__":
    unittest.main()
