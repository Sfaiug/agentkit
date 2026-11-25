"""A pick for no run takes a role's marks in the order marked, and a run's in its draw among them
(tests/test_key_a_run_draws_its_executor_and_reviewer.py): no lineup, rank or usage left
reorders them (the owner, 24 Nov 2026: "I want the user to have full controll.").

Two executors are marked, wren and then lark, each on a one-login provider of its own.  The
lineup a `ak models` stores rates lark far above wren to execute, better and cheaper, and lark's
week has far more left.  `ak usage --json`'s `pick_order` still names wren first, and marked the
other way round it names lark first.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on
harnesses that are only their meters (tests/fixtures/meters.py), with the lineup written as
`ak models` stores it.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

MODELS = {"wren": {"harness": "echo", "provider": "fernco", "model": "fern-wren-1"},
          "lark": {"harness": "echo", "provider": "hillco", "model": "hill-lark-1"}}
MAKERS = {"wren": "Fern", "lark": "Hill"}
USED = {"fernco": 80, "hillco": 5}      # each week's used%: lark's has far more left
# each model's share on every execute measure and its cost a task: lark the better and cheaper
SCORES = {"wren": (0.10, 9.0), "lark": (0.95, 1.0)}
COST = "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask"


def lineup():
    """A row of each model, under its maker, holding it as `yours`, scored as `SCORES` says."""
    return {"matrix": {"lineup": [
        {"release": entry["model"], "name": entry["model"], "board_name": entry["model"],
         "maker": MAKERS[name], "effort": "high", "yours": [
             {"harness": entry["harness"], "model": entry["model"]}],
         "values": {"aa.intelligenceIndex": 50, "aa.frontierCode20": share, "arena.agent": share,
                    "aa.terminalBench40": share, COST: cost}}
        for name, entry in MODELS.items() for share, cost in [SCORES[name]]]}}


class APickTakesTheMarksInTheirOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        meter = meters.install(cls.home)
        for provider, used in USED.items():
            meter.week(provider, used=used)
        cls.home.write(".agentkit/state/matrix.json", lineup())

    def pick_order(self, workers):
        akconfig.write(self.home, MODELS, workers=workers)
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["pick_order"]

    def test_they_come_as_marked(self):
        self.assertEqual(self.pick_order(["wren", "lark"]), ["wren", "lark"])

    def test_marked_the_other_way_round_they_come_the_other_way_round(self):
        self.assertEqual(self.pick_order(["lark", "wren"]), ["lark", "wren"])


if __name__ == "__main__":
    unittest.main()
