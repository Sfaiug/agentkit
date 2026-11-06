"""Each role's answer holds up to five choices a point apart, and the best of each other model.
Of the rows compared that have a cost, whichever harness runs them, or none, the front holds
each better than every cheaper one, the best last.  `choices`: its rows within 10 points of the
best, cheapest first, each a point or more above the last kept, the best taking the place of
one less than a point below it; the costliest five.  `others`: the best row of each release
with no choice, best first, `beaten` by a choice, else a row of the front, as good and no
dearer; on the front, `far below`, by null, more than 10 points under the best; else `close`
to the nearest choice, less than a point from it; else `no room`, by null, a point or more under
every choice, as the costliest five leave it.  Qualities exactly 10 or 1 apart are so, whatever
a rating's roundoff.

Black-box: AK_BIN in a temporary HOME, the boards held as just asked with invented releases of
one maker, its one harness a fake running one of them; only `ak models --json` is observed.
Fails against /bin/false.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, EVALUATIONS, aa, boards

ROLES = ("orchestrate", "execute", "review")
# Release, name, effort, quality in every role (every measure the share quality / 100 - 0.1,
# the best's 0.9) and cost a task, cheapest first
ROWS = [("acme-step-1", "Acme Step 1", "low", 70, 0.5),     # a choice's release: no other
        ("acme-low-1", "Acme Low 1", "high", 80, 1),        # over 10 below the best
        ("acme-lite-1", "Acme Lite 1", "high", 79, 1.5),    # beaten, by no choice
        ("acme-cut-1", "Acme Cut 1", "high", 90.5, 2),      # kept, the sixth from the top
        ("acme-mid-1", "Acme Mid 1", "high", 92, 3),
        ("acme-near-1", "Acme Near 1", "high", 92.5, 4),    # half a point over Mid
        ("acme-step-1", "Acme Step 1", "high", 94, 5),
        ("acme-wide-1", "Acme Wide 1", "high", 96, 8),
        ("acme-top-1", "Acme Top 1", "high", 97.5, 12),
        ("acme-edge-1", "Acme Edge 1", "high", 99.5, 16),   # half a point under the best
        ("acme-best-1", "Acme Best 1", "high", 100, 20),    # the best, which no harness runs
        ("acme-dear-1", "Acme Dear 1", "high", 95, 30),     # beaten; its max as good, dearer
        ("acme-dear-1", "Acme Dear 1", "max", 95, 40)]
CHOICES = [("Acme Mid 1", "high"), ("Acme Step 1", "high"), ("Acme Wide 1", "high"),
           ("Acme Top 1", "high"), ("Acme Best 1", "high")]
OTHERS = [("Acme Edge 1", "high", "close", {"name": "Acme Best 1", "effort": "high"}),
          ("Acme Dear 1", "high", "beaten", {"name": "Acme Wide 1", "effort": "high"}),
          ("Acme Near 1", "high", "close", {"name": "Acme Mid 1", "effort": "high"}),
          # within 10 points, but 1.5 under the cheapest of the five
          ("Acme Cut 1", "high", "no room", None),
          ("Acme Low 1", "high", "far below", None),
          ("Acme Lite 1", "high", "beaten", {"name": "Acme Low 1", "effort": "high"})]
# Shares whose qualities lie exactly 10, 1 and 1 apart, which a rating's floats put a hair
# across: the lower row 10.00000000000001 under the best, 0.99999999999999 under the next
EXACT = ((.57, .67), (.804, .814, .90), (.56, .57))


def answer(rows, runs):
    """`ak models --json` over the boards holding `rows`, each (release, name, effort, share
    of every measure, cost a task), its one harness running release `runs` at `high`."""
    with Home() as home:
        fake = fakeadapter.install(home, claude="pass")["claude"]
        fake.answer("models", f"{runs}\t{runs}\thigh\n")
        akconfig.write(home, {"mine": {"harness": "claude", "model": runs}})
        held = boards()
        for board in held.values():
            board["rows"] = [row for row in board["rows"] if row["model"] == "Old 1"]
        for release, name, effort, share, cost in rows:
            held["artificialanalysis.ai"]["rows"].append(aa(release, name, effort, {
                "aa.intelligenceIndex": 50, "aa.frontierCode20": share,
                "aa.terminalBench40": share, "aa.omniscience": 100 * share,
                "aa.automationBenchPartialScore": share,
                **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": cost
                   for slug in EVALUATIONS}}))
            held["arena.ai"]["rows"].append({"model": name, "effort": effort,
                                            "values": {"arena.agent": share}})
        home.write(".agentkit/state/boards.json", held)
        done = home.ak("models", "--json", env=ENV)
        assert done.code == 0, done.out + done.err
        return json.loads(done.out)


class RoleChoices(unittest.TestCase):
    def test_each_role_holds_choices_a_point_apart_and_the_best_of_each_other_model(self):
        found = answer([(release, name, effort, quality / 100 - 0.1, cost)
                        for release, name, effort, quality, cost in ROWS], "acme-mid-1")
        for role in ROLES:
            with self.subTest(role=role):
                said = found[role]
                self.assertEqual([(row["name"], row["effort"]) for row in said["choices"]],
                                 CHOICES)
                notes = {row["name"]: row["notes"] for row in said["choices"]}
                self.assertIn("no harness", notes["Acme Best 1"])
                self.assertNotIn("no harness", notes["Acme Mid 1"])
                self.assertEqual([(row["name"], row["effort"], row["why"], row["by"])
                                  for row in said["others"]], OTHERS)

    def test_qualities_exactly_10_or_1_apart_are_all_choices(self):
        for shares in EXACT:
            rows = [(f"acme-{n}-1", f"Acme {n} 1", "high", share, n + 1)
                    for n, share in enumerate(shares)]
            found = answer(rows, "acme-0-1")
            for role in ROLES:
                with self.subTest(shares=shares, role=role):
                    self.assertEqual([row["release"] for row in found[role]["choices"]],
                                     [release for release, *_ in rows])
                    self.assertEqual(found[role]["others"], [])


if __name__ == "__main__":
    unittest.main()
