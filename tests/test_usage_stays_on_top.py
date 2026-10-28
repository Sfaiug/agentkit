"""The usage stays at the top of the ak screen and the keys at its bottom, whatever the seats.

The owner's words (14 Oct 2026): "usage always seen, also menu at the bottom always seen".  Every
page has the usage under the header and, with the keyboard, the key line on the bottom row but
the two every draw keeps.  A screen too short for the block and a few rows under it folds it to
each subscription's reading, whole -- a label gives way, never its share -- and only one too
short for a seat under its heading even then cuts them, saying so.  The line the pointer opens
under the grid fits the screen and says what the grid was drawn from.  Offline: a temporary HOME,
fake seats, no tmux.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, terminal  # noqa: E402

WEEK = 604800
# the longest key line the menu draws: a stopped seat's `p past` on it, the keyboard its own
LONG_KEYS = "↑↓←→ move   ⏎ open   n new   p past   c config   esc leave"


class UsageStaysOnTop(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": "at_prompt", "since": 9100, "began": 9100}))
        acme = config.CODE / "acme"
        acme.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(acme)], check=True)
        self.seats = [{"name": f"acme-{n:02d}", "repo": str(acme), "path": str(acme),
                       "created": 9000 + n} for n in range(14)]
        for seat in self.seats:
            config.save_session(self.cfg, seat["name"], "fable", ["opus"], {"repo": str(acme)})
        self.meters = {"anthropic": {"meters": [{"name": "weekly_all", "used": 79}]},
                       "openai": {"meters": [{"name": "weekly", "used": 31, "window_secs": WEEK}]}}

    def draw(self, width, height, seats=14, cursor=None, keys=None, piped=False):
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000,
                                                             "providers": self.meters}))
        drawn = {}
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats[:seats], keys or terminal.keys(menu.KEYS, enter="open"),
                      0, cursor, None if piped else drawn, look=False)
        return terminal.ANSI.sub("", out.getvalue().replace("\033[K", "")).split("\n")[:-1], drawn

    def point(self, width, height, label, rows=None):
        """The screen with one seat and the pointer on `label`'s cell of the grid, its usage
        read from `rows` when they are handed in, one reading a call."""
        _, drawn = self.draw(width, height, seats=1)
        number = [terminal.plain(shown) for _, shown, _, _ in menu.usage_rows(self.cfg)
                  ].index(label) + 1
        row, column = next((row, first) for row, (_, places, *_) in drawn["spots"].items()
                           for first, _, cell in places if cell == ("usage", number))
        with patch.object(terminal, "_POINTER", terminal.Key("point", "", column, row)), \
                patch.object(menu, "usage_rows", side_effect=rows or menu.usage_rows):
            return self.draw(width, height, seats=1)[0]

    def test_every_page_has_the_usage_on_top_and_the_keys_on_the_bottom_row(self):
        _, drawn = self.draw(100, 24)
        self.assertGreater(len(drawn["turns"]), 1)
        for first in drawn["turns"]:
            lines, _ = self.draw(100, 24, cursor=first)
            self.assertRegex(lines[2], r"Claude +[▰▱]+ +21% left")       # under the rule
            self.assertEqual(len(lines), 22, lines)
            self.assertIn("esc leave", lines[-1])
        lines, _ = self.draw(80, 24, seats=1)      # one seat: the keys still on the bottom row
        self.assertEqual((len(lines), "esc leave" in lines[-1]), (22, True), lines)

    def test_a_short_screen_keeps_every_reading_whole(self):
        labels = [terminal.plain(label) for _, label, _, _ in menu.usage_rows(self.cfg)]
        for width, height, seats, keys in ((100, 14, 14, None), (40, 14, 14, None),
                                           (30, 14, 1, None), (30, 20, 14, None),
                                           (30, 11, 1, None), (38, 10, 1, LONG_KEYS),
                                           (28, 13, 1, LONG_KEYS),
                                           (38, 10, 14, LONG_KEYS),
                                           (40, 15, 0, None), (100, 11, 0, None)):
            lines, _ = self.draw(width, height, seats, keys=keys)
            text = "\n".join(lines)
            self.assertLessEqual(len(lines), height - 2, text)
            self.assertNotIn("no reading yet", text)                   # not the grid
            self.assertNotIn("…", text.split("\nacme")[0])
            for label in labels:
                self.assertRegex(text, rf"{re.escape(label)} (\d+%|—)", (width, height, label))
            self.assertIn("ChatGPT 69%", text)

    def test_a_short_empty_screen_keeps_readings_without_reserving_page_keys(self):
        for width, height in ((30, 8), (28, 9)):
            for piped in (False, True):
                with self.subTest(width=width, height=height, piped=piped):
                    lines, _ = self.draw(width, height, seats=0, keys=LONG_KEYS,
                                         piped=piped)
                    self.assertIn("Claude 21%", lines[0])
                    self.assertIn("  no sessions; n starts one", lines)
                    self.assertIn("esc leave", lines[-1])
                    self.assertLessEqual(len(lines), height - 2, lines)
                    self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)

    def test_a_spent_week_says_its_credits_and_a_long_label_gives_way_first(self):
        self.meters["openai"] = {"meters": [{"name": "weekly", "used": 100, "window_secs": WEEK}],
                                 "credits": 62469.67}
        self.cfg["providers"]["acme_subscription_provider"] = dict(self.cfg["providers"]["openai"])
        self.meters["acme_subscription_provider"] = {
            "meters": [{"name": "weekly", "used": 17, "window_secs": WEEK}]}
        text = "\n".join(self.draw(30, 20)[0])
        self.assertIn("ChatGPT 62,469 credits left", text)
        self.assertRegex(text, r"Acme_Sub\S*… 83%")
        self.assertIn("  MiMo   — no reading yet", self.draw(28, 30, seats=1)[0])   # the grid's too
        self.meters["openai"]["currency"] = "CHF"      # its label gives way, the line fits
        lines, _ = self.draw(28, 20, seats=1)
        self.assertIn("  CHF 62,469.67 credits left", lines)
        self.assertIn("  CHF 62,469.67 credits left", self.draw(28, 30, seats=1)[0])   # no grid
        self.assertEqual([line for line in lines if terminal.cells(line) > 28], [])

    def test_only_a_screen_with_no_room_for_a_seat_cuts_the_readings_and_says_so(self):
        lines, _ = self.draw(30, 9, keys=LONG_KEYS)
        self.assertLessEqual(len(lines), 7, lines)
        self.assertTrue(lines[0].endswith(" · …"), lines)
        self.assertTrue(any(re.match(r"[›> ] +\d+  ", line) for line in lines), lines)
        # a first reading as wide as the line keeps what it has left, its label giving way
        self.meters["anthropic"] = {"meters": [{"name": "weekly_all", "used": 100}],
                                    "credits": 62469.67}
        self.assertRegex(self.draw(30, 9, keys=LONG_KEYS)[0][0],
                         r"^  \S+… 62,469 credits left · …$")
        self.cfg["providers"]["acme_subscription_provider"] = dict(self.cfg["providers"]["openai"],
                                                                   colour="#ff0000")
        self.meters["acme_subscription_provider"] = {
            "meters": [{"name": "weekly", "used": 17, "window_secs": WEEK}]}
        self.assertRegex(self.draw(30, 9, keys=LONG_KEYS)[0][0],
                         r"^  Acme_Sub\S*… 83% · …$")

    def test_the_line_under_the_pointer_fits_and_reads_the_grid_it_lights(self):
        long = "acme_subscription_for_research_and_testing"
        self.cfg["providers"][long] = dict(self.cfg["providers"]["openai"])
        self.meters[long] = {"meters": [{"name": "weekly", "used": 50, "window_secs": WEEK}]}
        lines = self.point(40, 30, long.title())
        self.assertIn("  Acme_Subscription_For_Research_And_…",           # its label gives way
                      [line.rstrip() for line in lines])
        self.assertEqual([line for line in lines if terminal.cells(line) > 40], [])
        # a reading that would fold the grid lands mid-draw: the draw is the grid it read
        old = menu.usage_rows(self.cfg)
        self.meters["openai"] = {"meters": [{"name": "weekly", "used": 100, "window_secs": WEEK}],
                                 "credits": 62469.67, "currency": "CHF"}
        self.draw(28, 30, seats=1)
        new = menu.usage_rows(self.cfg)
        self.meters["openai"] = {"meters": [{"name": "weekly", "used": 31, "window_secs": WEEK}]}
        lines = self.point(28, 30, "ChatGPT", [old] + [new] * 5)
        self.assertTrue(any(re.match(r"  ChatGPT +▰", line) for line in lines), lines)
        self.assertTrue(any("acme-00" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
