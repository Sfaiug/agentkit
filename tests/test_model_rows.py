"""`ak models` lists every model and effort the installed harnesses offer with the public boards'
numbers for each.

A row is a model at an effort a board lists or the config runs it at in any role; a board naming
no effort counts for every effort of its model; a row at another effort never stands in; a
board's model is matched by its letters and digits, else by the board's name the id extends with
a version, else, on a board where neither finds it, by `benchmark` on the config entry; the table
puts the fullest rows first and names the rows no board has.

Offline: the boards' answers are handed in as bytes (tests/test_model_matrix.py's), the harness
manifests, catalogs and the installed harnesses are faked, and a throwaway HOME holds the cache
and key.
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


def prepare(case):
    """The boards answered by bytes, the harness manifests, catalogs and installed harnesses
    faked, a key, and a configured Muse Wonder Full, on a Sandbox case."""
    case.boards = boards_test.Boards()
    boards_test.AA += [
        {"name": "Muse Wonder Full (max)", "evaluations": {"artificial_analysis_coding_index": 57.1}},
        {"name": "Muse Spark 1.3 (xhigh)", "evaluations": {"artificial_analysis_coding_index": 40.0}}]
    case.addCleanup(lambda: boards_test.AA.__delitem__(slice(-2, None)))
    case.stack.enter_context(patch.object(boards_test, "TABLE", boards_test.TABLE
                                          + "muse-spark-1.3-contributor,50.0,\n"))
    case.stack.enter_context(patch.object(matrix, "fetch_bytes", case.boards))
    # acme has a manifest and no binary here: none of its models gets a row
    case.stack.enter_context(patch.object(config, "manifests", return_value=[
        (harness, {}) for harness in (*CATALOGS, "acme")]))
    case.stack.enter_context(patch.object(config, "harness_present",
                                          side_effect=lambda harness: harness in CATALOGS))
    case.stack.enter_context(patch.object(config, "catalog", side_effect=CATALOGS.__getitem__))
    case.stack.enter_context(patch.object(terminal, "width", return_value=100))
    (config.SECRETS / matrix.AA_KEY).write_text("k\n")
    case.cfg["models"]["wonder"] = {"harness": "muse", "model": "muse-wonder-full-1.0",
                                    "effort": "max", "provider": "meta"}


class ModelRows(Sandbox):
    def setUp(self):
        super().setUp()
        prepare(self)

    def table(self):
        held = matrix.collect(now=10000)
        return {matrix.row_label(row): row for row in matrix.rows(self.cfg, held)}

    def test_a_row_per_effort_the_boards_list_or_the_config_runs(self):
        self.cfg["models"]["astra"]["exec_effort"] = "medium"
        rows = self.table()
        self.assertEqual({row["harness"] for row in rows.values()}, set(CATALOGS))
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
        # an effort one role runs it at is a row too, and Arena's xhigh row never stands in
        self.assertEqual((rows["astra @ medium"]["name"], rows["astra @ medium"]["matched"]),
                         ("astra", {"livebench.ai": "gpt-6-astra"}))
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
        # `contributor` is no version: Artificial Analysis's `Muse Spark 1.3` is not found
        # until the entry says what to look for, and LiveBench's exact id is found either way
        self.assertEqual(rows["spark @ xhigh"]["matched"], {"livebench.ai": "muse-spark-1.3-contributor"})
        self.cfg["models"]["spark"]["benchmark"] = "Muse Spark 1.3"
        rows = self.table()
        self.assertEqual(rows["spark @ xhigh"]["matched"], {
            "artificialanalysis.ai": "Muse Spark 1.3 (xhigh)", "livebench.ai": "muse-spark-1.3-contributor"})
        self.assertEqual(rows["spark @ xhigh"]["values"]["aa.evaluations.artificial_analysis_coding_index"], 40.0)
        # a shorter board name never stands for a longer id of another version
        index = {"claudesonnet5": [{"model": "Claude Sonnet 5", "effort": None, "values": {}}],
                 "claudesonnet55": [{"model": "Claude Sonnet 5.5", "effort": None, "values": {}}]}
        self.assertEqual(matrix.matching(index, "claude-sonnet-5-5", "max")["model"],
                         "Claude Sonnet 5.5")
        self.assertIsNone(matrix.matching({"claudesonnet5": index["claudesonnet5"]},
                                          "claude-sonnet-5-5", "max"))

    def test_the_table_names_the_rows_no_board_has_and_json_says_what_matched(self):
        held = matrix.collect(now=10000)
        table = matrix.rows(self.cfg, held)
        with patch.object(matrix.time, "time", return_value=10000):
            lines = [terminal.plain(line)
                     for line in matrix.render(table, held, matrix.scored(table)).splitlines()]
        text = "\n".join(lines)
        self.assertEqual(lines[0].split()[:3], ["model", "harness", "id"])
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        self.assertRegex(text, r"\nopus +claude +claude-opus-5-5 @ xhigh ")
        self.assertRegex(text, r"no board row: .*claude-opus-4-7")
        self.assertIn("arena.ai: 2 rows as of", text)
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertNotIn("rows", data["boards"]["arena.ai"])
        rows = {matrix.row_label(row): row for row in data["rows"]}
        self.assertEqual(rows["claude-opus-5-5 @ max"]["matched"],
                         {"artificialanalysis.ai": "Claude Opus 5.5 (max)",
                          "arena.ai": "Claude Opus 5.5 (max)", "livebench.ai": "claude-opus-5.5"})
        self.assertEqual(rows["opus @ xhigh"]["matched"],
                         {"artificialanalysis.ai": "Claude Opus 5.5 (xhigh)", "livebench.ai": "claude-opus-5.5"})


if __name__ == "__main__":
    unittest.main()
