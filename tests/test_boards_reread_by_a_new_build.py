"""A board held from another build of ak whose cached rows carry none of a column the formula
reads is asked again before the day is up, once: its reader changed, and a day of empty scores
is stale state.  The same build asks no board twice a day, and a board whose rows carry every
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
from agentkit import boards, matrix, update
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

    def test_the_matrix_asks_for_every_column_it_scores_with_its_build(self):
        needs = matrix.needed()
        self.assertEqual(sorted(needs), sorted(boards.BOARDS))
        self.assertIn(matrix.COST, needs["artificialanalysis.ai"])
        self.assertIn("livebench.coding", needs["livebench.ai"])
        self.assertIn("arena.agent_steerability", needs["arena.ai"])
        self.assertEqual({column for columns in needs.values() for column in columns},
                         {matrix.COST, matrix.INTEL, matrix.TASK_COST}
                         | {column for role in matrix.ROLES.values() for column, _, _ in role})
        with patch.object(update, "agentkit_version", return_value="abc1234"):
            matrix.refresh(self.cfg, now=10000)
        asked = self.asked("huggingface")
        self.forget("arena.ai", "arena.agent_steerability")
        with patch.object(update, "agentkit_version", return_value="def5678"):
            held, _ = matrix.refresh(self.cfg, now=10001)
        self.assertGreater(self.asked("huggingface"), asked)
        self.assertEqual(held["arena.ai"]["build"], "def5678")
        self.assertEqual(matrix.stored()["computed_at"], 10001)   # computed on what came


if __name__ == "__main__":
    unittest.main()
