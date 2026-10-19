"""The usage grid on the `ak` screen shows only subscriptions.

OpenCode's own free models run on a provider whose table says `mode = "free"`: the owner has no
subscription there, so the grid has no row for it, whatever its reading says, and the pointer
still lights the subscription it is on.  A subscription whose probe found no meter, as Grok's
can, keeps its row and says so.  Offline, with invented readings.
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
METERLESS = {"meters": [], "error": None, "none": True, "none_reason": "no meter: fixture"}


class SubscriptionsOnly(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.cfg["providers"] = {"anthropic": {"mode": "subscription",
                                               "accounts": ["default", "second"]},
                                 "openai": {"mode": "subscription"},
                                 "xai": {"mode": "subscription"},
                                 "opencode": {"mode": "free", "name": "OpenCode"}}
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
                     "xai": METERLESS,
                     "opencode": opencode}
        (config.STATE / "usage.json").write_text(
            json.dumps({"fetched_at": 10000, "providers": providers}))

    def draw(self, width):
        out = io.StringIO()
        with patch.object(terminal, "width", return_value=width), redirect_stdout(out):
            menu.draw(self.cfg, [])
        return terminal.plain(out.getvalue())

    def test_a_free_provider_has_no_row_and_the_pointer_lights_the_right_one(self):
        failed = {**METERLESS, "error": "unknown: OpenCode did not answer"}
        for label, opencode in (("no meter", METERLESS), ("failed", failed),
                                ("a meter", {"meters": [self.meter(20)]}), ("none", None)):
            with self.subTest(reading=label):
                self.cache(opencode)
                self.assertEqual(sorted(said(self.cfg)),
                                 ["ChatGPT", "Claude I", "Claude II", "Grok"])
                self.assertEqual(said(self.cfg)["Grok"].split(), ["—", "no", "meter"])
                for width in (120, 40):     # the grid, and the readings folded on a narrow screen
                    screen = self.draw(width)
                    for shown in ("Claude II", "ChatGPT", "Grok"):
                        self.assertIn(shown, screen)
                    self.assertNotIn("OpenCode", screen)
                for shown in ("ChatGPT", "Claude II", "Grok"):
                    self.assertTrue(terminal.plain(menu.usage_detail(
                        self.cfg, number(self.cfg, shown))).startswith(shown))


if __name__ == "__main__":
    unittest.main()
