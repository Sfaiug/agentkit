"""`matrix.lineup` gives a row per current release and effort, with the installed harnesses'
models that are it there (`yours`), and `matrix.answer` per role: every row rated, and over the
releases compared the best quality, the pick, the line of best quality for the money and the
best of yours to take.

Offline: both are handed what they read.  The models, harnesses and numbers are invented; on
execute, with no `arena.agent` anywhere, a row's quality is 100 less the weighted mean of how far
its frontier-code and terminal-bench shares are behind the best's, in hundredths.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import matrix, quality

COST = quality.COSTS["execute"]


def aa(slug, name, effort, release, frontier, terminal, cost=None, replaced_by=None):
    values = {quality.INTEL: 50, "aa.frontierCode20": frontier, "aa.terminalBench40": terminal}
    if cost is not None:
        values[COST] = cost
    return {"model": name, "effort": effort, "values": values, "slug": slug,
            "release": {"slug": release, "name": name, "deprecatedTo": replaced_by},
            "maker": "Acme", "deprecated": replaced_by is not None}


BOARDS = {"artificialanalysis.ai": {"rows": [
    aa("acme-5", "Acme 5", "high", "acme-5", 0.60, 0.60, 4.0),        # 0 0: 100, the default
    aa("acme-5-low", "Acme 5", "low", "acme-5", 0.56, 0.56, 2.0),     # 4 4: 96
    aa("bolt-2", "Bolt 2", "high", "bolt-2", 0.58, 0.58, 1.0),        # 2 2: 98
    aa("crux-1", "Crux 1", "medium", "crux-1", 0.40, 0.40, 0.5),      # 20 20: 80
    aa("dune-1", "Dune 1", "high", "dune-1", 0.30, 0.30),             # 40 40: 70, no cost
    aa("acme-4", "Acme 4", "high", "acme-4", 0.50, 0.50, 0.1, replaced_by="acme-5")]}}

OFFERS = {"anvil": [{"id": "acme-5", "efforts": ["low", "high"]},
                    {"id": "acme-4", "efforts": []}],              # the older release
          "brook": [{"id": "acme/acme-5", "efforts": ["none"]},     # at its default, high
                    {"id": "crux-1", "efforts": []}]}

ANVIL, BROOK = {"harness": "anvil", "model": "acme-5"}, {"harness": "brook", "model": "acme/acme-5"}


def key(row):
    return row and (row["release"], row["effort"])


class Lineup(unittest.TestCase):
    def setUp(self):
        self.lineup = matrix.lineup(BOARDS, OFFERS)

    def test_a_row_per_current_release_and_effort_with_the_harness_models_that_are_it(self):
        self.assertEqual({key(row): row["yours"] for row in self.lineup}, {
            ("acme-5", "low"): [ANVIL],
            ("acme-5", "high"): [ANVIL, BROOK],          # two harnesses run it
            ("bolt-2", "high"): [],
            ("crux-1", "medium"): [{"harness": "brook", "model": "crux-1"}],
            ("dune-1", "high"): []})
        row = next(row for row in self.lineup if key(row) == ("acme-5", "low"))
        self.assertEqual({name: row[name] for name in ("release", "name", "maker", "values")},
                         {"release": "acme-5", "name": "Acme 5", "maker": "Acme",
                          "values": BOARDS["artificialanalysis.ai"]["rows"][1]["values"]})

    def test_a_model_naming_an_older_release_makes_nothing_of_the_current_one_yours(self):
        offers = {"anvil": [{"id": "acme-4", "efforts": ["high"]}]}
        self.assertEqual([row["yours"] for row in matrix.lineup(BOARDS, offers)], [[]] * 5)

    def test_none_beside_other_efforts_is_an_effort_and_a_bracketed_name_matches(self):
        name, slug = "Eon 2 (Default Fallback)", "eon-2-default-fallback"
        boards = {"artificialanalysis.ai": {"rows": [
            aa(slug, name, "high", slug, 0.5, 0.5), aa(slug + "-none", name, "none", slug, 0.4, 0.4)]}}
        offers = {"anvil": [{"id": "eon-2", "efforts": ["none", "high"]}]}
        self.assertEqual({row["effort"]: row["yours"] for row in matrix.lineup(boards, offers)},
                         {"none": [{"harness": "anvil", "model": "eon-2"}],
                          "high": [{"harness": "anvil", "model": "eon-2"}]})

    def test_a_model_naming_no_version_is_the_board_name_adding_one_and_any_effort_runs_a_bare_row(self):
        boards = {"artificialanalysis.ai": {"rows": [
            aa("eon-flash-1017", "Eon Flash 1017", "max", "eon-flash-1017", 0.5, 0.5),
            aa("ray", "Ray 1.0", None, "ray", 0.4, 0.4),
            aa("sol-1", "Sol 20", "high", "sol-1", 0.3, 0.3), aa("mir-1", "Sol 30", "high", "mir-1", 0.3, 0.3),
            aa("zen-5", "Zen 5", "high", "zen-5", 0.2, 0.2)]}}
        def yours(model, *efforts):
            return {key(row) for row in matrix.lineup(boards, {"anvil": [
                {"id": model, "efforts": list(efforts)}]}) if row["yours"]}
        self.assertEqual(yours("cloud/eon-flash-free", "low", "max"), {("eon-flash-1017", "max")})
        self.assertEqual(yours("ray-free", "low", "high"), {("ray", None)})
        self.assertEqual(yours("sol", "high"), set())       # two releases stand for nothing
        self.assertEqual(yours("zen", "low"), set())        # no such effort on the board
        self.assertEqual(yours("zen-55", "high"), set())    # a version of its own


class Answer(unittest.TestCase):
    def setUp(self):
        self.lineup = matrix.lineup(BOARDS, OFFERS)

    def test_a_pick_no_harness_runs_takes_the_cheapest_of_yours_within_the_best(self):
        execute = matrix.answer(self.lineup, 5)["execute"]
        self.assertEqual({key(row): round(row["quality"], 6) for row in execute["rated"]},
                         {("acme-5", "high"): 100, ("acme-5", "low"): 96, ("bolt-2", "high"): 98,
                          ("crux-1", "medium"): 80, ("dune-1", "high"): 70})
        self.assertEqual(execute["best"], 100)
        self.assertEqual(key(execute["pick"]), ("bolt-2", "high"))
        self.assertEqual([key(row) for row in execute["front"]],
                         [("crux-1", "medium"), ("bolt-2", "high"), ("acme-5", "high")])
        self.assertEqual(key(execute["take"]), ("acme-5", "low"))     # 2.0, not high's 4.0

    def test_what_is_compared_never_changes_a_row_s_quality_and_a_pick_of_yours_is_taken(self):
        everything = matrix.answer(self.lineup, 5)["execute"]
        execute = matrix.answer(self.lineup, 5, {"acme-5", "crux-1"})["execute"]
        self.assertEqual(execute["rated"], everything["rated"])
        self.assertEqual(key(execute["pick"]), ("acme-5", "low"))
        self.assertIs(execute["take"], execute["pick"])
        self.assertEqual([key(row) for row in execute["front"]],
                         [("crux-1", "medium"), ("acme-5", "low"), ("acme-5", "high")])

    def test_nothing_with_a_cost_picks_and_takes_nothing(self):
        execute = matrix.answer(self.lineup, 5, {"dune-1"})["execute"]
        self.assertEqual((round(execute["best"], 6), execute["pick"], execute["front"],
                          execute["take"]), (70, None, [], None))
        self.assertEqual(matrix.answer(self.lineup, 5)["orchestrate"],
                         {"rated": [], "best": None, "pick": None, "front": [], "take": None})

    def test_none_of_yours_within_the_best_takes_nothing(self):
        execute = matrix.answer(self.lineup, 1, {"bolt-2", "crux-1"})["execute"]
        self.assertEqual((key(execute["pick"]), execute["take"]), (("bolt-2", "high"), None))


if __name__ == "__main__":
    unittest.main()
