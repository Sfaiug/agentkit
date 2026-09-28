"""A usage row says how old its reading is, never `rate limited`; offline.

Invented readings in a temporary HOME: a reading older than half an hour carries
`as of HH:MM` on its menu row and under `ak usage`, with the weekday when it is not
from today; a fresher one, and a refusal of any age, say nothing at all.
"""

import json
import time
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, menu, terminal, usage

NOW = 10000                # the clock the Sandbox pins; 1970-01-01 02:46:40 UTC, a Thursday
OLD = NOW - 3600           # an hour ago, the same day -> `as of 01:46`
AWAY = NOW - 86400         # the day before -> `as of Wed 02:46`
WEEK = 604800


class UsageRowAge(Sandbox):
    def setUp(self):
        super().setUp()
        # Local time is UTC here, so a pinned reading timestamp reads the same on every machine.
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.cfg["providers"]["acme"] = {"mode": "subscription"}

    def meter(self, used=40, resets_at=NOW + 3 * 86400):
        return {"name": "weekly", "used": used, "resets_at": resets_at, "window_secs": WEEK,
                "elapsed": 50.0, "pace": -10.0}

    def cache(self, prov):
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": NOW, "providers": {"acme": prov}}))

    def row(self, width=100):
        rows = [terminal.plain(line) for line in menu.usage_lines(self.cfg, width)]
        return next(line for line in rows if line.split()[0] == "Acme")

    def rendered(self, prov):
        with patch.object(terminal, "width", return_value=170), \
                patch.object(usage, "review_pair", return_value=None):
            return usage.render(self.cfg, {"acme": prov}, [])

    def test_an_old_reading_carries_as_of_on_its_menu_row(self):
        self.cache({"meters": [self.meter()], "fetched_at": OLD})
        self.assertRegex(self.row(), r"60% left · resets \w+ \d\d:\d\d · as of 01:46$")
        self.assertNotRegex(self.row(), "rate limited|unavailable")
        with patch.object(terminal, "colour_depth", return_value=8):
            [line] = [line for line in menu.usage_lines(self.cfg, 100) if "Acme" in line]
        self.assertIn("\033[2mas of 01:46\033[0m", line)   # the age note is dim, like each note
        # `ak usage` says the same words under its table.
        self.assertRegex(self.rendered({"meters": [self.meter()], "fetched_at": OLD}),
                         r"note: acme as of 01:46")

    def test_a_reading_from_another_day_names_the_weekday(self):
        self.cache({"meters": [self.meter()], "fetched_at": AWAY})
        self.assertRegex(self.row(), r"60% left · resets \w+ \d\d:\d\d · as of Wed 02:46$")
        self.assertRegex(self.rendered({"meters": [self.meter()], "fetched_at": AWAY}),
                         r"note: acme as of Wed 02:46")

    def test_a_reading_half_an_hour_old_or_less_says_nothing(self):
        for taken in (NOW - 60, NOW - usage.AS_OF_AFTER, NOW + 600):
            self.cache({"meters": [self.meter()], "fetched_at": taken})
            self.assertRegex(self.row(), r"60% left · resets \w+ \d\d:\d\d$")
            self.assertNotIn("as of", self.row())
            self.assertNotIn("note: acme",
                             self.rendered({"meters": [self.meter()], "fetched_at": taken}))

    def test_probed_at_counts_only_where_fetched_at_is_absent(self):
        # No reading ever wrote `fetched_at` down: the last ask's moment stands in.
        self.cache({"meters": [self.meter()], "probed_at": OLD})
        self.assertRegex(self.row(), r"as of 01:46$")
        # But a reading that wrote it -- none, or nothing numeric -- has no age to say,
        # whatever the last ask's moment was.
        for taken in (None, "soon"):
            self.cache({"meters": [self.meter()], "fetched_at": taken, "probed_at": OLD})
            self.assertNotIn("as of", self.row())
            self.assertRegex(self.row(), r"60% left · resets \w+ \d\d:\d\d$")

    def test_a_refusal_says_nothing_fresh_or_old(self):
        for taken, tail in ((NOW - 60, r"60% left · resets \w+ \d\d:\d\d$"),
                            (OLD, r"60% left · resets \w+ \d\d:\d\d · as of 01:46$")):
            for error in ("unknown: HTTP 429 from api.acme.example/usage",
                          "unknown: HTTP 503 from api.acme.example/usage"):
                prov = {"meters": [self.meter()], "fetched_at": taken, "probe_error": error,
                        "stale_since": taken}
                self.cache(prov)
                self.assertRegex(self.row(), tail)
                self.assertNotRegex(self.row(), "rate limited|unavailable|no login")
                self.assertNotRegex(self.rendered(prov), "rate limited|unavailable")
        # A fault still wins the note's place: the adapter's own line, and no age beside it.
        prov = {"meters": [self.meter()], "fetched_at": OLD, "error": "unknown: offline"}
        self.cache(prov)
        self.assertIn("? offline", self.row())
        self.assertNotIn("as of", self.row())
        self.assertIn("note: acme unknown: offline", self.rendered(prov))

    def test_a_phone_width_row_keeps_the_age_note(self):
        self.cache({"meters": [self.meter()], "fetched_at": OLD})
        row = self.row(40)
        self.assertIn("as of 01:46", row)      # the short note stays, as the refusal's own did
        self.assertNotIn("resets", row)        # ... and the long one gives way on its own
        self.assertLessEqual(terminal.cells(row), 40)
        self.assertIn("resets", self.row(100))

    def test_a_rolled_window_and_no_reading_keep_their_own_words(self):
        past = {**self.meter(), "resets_at": NOW - 1}
        self.cache({"meters": [past], "fetched_at": OLD})
        self.assertEqual(self.row().split(), ["Acme", "—", "window", "reset"])
        self.cache({"meters": [], "probe_error": "unknown: HTTP 429 from api.acme.example"})
        self.assertEqual(self.row().split(), ["Acme", "—", "no", "reading", "yet"])


if __name__ == "__main__":
    unittest.main()
