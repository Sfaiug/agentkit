"""The usage grid on the `ak` screen shows only subscriptions.

OpenCode's own free models run on a provider its harness reads no meter for: the owner has no
subscription there, so the grid has no row for it, whether its last probe answered or failed,
and the pointer still lights the subscription it is on.  Offline, with invented readings.
"""

from contextlib import redirect_stdout
import io
import json
import time
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import number, said
from agentkit import config, menu, terminal, usage

WEEK = 604800


class SubscriptionsOnly(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.cfg["providers"] = {"anthropic": {"mode": "subscription",
                                               "accounts": ["default", "second"]},
                                 "openai": {"mode": "subscription"},
                                 "opencode": {"mode": "subscription", "name": "OpenCode"}}
        self.cfg["models"]["deepseek-flash-free"] = {
            "harness": "opencode", "model": "opencode/deepseek-v4.1-flash-free",
            "effort": "high", "provider": "opencode"}

    def meter(self, used):
        return {"name": "weekly", "used": used, "resets_at": 136800, "window_secs": WEEK}

    def cache(self, opencode):
        weekly_all = {**self.meter(45), "name": "weekly_all"}
        providers = {"anthropic": {"meters": [weekly_all],
                                   "accounts": {"second": {"meters": [{**weekly_all, "used": 58}]}}},
                     "openai": {"meters": [self.meter(11)]},
                     "opencode": opencode}
        (config.STATE / "usage.json").write_text(
            json.dumps({"fetched_at": 10000, "providers": providers}))

    def draw(self, width):
        out = io.StringIO()
        with patch.object(terminal, "width", return_value=width), redirect_stdout(out):
            menu.draw(self.cfg, [])
        return terminal.plain(out.getvalue())

    def test_a_provider_with_no_meter_has_no_row_and_the_pointer_lights_the_right_one(self):
        meterless = {"meters": [], "error": None, "none": True,
                     "none_reason": "no meter: OpenCode reads none for opencode"}
        failed = {**meterless, "error": "unknown: OpenCode did not answer",
                  "probe_error": "unknown: OpenCode did not answer"}
        for label, opencode in (("answered", meterless), ("failed", failed)):
            with self.subTest(probe=label):
                self.cache(opencode)
                self.assertEqual(sorted(said(self.cfg)), ["ChatGPT", "Claude I", "Claude II"])
                for width in (120, 40):     # the grid, and the readings folded on a narrow screen
                    screen = self.draw(width)
                    self.assertIn("Claude II", screen)
                    self.assertIn("ChatGPT", screen)
                    self.assertNotIn("OpenCode", screen)
                    self.assertNotIn("no meter", screen)
                for shown in ("ChatGPT", "Claude II"):
                    self.assertTrue(terminal.plain(menu.usage_detail(
                        self.cfg, number(self.cfg, shown))).startswith(shown))


if __name__ == "__main__":
    unittest.main()
