"""The usage rows read live, in each company's colour, in rainbow order; offline.

No row, heading or note says how old a reading is, however old it is.  Each bar's filled cells
take its provider's colour -- a `colour` key on the provider, else the shipped one, else the
accent -- and its empty cells stay dim; the rows run red through violet by that colour's hue,
the near-greys last; and a terminal without truecolor gets the nearest colour it has.
"""

import json
import re
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, menu, terminal, usage

WEEK = 604800
SIX = {"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#FCFCFC",
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

    def rows(self, width=100, depth=0):
        with patch.object(terminal, "colour_depth", return_value=depth):
            return menu.usage_lines(self.cfg, width)[1:]

    def test_no_row_heading_or_note_says_how_old_its_reading_is(self):
        # Hours old, from before anybody dated a reading, and refused on the last probe: the
        # rows are the same rows, the refusal says so in its own words, and nothing says `old`.
        providers = {name: {"meters": [self.meter(50)], "fetched_at": 10000 - 7200,
                            "probed_at": 10000 - 7200} for name in SIX}
        providers["meta"] = {"meters": [self.meter(50)], "fetched_at": None}
        providers["anthropic"].update(probe_error="unknown: HTTP 429 from api.anthropic.com",
                                      stale_since=10000 - 3600)
        for fetched_at in (10000, 10000 - usage.CACHE_TTL - 1, 10000 - 7200, None):
            self.cache(providers, fetched_at)
            for width in (170, 40):
                lines = menu.usage_lines(self.cfg, width)
                self.assertEqual(lines[0], "  usage left")
                self.assertNotRegex("\n".join(lines), r"\bold\b|age unknown", lines)
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
            self.assertRegex(self.rows()[0], r"50% left · resets \w+ \d\d:\d\d · rate limited$")
        with patch.object(terminal, "width", return_value=170), \
                patch.object(usage, "review_pair", return_value=None):
            read = {name: {**prov, "meters": [{**self.meter(50), "elapsed": 50, "pace": 0}]}
                    for name, prov in providers.items()}
            rendered = usage.render(self.cfg, usage._gate_flags(read, 10000, self.cfg), [])
        self.assertIn("note: anthropic rate limited: HTTP 429 from api.anthropic.com", rendered)
        self.assertNotRegex(rendered, r"\bold\b|last reading")

    def test_the_six_companies_fill_their_bars_in_their_own_colours(self):
        for name, rgb in SIX.items():
            self.assertEqual(menu.colour(self.cfg, name), rgb)
        rows = self.rows(depth=24)
        dim = "\033[2;38;2;108;112;134m░░░░░░\033[0m"
        for label, rgb in (("Claude", SIX["anthropic"]), ("MiMo", SIX["mimo"]),
                           ("Muse", SIX["meta"]), ("Gemini", SIX["google"]),
                           ("ChatGPT", SIX["openai"]), ("Grok", SIX["xai"])):
            row = next(row for row in rows if terminal.plain(row).split()[0] == label)
            red, green, blue = (int(rgb[i:i + 2], 16) for i in (1, 3, 5))
            # half a week left: six filled cells in the company's colour, six empty ones dim
            self.assertIn(f"\033[38;2;{red};{green};{blue}m██████\033[0m{dim}", row)

    def test_rows_run_red_through_violet_and_the_greys_come_last(self):
        labels = [terminal.plain(row).split()[0] for row in self.rows()]
        self.assertEqual(labels, ["Claude", "MiMo", "Muse", "Gemini", "ChatGPT", "Grok"])
        # the order is the colour's, not the config's: a provider's own `colour` moves it
        self.cfg["providers"]["openai"]["colour"] = "#8000FF"          # violet, after blue
        self.cfg["providers"]["anthropic"]["colour"] = "#C8C8C0"       # a darker near-grey
        labels = [terminal.plain(row).split()[0] for row in self.rows()]
        # the greys lightest first: #FFFFFF, #FCFCFC, then #C8C8C0
        self.assertEqual(labels, ["MiMo", "Muse", "Gemini", "ChatGPT", "Grok", "Claude"])
        # and a row with nothing to draw keeps its place all the same
        self.cache({"meta": {"meters": [self.meter(50)]}})
        rows = self.rows()
        self.assertEqual([terminal.plain(row).split()[0] for row in rows],
                         ["MiMo", "Muse", "Gemini", "ChatGPT", "Grok", "Claude"])
        self.assertEqual(terminal.plain(rows[0]).split(), ["MiMo", "—", "no", "reading", "yet"])

    def test_an_unknown_provider_is_drawn_in_the_accent(self):
        self.cfg["providers"]["acme"] = {"mode": "payg"}
        self.cache({"acme": {"meters": [self.meter(50)]}})
        self.assertEqual(menu.colour(self.cfg, "acme"), "accent")
        row = next(row for row in self.rows(depth=24) if "Acme" in row)
        self.assertIn("\033[38;2;137;180;250m██████\033[0m", row)   # the accent's own colour
        # it sorts by the accent's hue, among the blues
        labels = [terminal.plain(row).split()[0] for row in self.rows()]
        self.assertEqual(labels.index("Acme"), labels.index("Muse") + 1)
        # a colour that is not `#RRGGBB` is no colour: the shipped one, else the accent, stands
        self.cfg["providers"]["acme"]["colour"] = "blue"
        self.cfg["providers"]["anthropic"]["colour"] = "#D9775"
        self.assertEqual(menu.colour(self.cfg, "acme"), "accent")
        self.assertEqual(menu.colour(self.cfg, "anthropic"), SIX["anthropic"])
        self.cfg["providers"]["acme"]["colour"] = "#00ff00"
        self.assertEqual(menu.colour(self.cfg, "acme"), "#00ff00")

    def test_a_terminal_without_truecolor_gets_the_nearest_it_has(self):
        rows = self.rows(depth=256)
        claude = next(row for row in rows if "Claude" in row)
        self.assertIn("\033[38;5;173m██████\033[0m", claude)       # #D97757 -> 215,135,95
        self.assertIn("\033[2;38;5;243m░░░░░░\033[0m", claude)     # the empty cells stay dim
        self.assertEqual(terminal.xterm_colour("3E9EFB"), 75)
        self.assertIn("\033[38;5;75m██████", next(row for row in rows if "Muse" in row))
        # eight colours: each channel on where it is nearer full than off
        rows = self.rows(depth=8)
        for label, tone in (("Claude", 31), ("MiMo", 33), ("Muse", 36), ("Gemini", 34),
                            ("ChatGPT", 37), ("Grok", 37)):
            row = next(row for row in rows if terminal.plain(row).split()[0] == label)
            self.assertIn(f"\033[{tone}m██████\033[0m\033[2m░░░░░░\033[0m", row)
        # and none at all is the plain bar
        self.assertNotIn("\033", "".join(self.rows(depth=0)))
        self.assertTrue(re.search(r"Claude\s+█{6}░{6}\s+50% left", self.rows()[0]))


if __name__ == "__main__":
    unittest.main()
