"""A release compared whose rows have a quality on the boards and no price is among a role's
`others`, after those with a cost, its best row with the why `no cost`, by null, and a null
`cost`.  A row a board prices that your runs and plans give no cost, as only releases no board
prices ran, is `not converted` instead.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked with invented releases of
one maker (tests/test_key_role_choices.py), its harness a fake listing each of them, each
configured; judged by `ak models --json`; and the boards, logins' weeks and finished runs of
tests/test_key_picks_priced_in_usage.py.  Fails against /bin/false.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akboards import ENV
import test_key_picks_priced_in_usage as priced
from test_key_role_choices import hold

# Release, name, quality in every role and cost a task, each at `high`, cheapest first
ROWS = [("acme-base-1", "Acme Base 1", 90, 2),
        ("acme-mid-1", "Acme Mid 1", 93, 4),
        ("acme-dear-1", "Acme Dear 1", 92, 6),     # Mid is as good for less
        ("acme-top-1", "Acme Top 1", 97, 10),
        ("acme-bare-1", "Acme Bare 1", 95, None)]  # no board prices it
CONFIGURED = {release.split("-")[1]: {"harness": "claude", "model": release}
              for release, *_ in ROWS}
CHOICES = ["Acme Base 1", "Acme Mid 1", "Acme Top 1"]
# (name, why, by, its cost null)
OTHERS = [("Acme Dear 1", "beaten", "Acme Mid 1", False), ("Acme Bare 1", "no cost", None, True)]


class WhyNoCost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"{release}\t{name}\thigh\n" for release, name, *_ in ROWS))
        hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                    for release, name, quality, cost in ROWS])

    def test_json_lists_it_in_each_roles_others_after_those_with_a_cost(self):
        akconfig.write(self.home, CONFIGURED, orchestrator="top")
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        found = json.loads(done.out)
        for role in ("orchestrate", "execute", "review"):
            with self.subTest(role=role):
                self.assertEqual([row["name"] for row in found[role]["choices"]], CHOICES)
                self.assertEqual([(row["name"], row["why"], row["by"] and row["by"]["name"],
                                   row["cost"] is None) for row in found[role]["others"]],
                                 OTHERS)


class NotConverted(unittest.TestCase):
    # its home: Anvil, Bloom and Dune ran builds and reviews, no orchestration
    setUp, cache, answer = (getattr(priced.PicksPricedInUsage, name)
                            for name in ("setUp", "cache", "answer"))

    def test_with_only_releases_no_board_prices_run_one_a_board_prices_is_not_converted(self):
        path = self.home.path / ".agentkit/state/boards.json"
        held = json.loads(path.read_text())
        for row in held["artificialanalysis.ai"]["rows"]:
            if row["model"] in ("Anvil", "Bloom", "Dune") and row["effort"] == "high":
                row["values"] = {key: value for key, value in row["values"].items()
                                 if not key.endswith(".costPerTask")}
        path.write_text(json.dumps(held))
        self.assertEqual([(row["name"], row["why"], row["board_cost"]) for row in
                          self.answer()["orchestrate"]["others"]],
                         [("Crown", "not converted", 100), ("Bloom", "no cost", None),
                          ("Anvil", "no cost", None), ("Echo", "not converted", 20),
                          ("Dune", "no cost", None)])


if __name__ == "__main__":
    unittest.main()
