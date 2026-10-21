"""`ak models` recommends, per role, the cheapest row as good as the best: among the rows with a
score for the role, those within `within` (5 unless config.toml says) of the best row's quality,
cheapest first, one per model at its cheapest such effort, the first of them the recommendation
and the rest beside it (`as good:`).  Cheapest by what Artificial Analysis's index run cost on
the row (`cost`), a row it has not run after every priced one, by LiveBench's cost of a coding
task (`$/task`), unpriced last; rows alike on cost go by the higher quality (exact, not as the
table rounds it), then the row the config runs in the role, then the higher effort, then the
first by harness and model name, so the pick is the same however the table is ordered; a role no
row has a score for gets none.  The table says the recommendation under the rows, `--json`
carries each role's rows, and a table with no scored row says so.  `within` in config.toml is a
number of points, 0 or more, else the config is refused."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures import scores
from fixtures.sandbox import Sandbox
from agentkit import boards, config, matrix, terminal

def coding(value):
    """Values scoring `value` of 60 to build, as a share of 100 (fixtures.scores)."""
    return scores.values(execute=100 * value / 60)


def row(name, model, effort, roles=matrix.ROLES, **values):
    """A configured row runs in every role unless `roles` says which."""
    return {"harness": "acme", "model": model, "effort": effort, "name": name, "matched": {},
            "roles": list(roles) if name else [], "values": values}


def picks(role, *rows, within=matrix.WITHIN):
    return [matrix.row_label(row) for row in
            matrix.recommended(matrix.scored(list(rows), scores.BEST), within)[role]]


class ModelRecommends(unittest.TestCase):
    def test_the_cheapest_row_as_good_as_the_best_with_the_rest_beside_it(self):
        best = row(None, "acme-a", "max", **coding(60), **{matrix.COST: 8000})
        cheaper = row(None, "acme-a", "high", **coding(58), **{matrix.COST: 3000})  # 96.7
        other = row(None, "acme-b", "max", **coding(58), **{matrix.COST: 500})      # 96.7
        under = row(None, "acme-c", "max", **coding(56), **{matrix.COST: 100})      # 93.3
        task = row(None, "acme-d", "max", **coding(59), **{boards.TASK_COST: 0.5})  # LiveBench priced
        free = row(None, "acme-e", "max", **coding(59.5))                           # unpriced
        table = (best, cheaper, other, under, task, free)
        # within 5 of the best: the cheapest first, a model once at its cheapest such effort, a
        # row priced by LiveBench alone after every row Artificial Analysis priced, unpriced last
        self.assertEqual(picks("execute", *table),
                         ["acme-b @ max", "acme-a @ high", "acme-d @ max", "acme-e @ max"])
        self.assertEqual(picks("execute", *table, within=8)[0], "acme-c @ max")
        self.assertEqual(picks("execute", *table, within=0), ["acme-a @ max"])
        # a role no model holds half the measures of (review: one of three here) has no
        # recommendation; no row, none at all
        self.assertEqual(list(matrix.recommended(matrix.scored([best, cheaper], scores.BEST))),
                         ["execute"])
        self.assertEqual(matrix.recommended([]), {})

    def test_rows_alike_on_cost_go_by_quality_the_config_s_row_the_higher_effort_and_the_name(self):
        self.assertEqual(picks("execute", row(None, "acme-a", None, **coding(99.95)),
                               row(None, "acme-b", None, **coding(99.99)))[0], "acme-b")
        # a board naming no effort leaves every effort of the model alike: each role keeps the
        # effort the config runs it at
        alike = scores.values(orchestrate=70, execute=80, review=60)
        runs = [row("pro", "acme-pro", effort, [role], **alike) for role, effort in
                (("orchestrate", "high"), ("execute", "low"), ("review", "medium"))]
        self.assertEqual([picks(role, *runs)[0] for role in matrix.ROLES],
                         ["pro @ high", "pro @ low", "pro @ medium"])
        full = row(None, "acme-pro", "max", **alike)
        self.assertEqual(picks("execute", full, {**full, "effort": "low"}), ["acme-pro @ max"])
        self.assertEqual(picks("execute", {**full, "effort": None}, {**full, "effort": "low"}),
                         ["acme-pro @ low"])
        # alike in all of it: the first by harness and model name, whatever order the table is in
        twins = [row("z", "acme-z", "high", **coding(50)), row("a", "acme-a", "high", **coding(50))]
        self.assertEqual((picks("execute", *twins)[0], picks("execute", *reversed(twins))[0]),
                         ("a @ high", "a @ high"))

    def test_the_table_and_json_say_the_recommendation(self):
        table = matrix.scored([
            row("pro", "acme-pro", "high", **scores.values(orchestrate=100, execute=87.5)),
            row(None, "acme-mini", None, **scores.values(execute=100, review=100))], scores.BEST)
        with patch.object(terminal, "width", return_value=100):
            text = terminal.plain(matrix.render(table, {}))
            none = terminal.plain(matrix.render(matrix.scored([row(None, "acme-old", None)],
                                                              scores.BEST), {}))
        self.assertIn("recommended: orchestrate pro @ high (100 of 2) · execute acme-mini (100 of 3) · "
                      "review acme-mini (100 of 3)", " ".join(text.split()))
        self.assertIn("a row within 5 of the best counts as as good (`within` in config.toml), and the "
                      "cheapest of those is recommended: by `cost`, what Artificial Analysis's index run "
                      "cost on it, then `$/task`, LiveBench's cost of a coding task, unpriced last, then "
                      "the higher quality, the one the config runs in the role, the higher effort, the "
                      "first by name", " ".join(text.split()))
        self.assertIn("no recommendation yet: no board has a row ak can run", none)
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value={"within": 20}), \
                patch.object(matrix, "refresh", return_value=({}, table)), patch.object(matrix, "live", return_value={}):
            self.assertEqual(matrix.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["within"], 20)
        # within 20, the executor the config runs stands beside the recommendation
        self.assertEqual(data["recommended"], {"orchestrate": ["pro @ high"],
                                               "execute": ["acme-mini", "pro @ high"],
                                               "review": ["acme-mini"]})
        self.assertEqual(data["rows"][0]["scores"]["execute"], {"score": 87.5, "measures": 3})


class WithinInConfig(Sandbox):
    def test_within_in_the_config_is_a_number_of_points_0_or_more(self):
        shipped = (REPO / config.DEFAULT_CONFIG_NAME).read_text()
        path = config.HOME / config.CONFIG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)

        def write(value):
            path.write_text(re.sub(r"^within = \S+", f"within = {value}", shipped, count=1, flags=re.M))
        self.assertEqual(matrix.within(config.load()), 5)      # the shipped default
        write(2.5)
        self.assertEqual(matrix.within(config.load()), 2.5)
        for bad in ("-1", "true", '"5"'):
            write(bad)
            with self.assertRaisesRegex(config.Error, "within must be a number of points, 0 or more"):
                config.load()


if __name__ == "__main__":
    unittest.main()
