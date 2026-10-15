"""`ak models` recommends one row per role: among the rows with a score for the role, the row
resting on the most of the role's measures, then the highest score (exact, not as the table
rounds it), then the faster, then the cheaper (an unknown speed or cost after every measured
one), then the row the config runs, then the higher effort; a role no row has a measure of gets
none.  The table says the recommendation under the rows, `--json` carries it, and a table with
no scored row says so."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, matrix, terminal

CODING = "aa.evaluations.artificial_analysis_coding_index"


def row(name, model, effort, **values):
    return {"harness": "acme", "model": model, "effort": effort, "name": name, "matched": {},
            "values": values}


def pick(role, *rows):
    return matrix.row_label(matrix.recommended(matrix.scored(list(rows)))[role])


class ModelRecommends(unittest.TestCase):
    def test_most_measures_then_score_speed_cost_the_config_s_row_and_the_higher_effort(self):
        full = row(None, "acme-pro", "max", **{CODING: 50, "livebench.coding": 90, matrix.SPEED: 70})
        high = row(None, "acme-pro", "high", **{CODING: 60, "livebench.coding": 90, matrix.SPEED: 70})
        # a higher score on fewer measures never beats a row resting on more
        self.assertEqual(pick("execute", full, row(None, "acme-mini", None, **{CODING: 60})), "acme-pro @ max")
        # the same measures: the highest score, compared exactly, not as the table rounds it
        self.assertEqual(pick("execute", full, high), "acme-pro @ high")
        self.assertEqual(pick("execute", row(None, "acme-a", None, **{CODING: 99.99, matrix.SPEED: 50}),
                              row(None, "acme-b", None, **{CODING: 99.95, matrix.SPEED: 100})), "acme-a")
        # the same score: the faster, then the cheaper; an unknown speed or cost after every measured one
        self.assertEqual(pick("execute", full, {**full, "effort": "xhigh", "values": {**full["values"], matrix.SPEED: 80}}),
                         "acme-pro @ xhigh")
        cheap = {**full, "effort": "low", "values": {**full["values"], matrix.COST: 1.0}}
        self.assertEqual(pick("execute", full, cheap, {**cheap, "effort": "medium", "values": {**cheap["values"], matrix.COST: 2.0}}),
                         "acme-pro @ low")
        self.assertEqual(pick("execute", {**full, "values": {CODING: 50, "livebench.coding": 90}}, cheap), "acme-pro @ low")
        # nothing tells them apart: the row the config runs, else the higher effort
        self.assertEqual(pick("execute", full, {**full, "effort": "low", "name": "pro"}), "pro @ low")
        self.assertEqual(pick("execute", {**full, "effort": "low"}, full), "acme-pro @ max")
        self.assertEqual(pick("execute", {**full, "effort": None}, {**full, "effort": "low"}), "acme-pro @ low")
        # a role no row has a measure of has no recommendation; no row, none at all
        self.assertEqual(list(matrix.recommended(matrix.scored([full, high]))), ["execute", "review"])
        self.assertEqual(matrix.recommended([]), {})

    def test_the_table_and_json_say_the_recommendation(self):
        table = matrix.scored([row("pro", "acme-pro", "high", **{CODING: 45, "arena.agent": 0.1}),
                               row(None, "acme-mini", None, **{CODING: 60, "livebench.reasoning": 40})])
        with patch.object(terminal, "width", return_value=100):
            text = terminal.plain(matrix.render(table, {}))
            none = terminal.plain(matrix.render(matrix.scored([row(None, "acme-old", None)]), {}))
        self.assertIn("recommended: orchestrate pro @ high (100 of 1) · execute acme-mini (100 of 1) · "
                      "review acme-mini (100 of 2)", " ".join(text.split()))
        self.assertIn("recommended is the row with the most of the role's measures", " ".join(text.split()))
        self.assertIn("no recommendation yet: no board has a row ak can run", none)
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value={}), \
                patch.object(matrix, "collect", return_value={}), patch.object(matrix, "rows", return_value=table):
            self.assertEqual(matrix.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["recommended"], {"orchestrate": "pro @ high", "execute": "acme-mini",
                                               "review": "acme-mini"})
        self.assertEqual(data["rows"][0]["scores"]["execute"], {"score": 75.0, "measures": 1})


if __name__ == "__main__":
    unittest.main()
