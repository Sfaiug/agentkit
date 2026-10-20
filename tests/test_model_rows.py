"""`ak models` lists every model and effort the installed harnesses offer with the public boards'
numbers for each.

A row is a model at an effort a board lists or the config runs it at in any role; a board naming
no effort counts for every effort of its model; a row at another effort never stands in; a
board's model is matched by its letters and digits, else by the board's name the id extends with
a version, else, on a board where neither finds it, by `benchmark` on the config entry; the table
scores each row per role (tests/test_model_scores.py) and names the rows no board has.

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
from agentkit import boards, config, matrix, terminal
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
    case.stack.enter_context(patch.object(boards, "fetch_bytes", case.boards))
    # acme has a manifest and no binary here: none of its models gets a row
    case.stack.enter_context(patch.object(config, "manifests", return_value=[
        (harness, {}) for harness in (*CATALOGS, "acme")]))
    case.stack.enter_context(patch.object(config, "harness_present",
                                          side_effect=lambda harness: harness in CATALOGS))
    case.stack.enter_context(patch.object(config, "catalog", side_effect=CATALOGS.__getitem__))
    case.stack.enter_context(patch.object(terminal, "width", return_value=100))
    (config.SECRETS / boards.AA_KEY).write_text("k\n")
    case.cfg["models"]["wonder"] = {"harness": "muse", "model": "muse-wonder-full-1.0",
                                    "effort": "max", "provider": "meta"}


class ModelRows(Sandbox):
    def setUp(self):
        super().setUp()
        prepare(self)

    def table(self):
        held = boards.collect(now=10000)
        return {matrix.row_label(row): row
                for row in matrix.rows(self.cfg, held, matrix.present())}

    def test_a_row_per_effort_the_boards_list_or_the_config_runs(self):
        self.cfg["models"]["astra"]["exec_effort"] = "medium"
        rows = self.table()
        self.assertEqual({row["harness"] for row in rows.values()}, set(CATALOGS))
        self.assertEqual(sorted(name for name in rows if "opus-5-5" in name or name[:5] == "opus "),
                         ["claude-opus-5-5 @ max", "opus @ xhigh"])
        both = rows["claude-opus-5-5 @ max"]
        self.assertEqual(both["matched"], {
            "artificialanalysis.ai": {"model": "Claude Opus 5.5", "effort": "max"},
            "arena.ai": {"model": "Claude Opus 5.5", "effort": "max"},
            "livebench.ai": {"model": "claude-opus-5.5", "effort": None}})
        self.assertEqual(both["values"]["arena.agent_steerability"], 0.2)
        self.assertEqual(both["values"]["aa.pricing.price_1m_input_tokens"], 4.0)
        self.assertEqual(both["name"], None)
        # LiveBench names no effort: its numbers count at every effort of the model, its cost
        # of a task beside Artificial Analysis's cost of the run, which only max has
        self.assertEqual(rows["opus @ xhigh"]["values"]["livebench.coding"], 96.3)
        self.assertEqual(rows["opus @ xhigh"]["values"][boards.TASK_COST], round(113 / (29 * .963), 2))
        self.assertEqual((both["values"][matrix.COST], matrix.COST in rows["opus @ xhigh"]["values"]),
                         (20.69, False))
        # a row at another effort never stands in: the configured xhigh has no Arena numbers
        self.assertNotIn("arena.agent_task_outcome_explicit", rows["opus @ xhigh"]["values"])
        self.assertNotIn("arena.ai", rows["opus @ xhigh"]["matched"])
        # the boards' efforts count only among those the harness offers: Astra's xhigh does
        self.assertIn("astra @ xhigh", rows)
        self.assertEqual(rows["astra @ xhigh"]["values"]["arena.agent_task_outcome_explicit"], 0.137)
        # an effort one role runs it at is a row too, saying which, and Arena's xhigh row never
        # stands in
        self.assertEqual((rows["astra @ medium"]["name"], rows["astra @ medium"]["roles"], rows["astra @ medium"]["matched"]),
                         ("astra", ["execute"], {"livebench.ai": {"model": "gpt-6-astra", "effort": None}}))
        self.assertEqual((rows["astra @ xhigh"]["roles"], both["roles"]), (["orchestrate", "review"], []))
        # a board's `(Non-reasoning)` is ak's `none`, an effort Haiku offers
        self.assertEqual(rows["claude-haiku-4-5 @ none"]["matched"],
                         {"artificialanalysis.ai": {"model": "Claude Haiku 4.5", "effort": "none"}})
        # a model no board lists at any effort is one row at none
        self.assertEqual((rows["claude-opus-4-7"]["values"], rows["claude-opus-4-7"]["effort"]),
                         ({}, None))

    def test_a_board_s_model_is_found_by_its_name_a_version_or_benchmark(self):
        rows = self.table()
        # the id extends the board's name with a version: muse-wonder-full-1.0
        self.assertEqual(rows["wonder @ max"]["matched"],
                         {"artificialanalysis.ai": {"model": "Muse Wonder Full", "effort": "max"}})
        # `contributor` is no version: Artificial Analysis's `Muse Spark 1.3` is not found
        # until the entry says what to look for, and LiveBench's exact id is found either way
        lb = {"livebench.ai": {"model": "muse-spark-1.3-contributor", "effort": None}}
        self.assertEqual(rows["spark @ xhigh"]["matched"], lb)
        self.cfg["models"]["spark"]["benchmark"] = "Muse Spark 1.3"
        rows = self.table()
        self.assertEqual(rows["spark @ xhigh"]["matched"], {
            "artificialanalysis.ai": {"model": "Muse Spark 1.3", "effort": "xhigh"}, **lb})
        self.assertEqual(rows["spark @ xhigh"]["values"]["aa.evaluations.artificial_analysis_coding_index"], 40.0)
        # a shorter board name never stands for a longer id of another version
        index = {"claudesonnet5": [{"model": "Claude Sonnet 5", "effort": None, "values": {}}],
                 "claudesonnet55": [{"model": "Claude Sonnet 5.5", "effort": None, "values": {}}]}
        self.assertEqual(matrix.matching(index, "claude-sonnet-5-5", "max")["model"],
                         "Claude Sonnet 5.5")
        self.assertIsNone(matrix.matching({"claudesonnet5": index["claudesonnet5"]},
                                          "claude-sonnet-5-5", "max"))

    def test_the_table_scores_the_rows_the_boards_make_and_names_the_rest(self):
        held = boards.collect(now=10000)
        with patch.object(matrix.time, "time", return_value=10000):
            table = matrix.scored(matrix.rows(self.cfg, held, matrix.present()))
            lines = [terminal.plain(line) for line in matrix.render(table, held).splitlines()]
        text = "\n".join(lines)
        self.assertEqual(lines[0].split()[:3], ["model", "harness", "id"])
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines))
        # the configured xhigh row inherits LiveBench's numbers, which name no effort
        # the model's score for a role is its best-covered row's: xhigh holds one orchestrate
        # measure, max three, and nothing tells the two efforts apart; review has one of three
        self.assertRegex(lines[1], r"^- +claude +claude-opus-5-5 @ max +100 of 3 +100 of 3 +- +21 +4\.05$")
        self.assertRegex(lines[2], r"^opus +claude +claude-opus-5-5 @ xhigh +100 of 3 +100 of 3 +- +- +4\.05$")
        self.assertRegex(text, r"\nastra +codex +gpt-6-astra @ xhigh +- +- +- +- +-\n")
        # the run Artificial Analysis priced before the one it did not, whatever LiveBench charges
        self.assertIn("recommended: orchestrate claude-opus-5-5 @ max (100 of 3) · "
                      "execute claude-opus-5-5 @ max (100 of 3)", text)
        self.assertRegex(text, r"no board row: .*claude-opus-4-7")
        self.assertIn("arena.ai: 4 rows as of", text)
        out = io.StringIO()
        with redirect_stdout(out), patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(matrix.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(sorted(data), ["boards", "live", "recommended", "rows", "within"])
        self.assertNotIn("rows", data["boards"]["arena.ai"])
        rows = {matrix.row_label(row): row for row in data["rows"]}
        self.assertEqual(rows["claude-opus-5-5 @ max"]["scores"]["orchestrate"], {"score": 100.0, "measures": 3})
        self.assertIsNone(rows["claude-opus-5-5 @ max"]["scores"]["review"])     # one of three measures

    def test_a_board_row_s_effort_is_kept_apart_from_a_bracket_of_its_name(self):
        # a bracket naming no effort stays on the board's name: `Acme Pro (0813)` is at none
        held = {"livebench.ai": {"rows": [{"model": "Acme Pro (0813)", "effort": None,
                                           "values": {"livebench.coding": 1.0}}]}}
        self.cfg["models"]["opus"]["benchmark"] = "Acme Pro (0813)"
        table = [row for row in matrix.rows(self.cfg, held, matrix.present())
                 if row["name"] == "opus"]
        self.assertEqual(table[0]["matched"],
                         {"livebench.ai": {"model": "Acme Pro (0813)", "effort": None}})


if __name__ == "__main__":
    unittest.main()
