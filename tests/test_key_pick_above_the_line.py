"""AK_BIN picks the executor frontier row farthest above its cheapest-to-best line.
Only `ak models --json` is observed, with invented boards in a temporary HOME.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, EVALUATIONS, aa, boards

# Quality is 100 less the share's gap from .90, in hundredths. The value row is
# 35 points above the line, versus about 24 for near and 8.45 for small.
ROWS = [("acme-base-1", .40, .000001), ("acme-small-1", .485, .1),
        ("acme-mid-1", .53, .5), ("acme-rise-1", .62, 2),
        ("acme-value-1", .80, 10), ("acme-near-1", .89, 50), ("acme-best-1", .90, 100)]


class PickAboveTheLine(unittest.TestCase):
    def pick(self, rows):
        with Home() as home:
            fake = fakeadapter.install(home, claude="pass")["claude"]
            fake.answer("models", "".join(f"{name}\t{name}\thigh\n" for name, *_ in rows))
            akconfig.write(home, {name: {"harness": "claude", "model": name}
                                  for name, *_ in rows})
            held = boards()
            for board in held.values():
                board["rows"] = [row for row in board["rows"] if row["model"] == "Old 1"]
            for name, share, cost in rows:
                held["artificialanalysis.ai"]["rows"].append(aa(name, name, "high", {
                    "aa.intelligenceIndex": 50, "aa.frontierCode20": share,
                    "aa.terminalBench40": share,
                    **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost
                       for slug in EVALUATIONS}}))
                held["arena.ai"]["rows"].append({"model": name, "effort": "high",
                                                "values": {"arena.agent": share}})
            home.write(".agentkit/state/boards.json", held)
            done = home.ak("models", "--json", env=ENV)
            self.assertEqual(done.code, 0, done.err)
            front = json.loads(done.out)["execute"]["front"]
            return next(row["release"] for row in front if "pick" in row["notes"])

    def test_a_free_row_at_the_cheap_end_leaves_the_pick_unchanged(self):
        chosen = self.pick(ROWS)
        for cost in (0, 1e-12):
            with self.subTest(cost=cost):
                self.assertEqual(self.pick([("acme-free-1", .30, cost), *ROWS]), chosen)

    def test_the_farthest_row_wins_over_the_cheapest_and_the_best(self):
        self.assertEqual(self.pick(ROWS), "acme-value-1")

    def test_removing_any_of_the_four_cheapest_rows_keeps_the_pick(self):
        for n in range(4):
            with self.subTest(removed=ROWS[n][0]):
                self.assertEqual(self.pick(ROWS[:n] + ROWS[n + 1:]), "acme-value-1")


if __name__ == "__main__":
    unittest.main()
