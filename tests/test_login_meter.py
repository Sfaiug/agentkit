"""A subscription whose login ends within a week, or has ended, has an amber meter on the ak
screen, and the line under the grid says whose login it is and when it ends; offline.

`state/logins.json` is written as the tick keeps it (`agentkit/logins.py`), the menu's clock
reads 10000 (`fixtures.sandbox`) and the local time is UTC's.
"""

import json
import os
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import number
from agentkit import config, menu, terminal

DAY = 86400
WEEK = {"name": "weekly", "resets_at": 10000 + 3 * DAY, "window_secs": 604800, "used": 50}


class LoginMeter(Sandbox):
    def setUp(self):
        super().setUp()
        self.cfg["providers"]["anthropic"]["accounts"] = ["default", "second"]
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"accounts": {"default": {"meters": [WEEK]},
                                       "second": {"meters": [WEEK]}}},
            "openai": {"meters": [WEEK]}}}))
        (config.STATE / "logins.json").write_text(json.dumps({
            "anthropic": {"default": {"email": "one@acme.test", "ends": 10000 + 9 * DAY},
                          "second": {"email": "two@acme.test", "ends": 10000 + 3 * DAY}},
            "openai": {"default": {"email": "owner@acme.test", "ends": None}},
            "meta": {"default": {"email": "owner@acme.test", "ends": 9000}}}))
        self.addCleanup(time.tzset)
        for patcher in (patch.object(terminal, "colour_depth", return_value=24),
                        patch.dict(os.environ, {"TZ": "UTC"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        time.tzset()

    def cell(self, label, lit=None):
        """The grid's cell for `label`, as drawn one to a line, as on a phone."""
        return next(line for line in menu.usage_lines(self.cfg, 60, lit)
                    if terminal.plain(line).startswith(label + " "))

    def test_a_login_ending_within_a_week_turns_its_meter_amber_at_rest(self):
        meter = "▰" * 5
        self.assertIn(terminal.styled(meter, "amber"), self.cell("Claude II"))
        # nine days off, or no end written down, it stays grey
        for label in ("Claude I", "ChatGPT"):
            self.assertNotIn(terminal.styled(meter, "amber"), self.cell(label))
            self.assertIn(meter + terminal.styled("▱" * 5, "dim"), self.cell(label))
        # a login that ended, on a subscription with no reading to draw, says so in amber
        self.assertIn(terminal.styled("—", "amber")[:-4], self.cell("Muse"))
        # under the pointer the meter is its company's colour, as every other one is
        second = number(self.cfg, "Claude II")
        lit = self.cell("Claude II", second)
        self.assertNotIn(terminal.styled(meter, "amber"), lit)
        self.assertIn(terminal.styled(meter, menu.colour(self.cfg, "anthropic")), lit)

    def test_b_the_line_under_the_pointer_says_whose_login_and_when_it_ends(self):
        detail = menu.usage_detail(self.cfg, number(self.cfg, "Claude II"), 120)
        self.assertIn(terminal.styled("login two@acme.test ends Sun 04 Jan 02:46 (in 3 days)",
                                      "amber"), detail)
        ended = terminal.plain(menu.usage_detail(self.cfg, number(self.cfg, "Muse"), 120))
        self.assertIn("login owner@acme.test ended Thu 01 Jan 02:30", ended)
        for label in ("Claude I", "ChatGPT"):
            self.assertNotIn("login", terminal.plain(
                menu.usage_detail(self.cfg, number(self.cfg, label), 120)))


if __name__ == "__main__":
    unittest.main()
