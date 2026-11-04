"""AK_BIN's models table says which week shares were measured and what the rest are.

Owner, 3 Nov 2026: a cost on screen must never look more certain than it is. Reuses the
invented lineup and capacity pairs of test_key_picks_priced_in_usage in a temporary HOME.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_key_picks_priced_in_usage as priced

LEGEND = "  week %     a task's share of its subscription's week: measured where the row says"


class MeasuredNote(unittest.TestCase):
    setUp = priced.PicksPricedInUsage.setUp
    command = priced.PicksPricedInUsage.command

    def row(self, table, name, effort):
        return next(line for line in table.splitlines()
                    if f" {name.title()} " in line and f" {effort} " in line)

    def test_only_a_measured_share_says_measured_and_the_legend_says_what_the_rest_are(self):
        table = self.command(["anvil-1", "crown-1"])
        builds = table[table.index("builds"):table.index("reviews")]
        self.assertTrue(self.row(builds, "anvil", "high").endswith("measured"))
        self.assertNotIn("measured", self.row(builds, "anvil", "low"))
        self.assertNotIn("measured", self.row(builds, "crown", "high"))
        self.assertTrue(any(line.startswith(LEGEND) for line in table.splitlines()), table)

    def test_board_dollars_alone_add_no_legend_line(self):
        self.home.write(".agentkit/state/capacity.json", {})
        table = self.command(["anvil-1", "crown-1"])
        self.assertNotIn("week %", table)
        self.assertNotIn("measured", table)


if __name__ == "__main__":
    unittest.main()
