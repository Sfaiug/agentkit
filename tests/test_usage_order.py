"""The usage rows read live, in the order config.toml names their providers; offline.

No row, heading or note says how old a reading is; a provider's `colour` loads and moves nothing.
"""

import json
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import said
from agentkit import config, menu, terminal, usage

WEEK = 604800
SIX = ("anthropic", "openai", "meta", "xai", "google", "mimo")      # as config.default.toml has them


class UsageOrder(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.cfg["providers"]["google"] = {"mode": "subscription"}
        self.cache({name: {"meters": [self.meter(50)]} for name in SIX})

    @staticmethod
    def meter(used):
        return {"name": "weekly", "used": used, "resets_at": 10000 + 3 * 86400,
                "window_secs": WEEK}

    def cache(self, providers, fetched_at=10000):
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": fetched_at, "providers": providers}))

    def labels(self):
        return [label for _, label, _, _ in menu.usage_cells(self.cfg)]

    def test_no_row_heading_or_note_says_how_old_its_reading_is(self):
        # Hours old, from before anybody dated a reading, and refused on the last probe: the
        # rows are the same rows, the old reading says when it was taken, and nothing says `old`.
        providers = {name: {"meters": [self.meter(50)], "fetched_at": 10000 - 7200,
                            "probed_at": 10000 - 7200} for name in SIX}
        providers["meta"] = {"meters": [self.meter(50)], "fetched_at": None}
        providers["anthropic"].update(probe_error="unknown: HTTP 429 from api.anthropic.com",
                                      stale_since=10000 - 3600)
        for fetched_at in (10000, 10000 - usage.CACHE_TTL - 1, 10000 - 7200, None):
            self.cache(providers, fetched_at)
            for width in (170, 40):
                lines = menu.usage_lines(self.cfg, width)
                self.assertNotRegex("\n".join(lines), r"\bold\b|age unknown", lines)
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
            self.assertRegex(said(self.cfg)["Claude"],
                             r"50% left · resets \w+ \d\d:\d\d · as of (\w+ )?\d\d:\d\d$")
        with patch.object(terminal, "width", return_value=170), \
                patch.object(usage, "review_pair", return_value=None):
            read = {name: {**prov, "meters": [{**self.meter(50), "elapsed": 50, "pace": 0}]}
                    for name, prov in providers.items()}
            rendered = usage.render(self.cfg, usage._gate_flags(read, 10000, self.cfg), [])
        self.assertRegex(rendered, r"note: Claude as of (\w+ )?\d\d:\d\d")
        self.assertNotRegex(rendered, r"\bold\b|last reading")

    def test_rows_run_in_the_order_config_names_their_providers(self):
        self.assertEqual(self.labels(), ["Claude", "ChatGPT", "Muse", "Grok", "Gemini", "MiMo"])
        # one named first is drawn first, and one config.toml still gives a `colour` stays put
        providers = self.cfg["providers"]
        self.cfg["providers"] = {"google": providers.pop("google"), **providers}
        self.cfg["providers"]["anthropic"]["colour"] = "#C8C8C0"
        self.assertEqual(self.labels(), ["Gemini", "Claude", "ChatGPT", "Muse", "Grok", "MiMo"])
        # and a row with nothing to draw keeps its place all the same
        self.cache({"meta": {"meters": [self.meter(50)]}})
        self.assertEqual(self.labels(), ["Gemini", "Claude", "ChatGPT", "Muse", "Grok", "MiMo"])
        self.assertEqual(said(self.cfg)["MiMo"], "—  no reading yet")


if __name__ == "__main__":
    unittest.main()
