"""`ak models` scores every row per role and recommends one row per role.

A column is a share of the best among the rows ak can run (100; zero or below, 0, still
counted); a role's score is the mean of the role's measures the row has, said with how many it
rests on; the recommendation is a row a board measured at its effort before one that only
inherits a board naming no effort, then the row resting on the most measures, then the highest
score, then the faster, then the cheaper, an unknown speed or cost last.  The table shows
`97 of 3` per role, the recommendation under it, and what each role is scored on.

Offline: the boards' answers are handed in as bytes (tests/test_model_matrix.py's), the harness
catalogs and the installed harnesses are faked (tests/test_model_rows.py's), a throwaway HOME.
"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, matrix, terminal
import test_model_matrix as boards_test
import test_model_rows as rows_test

MORE = [{"name": "Claude Opus 5.5 (max)", "evaluations": {
             "artificial_analysis_coding_index": 60, "artificial_analysis_agentic_index": 70,
             "artificial_analysis_intelligence_index": 58}, "performance": {"median_output_tokens_per_second": 95}},
        {"name": "Claude Opus 5.5 (xhigh)", "evaluations": {
             "artificial_analysis_coding_index": 60, "artificial_analysis_agentic_index": 70,
             "artificial_analysis_intelligence_index": 56}, "performance": {"median_output_tokens_per_second": 82}},
        {"name": "GPT 6 Astra (max)", "evaluations": {
             "artificial_analysis_coding_index": 25, "artificial_analysis_agentic_index": 40,
             "artificial_analysis_intelligence_index": 53}, "performance": {"median_output_tokens_per_second": 57}}]


class ModelScores(Sandbox):
    def setUp(self):
        super().setUp()
        rows_test.prepare(self)
        boards_test.AA[:] = [entry for entry in boards_test.AA
                                     if not entry["name"].startswith(("Claude Opus 5.5", "GPT 6 Astra"))] + MORE
        boards_test.ARENA["agent"].append(("GPT 6 Astra (Max)", -0.05))
        self.addCleanup(boards_test.ARENA["agent"].pop)

    def scored(self):
        held = matrix.collect(now=10000)
        table = matrix.rows(self.cfg, held)
        recommended = matrix.scored(table)
        return held, table, {matrix.row_label(row): row for row in table}, recommended

    def test_a_score_is_the_mean_share_of_the_best_over_the_measures_the_row_has(self):
        _, _, rows, _ = self.scored()
        opus = rows["claude-opus-5-5 @ max"]["scores"]
        self.assertEqual(opus["execute"], {"score": 100.0, "measures": 4})
        self.assertEqual(opus["orchestrate"], {"score": 100.0, "measures": 4})
        astra = rows["gpt-6-astra @ max"]["scores"]
        # execute: coding index 25/60, agentic index 40/70, livebench coding 93.7/96.3, each a
        # share of the best, averaged; the long-horizon suite LiveBench gave it no score on
        self.assertEqual(astra["execute"]["measures"], 3)
        self.assertAlmostEqual(astra["execute"]["score"],
                               round((100 * 25 / 60 + 100 * 40 / 70 + 100 * 93.7 / 96.3) / 3, 1))
        # a net improvement below zero scores 0, and steerability it has none of is not counted
        self.assertEqual(astra["orchestrate"]["measures"], 2)
        self.assertAlmostEqual(astra["orchestrate"]["score"], round((0 + 100 * 40 / 70) / 2, 1))
        # the configured xhigh rests on fewer measures: no Arena row at that effort
        self.assertEqual(rows["opus @ xhigh"]["scores"]["orchestrate"], {"score": 100.0, "measures": 2})
        self.assertIsNone(rows["claude-opus-4-7"]["scores"]["review"])
        # a measure no row has above zero scores 0 and still counts
        table = [{"values": {"arena.agent": -0.1, "livebench.long_horizon": 40}},
                 {"values": {"livebench.long_horizon": 100}}]
        matrix.scored(table)
        self.assertEqual(table[0]["scores"]["orchestrate"], {"score": 20.0, "measures": 2})

    def test_the_recommendation_rests_on_the_most_measures_then_score_speed_and_cost(self):
        _, _, rows, recommended = self.scored()
        self.assertEqual({role: matrix.row_label(row) for role, row in recommended.items()},
                         {"orchestrate": "claude-opus-5-5 @ max", "execute": "claude-opus-5-5 @ max",
                          "review": "claude-opus-5-5 @ max"})
        # execute: max and xhigh score alike on all four measures; the faster row wins
        self.assertEqual(rows["opus @ xhigh"]["scores"]["execute"],
                         rows["claude-opus-5-5 @ max"]["scores"]["execute"])
        rows["opus @ xhigh"]["values"][matrix.SPEED] = 96
        table = list(rows.values())
        self.assertEqual(matrix.row_label(matrix.scored(table)["execute"]), "opus @ xhigh")
        # equal speed: the cheaper row
        rows["opus @ xhigh"]["values"][matrix.SPEED] = 95
        rows["opus @ xhigh"]["values"][matrix.COST] = 1.0
        self.assertEqual(matrix.row_label(matrix.scored(table)["execute"]), "opus @ xhigh")
        # an unknown cost ranks after every measured one, and so does an unknown speed
        del rows["opus @ xhigh"]["values"][matrix.COST]
        self.assertEqual(matrix.row_label(matrix.scored(table)["execute"]), "claude-opus-5-5 @ max")
        rows["opus @ xhigh"]["values"][matrix.COST] = 1.0
        del rows["opus @ xhigh"]["values"][matrix.SPEED]
        self.assertEqual(matrix.row_label(matrix.scored(table)["execute"]), "claude-opus-5-5 @ max")
        # a higher score on fewer measures never beats a row resting on more
        rows["opus @ xhigh"]["values"]["aa.evaluations.artificial_analysis_agentic_index"] = 75
        self.assertEqual(matrix.row_label(matrix.scored(table)["orchestrate"]), "claude-opus-5-5 @ max")
        self.assertGreater(rows["opus @ xhigh"]["scores"]["orchestrate"]["score"],
                           rows["claude-opus-5-5 @ max"]["scores"]["orchestrate"]["score"])
        self.assertEqual(matrix.scored([]), {})

    def test_a_row_measured_at_its_effort_beats_one_that_only_inherits_a_board_naming_no_effort(self):
        _, table, rows, _ = self.scored()
        # LiveBench names no effort: spark's one board is inherited, while Haiku's row at none
        # is the board's own
        self.assertEqual([rows[label]["measured"] for label in
                          ("claude-opus-5-5 @ max", "claude-haiku-4-5 @ none", "spark @ xhigh")],
                         [True, True, False])
        rows["spark @ xhigh"]["values"] = {**rows["claude-opus-5-5 @ max"]["values"],
                                           "livebench.coding": 99}
        recommended = matrix.scored(table)
        self.assertGreater(rows["spark @ xhigh"]["scores"]["execute"]["score"],
                           rows["claude-opus-5-5 @ max"]["scores"]["execute"]["score"])
        self.assertEqual(matrix.row_label(recommended["execute"]), "claude-opus-5-5 @ max")

    def test_the_table_says_each_score_with_its_measures_and_the_recommendation(self):
        held, table, _, recommended = self.scored()
        with patch.object(matrix.time, "time", return_value=10000):
            lines = [terminal.plain(line)
                     for line in matrix.render(table, held, recommended).splitlines()]
        text = "\n".join(lines)
        self.assertEqual(lines[0].split(), ["model", "harness", "id", "orch", "exec", "review",
                                            "tok/s", "$/task"])
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        self.assertRegex(lines[1], r"^- +claude +claude-opus-5-5 @ max +100 of 4 +100 of 4 +100 of 2 +95 +4\.05$")
        self.assertRegex(lines[2], r"^opus +claude +claude-opus-5-5 @ xhigh +100 of 2 +100 of 4 +98 of 2 +82 +4\.05$")
        self.assertIn("recommended: orchestrate claude-opus-5-5 @ max (100 of 4) · execute "
                      "claude-opus-5-5 @ max (100 of 4) · review claude-opus-5-5 @ max (100 of 2)",
                      " ".join(text.split()))                 # wrapped to the width, as a line
        self.assertIn("execute, 4 measures: aa.evaluations.artificial_analysis_coding_index (coding across evaluations)", text)
        self.assertRegex(text, r"\nclaude-opus-4-7 +- +- +- +- +-\n|\n- +claude +claude-opus-4-7 +- +- +- +- +-\n")
        self.assertIn("no recommendation yet", terminal.plain(matrix.render([], held, {})))
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["recommended"], {"orchestrate": "claude-opus-5-5 @ max",
                                               "execute": "claude-opus-5-5 @ max",
                                               "review": "claude-opus-5-5 @ max"})
        self.assertEqual(data["rows"][0]["scores"].keys(), matrix.ROLES.keys())


if __name__ == "__main__":
    unittest.main()
