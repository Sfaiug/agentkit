"""v5ai: the usage bars are one column at every width; offline.

Five providers where Claude carries ``Fable 41%``, ChatGPT is spent and says
``resets Mon 12:00`` and Muse's reading is 22 minutes old and says nothing of it -- Grok
and MiMo, meterless, draw no bar and are skipped where bars are reasoned about -- rendered
through ``menu.usage_lines`` with a fake usage record and a pinned clock.  A phone at 40
columns has room for the short notes only, and the bar gives way to make it;
60 columns is where a note and a bar have to share one.
"""

import json
import os
import re
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, terminal, usage

NOW = 1789747980  # 2026-09-18 16:13 UTC, the live menu in the report
RESETS_AT = 1789992000  # 2026-09-21 12:00 UTC -> `back 21 Sep`
DAY = 86400


def providers():
    return {
        "anthropic": {"meters": [
            {"name": "weekly_all", "used": 2, "resets_at": NOW + 3 * DAY,
             "window_secs": 604800},
            {"name": "weekly_scoped", "used": 59, "resets_at": NOW + 3 * DAY,
             "window_secs": 604800}]},
        "openai": {"meters": [
            {"name": "weekly", "used": 100, "resets_at": RESETS_AT,
             "window_secs": 604800}], "resets": 0},
        "meta": {"meters": [
            {"name": "weekly", "used": 55, "resets_at": NOW + 3 * DAY,
             "window_secs": 604800}], "fetched_at": NOW - 22 * 60},
    }


class UsageBars(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": NOW, "providers": providers()}))

    def lines(self, width):
        return menu.usage_lines(self.cfg, width)

    @staticmethod
    def bar_cells(line):
        bar = re.search(r"[█░]+", terminal.plain(line))
        return terminal.cells(bar.group(0)) if bar else 0

    def bars(self, lines):
        """The rows that draw a bar: the meterless rows carry none."""
        return [line for line in lines[1:] if self.bar_cells(line)]

    def test_v5ai_a_bars_share_one_width_at_40(self):
        lines = self.lines(40)
        self.assertEqual(len(lines), 7)
        # The bar gives way first, so a phone keeps every note it has room for: the short
        # ones stay even where `resets Mon 16:13` will never fit, and one note too long for
        # the room never takes a shorter one with it.
        self.assertIn("Fable 41%", lines[1])
        self.assertNotIn("old", lines[3])
        self.assertIn("no reading yet", lines[2])
        self.assertIn("no reading yet", lines[4])
        self.assertIn("no reading yet", lines[6])
        for line in self.bars(lines):
            self.assertNotIn("resets", line)
            self.assertLess(self.bar_cells(line), 12, lines)
        widths = [self.bar_cells(line) for line in self.bars(lines)]
        self.assertEqual(len(set(widths)), 1, lines)
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines), lines)

    def test_v5ai_b_shared_is_widest_fitting_and_at_least_four(self):
        lines = self.lines(60)
        shared = self.bar_cells(lines[1])
        self.assertGreaterEqual(shared, 4)
        # The row with the least room fills the width, so one more cell would not fit.
        self.assertEqual(max(terminal.cells(line) for line in lines[1:]), 60, lines)
        for line in lines[1:]:
            self.assertLessEqual(terminal.cells(line), 60, lines)
        self.assertEqual(len({self.bar_cells(line) for line in self.bars(lines)}), 1, lines)

    def test_v5ai_c_bars_are_full_width_at_100(self):
        lines = self.lines(100)
        for line in self.bars(lines):
            self.assertEqual(self.bar_cells(line), 12, lines)
        self.assertIn("98% left · resets Mon 16:13 · Fable 41%", lines[1])
        self.assertIn("0% left · resets Mon 12:00", lines[5])
        self.assertTrue(lines[3].endswith("45% left · resets Mon 16:13"), lines)
        self.assertIn("no reading yet", lines[2])
        self.assertIn("no reading yet", lines[4])
        self.assertIn("no reading yet", lines[6])

    def test_v5ai_d_fixtures_match_byte_for_byte(self):
        for width in (40, 100):
            lines = self.lines(width)
            self.assertEqual("\n".join(lines) + "\n",
                             (REPO / f"tests/fixtures/v5ai-{width}.txt").read_text())

    def test_v5ai_e_note_gives_way_before_bar_shrinks_below_four(self):
        errored = {
            "anthropic": {"meters": [
                {"name": "weekly_all", "used": 9, "resets_at": NOW + 3 * DAY,
                 "window_secs": 604800},
                {"name": "weekly_scoped", "used": 9, "resets_at": NOW + 3 * DAY,
                 "window_secs": 604800}]},
            "openai": {"meters": [
                {"name": "weekly", "used": 31, "resets_at": NOW + 3 * DAY,
                 "window_secs": 604800}], "resets": 0},
            "meta": {"meters": [
                {"name": "weekly", "used": 40, "resets_at": NOW + 3 * DAY,
                 "window_secs": 604800}], "error": "offline", "fetched_at": None},
        }
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": NOW, "providers": errored}))
        lines = self.lines(70)
        # The fault fits beside the reset, so every bar stays full width, and the
        # adapter's words lose their `unknown:`.
        for line in self.bars(lines):
            self.assertEqual(self.bar_cells(line), 12, lines)
        self.assertTrue(lines[3].endswith("60% left · resets Mon 16:13 · ? offline"), lines)
        self.assertNotIn("unknown", lines[3])
        # The healthy rows are byte-identical to a draw without the error.
        fresh = {**errored, "meta": {"meters": errored["meta"]["meters"]}}
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": NOW, "providers": fresh}))
        plain = self.lines(70)
        self.assertEqual(lines[1], plain[1])
        self.assertEqual(lines[5], plain[5])

    def test_v5ai_f_bars_share_one_width_and_fit_below_forty(self):
        for width in (28, 32, 36):
            lines = self.lines(width)
            widths = [self.bar_cells(line) for line in self.bars(lines)]
            self.assertEqual(len(set(widths)), 1, (width, lines))
            self.assertTrue(all(terminal.cells(line) <= width for line in lines),
                            (width, lines))


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixtures"]:
        test = UsageBars()
        test.setUp()
        try:
            for width in (40, 100):
                (REPO / f"tests/fixtures/v5ai-{width}.txt").write_text(
                    "\n".join(test.lines(width)) + "\n")
        finally:
            test.doCleanups()
    else:
        unittest.main(verbosity=2)
