"""`ak models` lists every model and effort the installed harnesses offer with the public boards'
numbers for each.

A row is a model at an effort a board lists or the config runs; a board naming no effort counts
for every effort of its model; a row at another effort never stands in; a board's model is
matched by its letters and digits, else by the board's name the id extends with a version, else
by `benchmark` on the config entry; the table puts the fullest rows first and names the rows no
board has.

Offline: the boards' answers are handed in as bytes (tests/test_model_matrix.py's), the harness
catalogs and the installed harnesses are faked, and a throwaway HOME holds the cache and key.
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

CATALOGS = {"claude": [{"id": "claude-opus-5-5", "efforts": ["low", "medium", "high", "xhigh", "max"]},
                       {"id": "claude-haiku-4-5", "efforts": ["none"]},
                       {"id": "claude-opus-4-7", "efforts": []}],
            "codex": [{"id": "gpt-6-astra", "efforts": ["low", "medium", "high", "xhigh", "max"]}],
            "muse": [{"id": "muse-wonder-full-1.0", "efforts": ["low", "high", "xhigh", "max"]},
                     {"id": "muse-spark-1.3-contributor", "efforts": ["low", "xhigh"]}]}


class ModelRows(Sandbox):
    def setUp(self):
        super().setUp()
        self.boards = boards_test.Boards()
        boards_test.AA += [
            {"name": "Muse Wonder Full (max)", "evaluations": {"artificial_analysis_coding_index": 57.1}},
            {"name": "Muse Spark 1.3 (xhigh)", "evaluations": {"artificial_analysis_coding_index": 40.0}}]
        self.addCleanup(lambda: boards_test.AA.__delitem__(slice(-2, None)))
        self.stack.enter_context(patch.object(matrix, "fetch_bytes", self.boards))
        self.stack.enter_context(patch.object(matrix, "harnesses", return_value=list(CATALOGS)))
        self.stack.enter_context(patch.object(matrix, "installed",
                                              side_effect=lambda harness: harness in CATALOGS))
        self.stack.enter_context(patch.object(config, "catalog", side_effect=CATALOGS.__getitem__))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        (config.SECRETS / matrix.AA_KEY).write_text("k\n")
        self.cfg["models"]["wonder"] = {"harness": "muse", "model": "muse-wonder-full-1.0",
                                        "effort": "max", "provider": "meta"}

    def table(self):
        held = matrix.collect(now=10000)
        return {matrix.row_label(row): row for row in matrix.rows(self.cfg, held)}

    def test_a_row_per_effort_the_boards_list_or_the_config_runs(self):
        rows = self.table()
        self.assertEqual(sorted(name for name in rows if "opus-5-5" in name or name[:5] == "opus "),
                         ["claude-opus-5-5 @ max", "opus @ xhigh"])
        both = rows["claude-opus-5-5 @ max"]
        self.assertEqual(both["matched"], {"artificialanalysis.ai": "Claude Opus 5.5 (max)",
                                           "arena.ai": "Claude Opus 5.5 (max)",
                                           "livebench.ai": "claude-opus-5.5"})
        self.assertEqual(both["values"]["arena.agent_steerability"], 0.2)
        self.assertEqual(both["values"]["aa.pricing.price_1m_input_tokens"], 4.0)
        self.assertEqual(both["name"], None)
        # LiveBench names no effort: its numbers count at every effort of the model
        self.assertEqual(rows["opus @ xhigh"]["values"]["livebench.coding"], 96.3)
        self.assertEqual(rows["opus @ xhigh"]["values"][matrix.COST], round(113 / (29 * .963), 2))
        # a row at another effort never stands in: the configured xhigh has no Arena numbers
        self.assertNotIn("arena.agent", rows["opus @ xhigh"]["values"])
        self.assertNotIn("arena.ai", rows["opus @ xhigh"]["matched"])
        # the boards' efforts count only among those the harness offers: Astra's xhigh does
        self.assertIn("astra @ xhigh", rows)
        self.assertEqual(rows["astra @ xhigh"]["values"]["arena.agent"], 0.137)
        # a board's `(Non-reasoning)` is ak's `none`, an effort Haiku offers
        self.assertEqual(rows["claude-haiku-4-5 @ none"]["matched"],
                         {"artificialanalysis.ai": "Claude Haiku 4.5 (none)"})
        # a model no board lists at any effort is one row at none
        self.assertEqual((rows["claude-opus-4-7"]["values"], rows["claude-opus-4-7"]["effort"]),
                         ({}, None))

    def test_a_board_s_model_is_found_by_its_name_a_version_or_benchmark(self):
        rows = self.table()
        # the id extends the board's name with a version: muse-wonder-full-1.0
        self.assertEqual(rows["wonder @ max"]["matched"],
                         {"artificialanalysis.ai": "Muse Wonder Full (max)"})
        # `contributor` is no version: nothing matches until the entry says what to look for
        self.assertEqual(rows["spark @ xhigh"]["values"], {})
        self.cfg["models"]["spark"]["benchmark"] = "Muse Spark 1.3"
        rows = self.table()
        self.assertEqual(rows["spark @ xhigh"]["values"]["aa.evaluations.artificial_analysis_coding_index"], 40.0)
        # a shorter board name never stands for a longer id of another version
        index = {"claudesonnet5": [{"model": "Claude Sonnet 5", "effort": None, "values": {}}],
                 "claudesonnet55": [{"model": "Claude Sonnet 5.5", "effort": None, "values": {}}]}
        self.assertEqual(matrix.matching(index, "claude-sonnet-5-5", "max")["model"],
                         "Claude Sonnet 5.5")
        self.assertIsNone(matrix.matching({"claudesonnet5": index["claudesonnet5"]},
                                          "claude-sonnet-5-5", "max"))

    def test_the_table_puts_the_fullest_rows_first_and_names_the_rest(self):
        held = matrix.collect(now=10000)
        with patch.object(matrix.time, "time", return_value=10000):
            lines = [terminal.plain(line)
                     for line in matrix.render(matrix.rows(self.cfg, held), held).splitlines()]
        text = "\n".join(lines)
        self.assertEqual(lines[0].split(), ["model", "harness", "id", "boards", "tok/s", "$/task"])
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        self.assertRegex(lines[1], r"^- +claude +claude-opus-5-5 @ max +artificialanalysis \(max\), "
                                   r"arena \(max\), livebench +95 +4\.05$")
        self.assertRegex(text, r"\nopus +claude +claude-opus-5-5 @ xhigh +artificialanalysis \(xhigh\), livebench +- +4\.05\n")
        self.assertRegex(text, r"no board row: .*claude-opus-4-7")
        self.assertIn("arena.ai: 2 rows as of", text)
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(sorted(data), ["boards", "rows"])
        self.assertNotIn("rows", data["boards"]["arena.ai"])
        self.assertIn("claude-opus-5-5 @ max", [matrix.row_label(row) for row in data["rows"]])


if __name__ == "__main__":
    unittest.main()
