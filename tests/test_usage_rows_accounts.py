"""Every subscription has its own usage row, and each row shows its 5-hour window.

A provider that lists `accounts` gets one row per account in config order -- the usual
provider's name numbered in roman numerals, `Claude I` and `Claude II` -- each from its own
reading, and a provider with one login is its name alone.  A row
whose account reports a 5-hour window carries `5h 40% left`, or `5h spent until 14:00`
once that window reads 100% used.  Offline, with invented readings.
"""

import json
import re
import time
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, menu, terminal, usage

NOW = 10000                   # the clock the Sandbox pins; a Thursday
WEEK_RESET = 136800           # 1970-01-02 14:00:00 UTC -> `resets Fri 14:00`
WEEK_RESET2 = 205200          # 1970-01-03 09:00:00 UTC -> `resets Sat 09:00`
SESSION_RESET = 13600         # 1970-01-01 03:46:40 UTC -> `until 03:46`
SESSION_SPENT = 17200         # 1970-01-01 04:46:40 UTC -> `until 04:46`
WEEK = 604800
SESSION = 18000


class UsageRowsAccounts(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.cfg["providers"] = {"anthropic": {"mode": "subscription",
                                               "accounts": ["default", "second"]},
                                 "openai": {"mode": "subscription"}}
        self.cache(self.providers())

    def meter(self, name, used, resets_at=WEEK_RESET, window=WEEK):
        return {"name": name, "used": used, "resets_at": resets_at, "window_secs": window}

    def providers(self, **replace):
        default = {"meters": [self.meter("weekly_all", 48),
                              self.meter("weekly_scoped", 59),
                              self.meter("session", 60, SESSION_RESET, SESSION)]}
        second = {"meters": [self.meter("weekly_all", 20, WEEK_RESET2),
                             self.meter("session", 100, SESSION_SPENT, SESSION)]}
        found = {"anthropic": {"accounts": {"default": default, "second": second},
                               # the worker turn's account, as today: no row reads it now
                               "meters": [self.meter("weekly_all", 99)],
                               "account": "second"},
                 "openai": {"meters": [self.meter("weekly", 31)]},
                 "meta": {"meters": [self.meter("weekly", 10)]},
                 "xai": {"meters": [self.meter("weekly", 10)]},
                 "mimo": {"meters": [self.meter("weekly", 10)]},
                 "google": {"meters": [self.meter("weekly", 10)]}}
        found.update(replace)
        return found

    def cache(self, providers, fetched_at=NOW):
        (config.STATE / "usage.json").write_text(
            json.dumps({"fetched_at": fetched_at, "providers": providers}))

    def rows(self, width=100):
        return [terminal.plain(line) for line in menu.usage_lines(self.cfg, width)]

    @staticmethod
    def bar_cells(line):
        found = re.search(r"[█░]+", line)
        return terminal.cells(found.group(0)) if found else 0

    def test_one_row_per_account_in_config_order(self):
        rows = self.rows()
        self.assertEqual(len(rows), 4, rows)
        self.assertTrue(rows[1].startswith("Claude I ") and "52% left" in rows[1], rows)
        self.assertTrue(rows[2].startswith("Claude II ") and "80% left" in rows[2], rows)
        self.assertTrue(rows[3].startswith("ChatGPT ") and "ChatGPT I" not in rows[3], rows)
        # ... and the order and the numbers are the config's, not the logins':
        self.cfg["providers"]["anthropic"]["accounts"] = ["second", "default"]
        rows = self.rows()
        self.assertTrue(rows[1].startswith("Claude I ") and "80% left" in rows[1], rows)
        self.assertTrue(rows[2].startswith("Claude II ") and "52% left" in rows[2], rows)
        # ... and the account's own name is never shown
        self.assertFalse(any("second" in row or "default" in row for row in rows), rows)

    def test_each_row_draws_its_own_reading(self):
        rows = self.rows()
        self.assertIn("52% left · resets Fri 14:00", rows[1])
        self.assertIn("80% left · resets Sat 09:00", rows[2])
        # everything a row shows today, per account: the scoped cap, the fault, the 5h
        self.assertIn("Fable 41%", rows[1])
        self.assertNotIn("Fable", rows[2])
        self.assertNotIn("1% left", "\n".join(rows))   # the top-level worker-turn reading
        # a fault on one account stays on its row
        cached = self.providers()
        cached["anthropic"]["accounts"]["second"]["error"] = "unknown: wobble"
        self.cache(cached)
        rows = self.rows()
        self.assertIn("? wobble", rows[2])
        self.assertNotIn("wobble", rows[1])
        # ... and an account with no reading is `—` while the other keeps its bar
        cached["anthropic"]["accounts"]["second"] = {}
        self.cache(cached)
        rows = self.rows()
        self.assertRegex(rows[1], r"Claude I\s+[█░]+\s+52% left")
        self.assertEqual(rows[2].split(), ["Claude", "II", "—", "no", "reading", "yet"])

    def test_a_provider_without_accounts_keeps_its_single_row(self):
        rows = self.rows()
        chat = [row for row in rows if row.startswith("ChatGPT")]
        self.assertEqual(len(chat), 1, rows)
        self.assertIn("69% left · resets Fri 14:00", chat[0])
        self.assertNotIn("5h", chat[0])   # no 5-hour window reported, no note

    def test_a_five_hour_window_says_what_is_left_of_it(self):
        rows = self.rows()
        self.assertIn("5h 40% left", rows[1])
        self.assertIn("5h spent until 04:46", rows[2])

    def test_the_spent_note_ranks_first_so_it_survives(self):
        notes = [(0, "resets Fri 14:00"), (3, "Fable 41%"),
                 (-1, "5h spent until 04:46"), (1, "rate limited")]
        self.assertEqual(menu.fitting(notes, 20), ["5h spent until 04:46"])
        # at a width where only one note fits, the spent 5h is the one kept
        rows = self.rows(60)
        self.assertIn("5h spent until 04:46", rows[2])
        self.assertNotIn("resets", rows[2])

    def test_rows_fit_and_share_one_bar_at_40_100_and_170(self):
        for width in (40, 100, 170):
            lines = menu.usage_lines(self.cfg, width)
            self.assertTrue(all(terminal.cells(line) <= width for line in lines), (width, lines))
            bars = [line for line in lines[1:] if self.bar_cells(terminal.plain(line))]
            self.assertTrue(bars, (width, lines))
            self.assertEqual(len({self.bar_cells(terminal.plain(line)) for line in bars}), 1,
                             (width, lines))
            if width >= 100:
                plain = [terminal.plain(line) for line in lines]
                self.assertIn("5h 40% left", plain[1])
                self.assertIn("5h spent until 04:46", plain[2])


if __name__ == "__main__":
    unittest.main()
