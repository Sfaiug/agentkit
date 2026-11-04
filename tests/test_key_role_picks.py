"""AK_BIN's role recommendations follow mistake cost, with no configurable quality window.
An invented lineup in a temporary HOME; only `ak models --json` is observed.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, EVALUATIONS, aa, boards

# Every role has qualities 70, 90, 99, 100: the first bend's price-per-point grows
# 106.7 times, the next's 9.375 times. Only the latter cannot be told from the best.
ROWS = [("acme-base-1", .60, 1), ("acme-bend-1", .80, 2),
        ("acme-near-1", .89, 50), ("acme-best-1", .90, 100)]


class RolePicks(unittest.TestCase):
    def test_each_role_picks_by_what_its_mistakes_cost_and_ignores_within(self):
        with Home() as home:
            fake = fakeadapter.install(home, claude="pass")["claude"]
            fake.answer("models", "".join(f"{name}\t{name}\thigh\n" for name, *_ in ROWS))
            models = {name: {"harness": "claude", "model": name} for name, *_ in ROWS}
            held = boards()
            for board in held.values():
                board["rows"] = [row for row in board["rows"] if row["model"] == "Old 1"]
            for name, share, cost in ROWS:
                held["artificialanalysis.ai"]["rows"].append(aa(name, name, "high", {
                    "aa.intelligenceIndex": 50, "aa.frontierCode20": share,
                    "aa.terminalBench40": share, "aa.omniscience": 100 * share,
                    "aa.automationBenchPartialScore": share,
                    **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost
                       for slug in EVALUATIONS}}))
                held["arena.ai"]["rows"].append({"model": name, "effort": "high",
                                                "values": {"arena.agent": share}})
            home.write(".agentkit/state/boards.json", held)
            answers = []
            for settings in ({}, {"within": 1}):
                akconfig.write(home, models, settings=settings)
                done = home.ak("models", "--json", env=ENV)
                self.assertEqual(done.code, 0, done.err)
                answers.append(json.loads(done.out))
            self.assertEqual(*answers)
            picks = {role: next(row["release"] for row in answers[0][role]["front"]
                                if "pick" in row["notes"])
                     for role in ("orchestrate", "execute", "review")}
            self.assertEqual(picks, {"execute": "acme-bend-1", "review": "acme-near-1",
                                     "orchestrate": "acme-near-1"})


if __name__ == "__main__":
    unittest.main()
