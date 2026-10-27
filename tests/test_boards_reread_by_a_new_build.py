"""A board held from another build of ak whose cached rows carry none of a column the formula
reads is asked again before the day is up, once: its reader changed, and a day of empty scores
is stale state, and so is one held from a build before its reader gave `boards.ADDED`.  The same build asks no board twice a day, and a board whose rows carry every
column it needs waits for the day.  The boards' answers are faked; a throwaway HOME."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, matrix, quality, update
from test_model_matrix import Boards


class Reread(Sandbox):
    def setUp(self):
        super().setUp()
        self.boards = Boards()
        self.stack.enter_context(patch.object(boards, "fetch_bytes", self.boards))

    def asked(self, host):
        return sum(host in url for url, _ in self.boards.asked)

    def forget(self, board, column):
        """The cached rows of `board` without `column`: a reader that never gave it."""
        cache = json.loads(boards.cache_path().read_text())
        for row in cache[board]["rows"]:
            row["values"].pop(column, None)
        boards.cache_path().write_text(json.dumps(cache))

    def test_a_new_build_asks_again_for_a_column_the_cached_rows_lack_once(self):
        held = boards.collect(now=10000, build="abc1234")
        self.assertEqual(held["livebench.ai"]["build"], "abc1234")
        asked = self.asked("livebench.ai")
        needs = {"livebench.ai": {"livebench.coding", "livebench.reasoning"}}
        self.forget("livebench.ai", "livebench.coding")
        # the build that read them asks no board twice a day
        boards.collect(now=10001, needs=needs, build="abc1234")
        self.assertEqual(self.asked("livebench.ai"), asked)
        # a new build reading a column they carry none of asks again, and only that board
        others = len(self.boards.asked) - asked
        held = boards.collect(now=10001, needs=needs, build="def5678")
        self.assertEqual(self.asked("livebench.ai"), 2 * asked)      # read whole once more
        self.assertEqual(len(self.boards.asked) - self.asked("livebench.ai"), others)
        self.assertEqual((held["livebench.ai"]["build"], held["livebench.ai"]["fetched_at"]),
                         ("def5678", 10001))
        self.assertTrue(all("livebench.coding" in row["values"]
                            for row in held["livebench.ai"]["rows"]))
        # a board whose rows carry every column of the need waits for the day, new build or not
        self.forget("livebench.ai", "livebench.reasoning")
        boards.collect(now=10002, needs={"livebench.ai": {"livebench.coding"}}, build="ghi9012")
        self.assertEqual(self.asked("livebench.ai"), 2 * asked)
        # once: a column the board gives no row at all waits for the day like any other
        self.forget("livebench.ai", "livebench.coding")
        boards.collect(now=10003, needs=needs, build="def5678")
        self.assertEqual(self.asked("livebench.ai"), 2 * asked)
        # and no build given, as `--refresh` and the tests ask, is the day alone
        boards.collect(now=10004, needs=needs)
        self.assertEqual(self.asked("livebench.ai"), 2 * asked)

    def test_a_new_build_asks_again_for_a_board_whose_cache_holds_no_row(self):
        needs = {"livebench.ai": {"livebench.coding"}}
        self.boards.down.add("livebench.ai")
        boards.collect(now=10000, build="abc1234")          # a first read that failed: no rows at all
        self.boards.down.clear()
        asked = self.asked("livebench.ai")
        boards.collect(now=10001, needs=needs, build="abc1234")
        self.assertEqual(self.asked("livebench.ai"), asked)     # the build that read it waits for the day
        held = boards.collect(now=10001, needs=needs, build="def5678")
        self.assertGreater(self.asked("livebench.ai"), asked)
        self.assertTrue(held["livebench.ai"]["rows"])
        # a read that gave no row, held as an empty list, carries no column either
        cache = json.loads(boards.cache_path().read_text())
        cache["livebench.ai"]["rows"] = []
        boards.cache_path().write_text(json.dumps(cache))
        asked = self.asked("livebench.ai")
        held = boards.collect(now=10002, needs=needs, build="ghi9012")
        self.assertGreater(self.asked("livebench.ai"), asked)
        self.assertTrue(held["livebench.ai"]["rows"])

    def test_a_board_read_before_its_reader_gave_the_added_columns_is_asked_again_once(self):
        boards.collect(now=10000, build="abc1234")
        cache = json.loads(boards.cache_path().read_text())
        for board in ("artificialanalysis.ai", "arena.ai"):     # as a build before them stored it
            for row in cache[board]["rows"]:
                row["values"] = {column: value for column, value in row["values"].items()
                                 if not column.startswith("aa.intelligenceIndexEvaluations.")
                                 and not column.endswith("95ci")}
        boards.cache_path().write_text(json.dumps(cache))
        asked = {host: self.asked(host) for host in ("artificialanalysis", "huggingface", "livebench")}
        held = boards.collect(now=10001, build="def5678")
        self.assertEqual({host: self.asked(host) for host in asked},
                         {"artificialanalysis": 2 * asked["artificialanalysis"],
                          "huggingface": 2 * asked["huggingface"], "livebench": asked["livebench"]})
        carried = {column for board in held.values() for row in board["rows"]
                   for column in row["values"]}
        self.assertTrue({"arena.agent.lower95ci", "aa.intelligenceIndexEvaluations.acme-bench.score"}
                        <= carried)
        boards.collect(now=10002, build="ghi9012")                # its rows carry them now: once
        self.assertEqual(self.asked("huggingface"), 2 * asked["huggingface"])
        self.assertEqual(self.asked("artificialanalysis"), 2 * asked["artificialanalysis"])

    def test_the_matrix_asks_for_every_column_it_scores_with_its_build(self):
        needs = matrix.needed()
        self.assertEqual(sorted(needs), sorted(boards.BOARDS))
        self.assertIn(quality.COSTS["execute"], needs["artificialanalysis.ai"])
        self.assertIn("aa.omniscienceAccuracy", needs["artificialanalysis.ai"])   # its error's
        self.assertIn("arena.agent.lower95ci", needs["arena.ai"])
        self.assertEqual({column for columns in needs.values() for column in columns},
                         {quality.INTEL, *quality.COSTS.values()}
                         | {name for role in quality.ROLES.values() for column, _, _ in role
                            for name in (column, *quality.reads(column))})
        with patch.object(update, "agentkit_version", return_value="abc1234"):
            matrix.refresh(self.cfg, now=10000)
        asked = self.asked("huggingface")
        self.forget("arena.ai", "arena.agent")
        with patch.object(update, "agentkit_version", return_value="def5678"):
            held, _ = matrix.refresh(self.cfg, now=10001)
        self.assertGreater(self.asked("huggingface"), asked)
        self.assertEqual(held["arena.ai"]["build"], "def5678")
        self.assertEqual(matrix.stored()["computed_at"], 10001)   # computed on what came


if __name__ == "__main__":
    unittest.main()
