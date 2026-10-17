"""The usage rows read live, in the rainbow order of each company's colour; offline.

No row, heading or note says how old a reading is, however old it is.  Each provider has its
colour -- a `colour` key on the provider, else the shipped one, else the accent -- and the rows
run red through violet by its hue, the near-greys last; the meter under the pointer is that colour
(tests/test_palette.py), its empty cells stay dim, and a terminal without truecolor gets the
nearest colour it has.
"""

import json
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from fixtures.subscriptions import said
from agentkit import config, menu, terminal, usage

WEEK = 604800
SIX = {"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#736CD3",
       "google": "#203B9B", "mimo": "#FB8046"}


class UsageColours(Sandbox):
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
        self.assertRegex(rendered, r"note: anthropic as of (\w+ )?\d\d:\d\d")
        self.assertNotRegex(rendered, r"\bold\b|last reading")

    def test_the_six_companies_have_their_own_colours(self):
        for name, rgb in SIX.items():
            self.assertEqual(menu.colour(self.cfg, name), rgb)

    def test_rows_run_red_through_violet_and_the_greys_come_last(self):
        self.assertEqual(self.labels(), ["Claude", "MiMo", "Muse", "Gemini", "Grok", "ChatGPT"])
        # the order is the colour's, not the config's: a provider's own `colour` moves it
        self.cfg["providers"]["anthropic"]["colour"] = "#C8C8C0"       # a darker near-grey
        # the greys lightest first: #FFFFFF, then #C8C8C0
        self.assertEqual(self.labels(), ["MiMo", "Muse", "Gemini", "Grok", "ChatGPT", "Claude"])
        # and a row with nothing to draw keeps its place all the same
        self.cache({"meta": {"meters": [self.meter(50)]}})
        self.assertEqual(self.labels(), ["MiMo", "Muse", "Gemini", "Grok", "ChatGPT", "Claude"])
        self.assertEqual(said(self.cfg)["MiMo"], "—  no reading yet")

    def test_an_unknown_provider_is_drawn_in_the_accent(self):
        self.cfg["providers"]["acme"] = {"mode": "payg"}
        self.cache({"acme": {"meters": [self.meter(50)]}})
        self.assertEqual(menu.colour(self.cfg, "acme"), "accent")
        # it sorts by the accent's hue, among the blues
        self.assertEqual(self.labels().index("Acme"), self.labels().index("Muse") + 1)
        # a colour that is not `#RRGGBB` is no colour: the shipped one, else the accent, stands
        self.cfg["providers"]["acme"]["colour"] = "blue"
        self.cfg["providers"]["anthropic"]["colour"] = "#D9775"
        self.assertEqual(menu.colour(self.cfg, "acme"), "accent")
        self.assertEqual(menu.colour(self.cfg, "anthropic"), SIX["anthropic"])
        self.cfg["providers"]["acme"]["colour"] = "#00ff00"
        self.assertEqual(menu.colour(self.cfg, "acme"), "#00ff00")

    def test_a_terminal_without_truecolor_gets_the_nearest_it_has(self):
        self.assertEqual(terminal.xterm_colour("D97757"), 173)      # a company's, on `c`
        self.assertEqual(terminal.xterm_colour("3E9EFB"), 75)
        # eight colours: a company's, each channel on where it is nearer full than off
        for name, tone in (("anthropic", 31), ("mimo", 33), ("meta", 36), ("google", 34),
                           ("openai", 37), ("xai", 34)):
            self.assertEqual(terminal.basic_colour(SIX[name][1:]), str(tone))


if __name__ == "__main__":
    unittest.main()
